import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. KEGG 深度檢索邏輯 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    if not jp_text or pd.isna(jp_text): return None
    # 僅提取開頭的片假名（排除廠商名）
    clean_kw = str(jp_text).strip().split('\n')[0]
    match = re.search(r'^([ァ-ヶー・]+)', clean_kw)
    kw = match.group(1) if match else None
    
    if not kw: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()

    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match: return None

        japic_code = japic_match.group(1)
        time.sleep(0.3) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 成分名 (欧文一般名)
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名 (Trade Name)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers).text
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 2. 核心清洗邏輯：專治「無法辨識」與「藍框外雜訊」 ---
def clean_pmda_v7(df):
    if len(df) < 3: return None
    
    # 直接硬鎖第 3 行為標題 (Index 2)
    header_row = df.iloc[2]
    # 徹底清除標題中的空格與換行
    clean_header = [re.sub(r'[\s\u3000\n]+', '', str(x)) for x in header_row]
    
    # 定位關鍵欄位座標
    idx_no, idx_trade, idx_ing = None, None, None
    for i, h in enumerate(clean_header):
        if 'No' in h: idx_no = i
        if '販賣名' in h: idx_trade = i
        if '成分名' in h: idx_ing = i
        
    if idx_trade is None or idx_ing is None: return None

    # 從第 4 行 (Index 3) 開始向下掃描
    valid_list = []
    for i in range(3, len(df)):
        row = df.iloc[i]
        val_no = str(row[idx_no]).strip() if idx_no is not None else ""
        val_trade = str(row[idx_trade]).strip()
        val_ing = str(row[idx_ing]).strip()

        # 🛑 藍框截斷邏輯：如果 No. 不是純數字，代表離開了有效範圍
        if not val_no.isdigit():
            if len(valid_list) > 0: break # 已有資料後遇到非數字即切斷
            continue # 開頭空行跳過
            
        if val_trade == "" or val_trade.lower() == 'nan': break # 遇到空列即停止

        valid_list.append({
            "No.": val_no,
            "Trade_JP": val_trade,
            "Ing_JP": val_ing
        })
        
    return pd.DataFrame(valid_list)

# --- 3. Streamlit UI ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯終極修復版")
st.title("💊 PMDA 藥品翻譯 (v7.0 座標硬鎖版)")

up_file = st.file_uploader("上傳 PMDA 檔案 (Excel 或 CSV)", type=['xlsx', 'csv'])

if up_file:
    # 讀取資料
    if up_file.name.endswith('.csv'):
        raw = pd.read_csv(up_file, header=None)
        sheets = ["預設 CSV"]
    else:
        xls = pd.ExcelFile(up_file)
        sheets = xls.sheet_names
        
    sheet_name = st.selectbox("請選擇月份分頁：", sheets)
    
    if sheet_name:
        if not up_file.name.endswith('.csv'):
            raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            
        clean_df = clean_pmda_v7(raw)
        
        if clean_df is not None and not clean_df.empty:
            st.success(f"✅ 辨識成功！偵測到 {len(clean_df)} 筆有效紀錄（已排除藍框外無效區域）")
            st.table(clean_df.head(10)) # 顯示前10筆預覽
            
            if st.button("🚀 開始翻譯檢索"):
                results = []
                status = st.status("正在進行 JAPIC 深度路徑檢索...", expanded=True)
                log = st.empty()
                pbar = st.progress(0)
                
                for idx, row in clean_df.iterrows():
                    # 執行檢索
                    en_t = get_kegg_advanced_info(row['Trade_JP'], log, is_trade=True)
                    en_i = get_kegg_advanced_info(row['Ing_JP'], log, is_trade=False)
                    
                    results.append({
                        "No.": row['No.'],
                        "日文販賣名": row['Trade_JP'],
                        "Trade Name (EN)": en_t if en_t else "[請手動核對]",
                        "日文成分名": row['Ing_JP'],
                        "Ingredient (EN)": en_i if en_i else "[請手動核對]"
                    })
                    pbar.progress((idx + 1) / len(clean_df))
                    
                status.update(label="✅ 處理完成", state="complete")
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                st.download_button("📥 下載翻譯結果", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), f"PMDA_Result.csv")
        else:
            st.error("⚠️ 無法辨識。程式已固定搜尋第 3 行，請確認該行是否包含『販賣名』。")
