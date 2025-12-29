import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# 更新標記：2025-12-29 12:45

# --- 1. 片假名提取 (確保精確度) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 物理移除換行與所有類型的括號內容
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 深度檢索邏輯 (解決截圖中的「查無結果」) ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        # Step 1: 搜尋 JAPIC
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        
        if not japic_match:
            # 備援：D編號 (Entry ID)
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade:
                api_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}", timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None

        japic_code = japic_match.group(1)
        time.sleep(0.3) 
        
        # Step 2: 進入詳情頁面
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 歐文一般名
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名 (修正點：截圖查無結果是因為原本路徑太窄)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                p_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                p_resp = session.get(p_url, headers=headers).text
                # 採用最寬鬆的 HTML 抓取模式，確保內容必中
                trade_match = re.search(r'class="md_td_en">([^<]+)</td>', p_resp)
                if trade_match:
                    return trade_match.group(1).strip()
    except: pass
    return None

# --- 3. 寬鬆標題偵測 (終結「仍無法辨識」) ---
def clean_dataframe(df):
    header_idx = None
    target_cols = {}

    # 擴大搜尋範圍到前 20 行
    for i in range(min(20, len(df))):
        # 將整行內容壓縮成純文字，不留任何空格
        row_str = "".join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in df.iloc[i] if pd.notnull(c)])
        
        # 寬鬆條件：只要包含「販」與「成」字就判定為標題行
        if '販' in row_str and '成' in row_str:
            header_idx = i
            # 自動抓取對應欄位座標
            for idx, cell in enumerate(df.iloc[i]):
                c = re.sub(r'[\s\u3000\n]+', '', str(cell))
                if 'No' in c: target_cols['No'] = idx
                if '販' in c: target_cols['Trade'] = idx
                if '成' in c: target_cols['Ing'] = idx
            break
            
    if header_idx is None or 'Trade' not in target_cols: return None
    
    # 過濾有效資料列
    df_rows = df.iloc[header_idx + 1:].reset_index(drop=True)
    results = []
    for _, row in df_rows.iterrows():
        val_no = str(row.iloc[target_cols.get('No', 0)]).strip().replace('.0','')
        val_trade = str(row.iloc[target_cols['Trade']]).strip()
        val_ing = str(row.iloc[target_cols['Ing']]).strip()

        # 數字檢查：確保只抓藍框內資料，其餘（注釋等）一律截斷
        if not val_no.isdigit():
            if len(results) > 0: break
            continue
            
        if val_trade == "" or val_trade.lower() == 'nan': break
        
        results.append({
            "No.": val_no,
            "JP_Trade": val_trade,
            "JP_Ingredient": val_ing
        })
        
    return pd.DataFrame(results)

# --- 4. UI 介面 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 藥品清單翻譯 (最終相容版：2025-12-29 12:45)")

up = st.file_uploader("上傳 Excel", type=['xlsx'])
if up:
    xls = pd.ExcelFile(up)
    sheet = st.selectbox("請選擇分頁：", xls.sheet_names)
    if sheet:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        df = clean_dataframe(raw)
        
        if df is not None and not df.empty:
            st.success(f"✅ 辨識成功！偵測到 {len(df)} 筆藥品資料。")
            if st.button("🚀 執行深度檢索"):
                status = st.status("正在檢索 KEGG/JAPIC...", expanded=True)
                log = st.empty()
                final_data = []
                for idx, r in df.iterrows():
                    log.write(f"正在分析 No.{r['No.']}: {r['JP_Trade'][:15]}...")
                    en_t = get_kegg_advanced_info(r['JP_Trade'], log, True)
                    en_i = get_kegg_advanced_info(r['JP_Ingredient'], log, False)
                    final_data.append({
                        "No.": r['No.'],
                        "商品名(日)": r['JP_Trade'],
                        "Trade Name (EN)": en_t if en_t else "[查無結果]",
                        "成分名(日)": r['JP_Ingredient'],
                        "Ingredient (EN)": en_i if en_i else "[查無結果]"
                    })
                    time.sleep(0.5)
                status.update(label="✅ 檢索完成", state="complete")
                st.dataframe(pd.DataFrame(final_data), use_container_width=True)
        else:
            st.error("⚠️ 無法辨識標題列。請確認 Excel 內容中包含「販賣名」欄位。")
