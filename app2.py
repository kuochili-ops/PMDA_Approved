import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 依照您的原則：精確提取開頭連續片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip().split('\n')[0] # 只取第一行
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯：真人模擬深度爬取 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        
        # 尋找 JAPIC Code
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match: return None

        japic_code = japic_match.group(1)
        
        # Step 2: 進入 JAPIC 總表頁
        time.sleep(0.5) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_resp = session.get(med_url, headers=headers, timeout=15)
        med_html = med_resp.text

        if not is_trade:
            # 抓取成分名 (欧文一般名)
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 抓取商品名 (Trade Name)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers, timeout=15)
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp.text, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except:
        pass
    return None

# --- 3. 精確資料清理：模擬 Excel 藍框截斷 ---
def clean_dataframe(df):
    # 搜尋標題行 (通常在第 3 行，Index 2)
    header_idx = None
    for i in range(min(10, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i] if pd.notnull(c)])
        row_str = re.sub(r'[\s\u3000\n]+', '', row_str)
        if '販賣名' in row_str or ('成分' in row_str and '名' in row_str):
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 設定標題
    df.columns = df.iloc[header_idx]
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位標準化
    rename_map = {}
    for col in temp_df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    temp_df = temp_df.rename(columns=rename_map)
    
    # --- 🛑 核心修復：強制截斷「藍框」外資料 ---
    valid_rows = []
    for _, row in temp_df.iterrows():
        val_no = str(row.get('No.', '')).strip().replace('.0','')
        val_trade = str(row.get('JP_Trade', '')).strip()
        
        # 截斷機制：如果 No. 不是數字 (可能是空白或注1)，立即停止
        if not val_no.isdigit():
            if len(valid_rows) > 0: break # 如果已經抓過資料了，遇到非數字就當作結束
            continue # 開頭的空行則跳過
            
        if val_trade == "" or val_trade.lower() == 'nan': break
            
        valid_rows.append(row)
        
    return pd.DataFrame(valid_rows).reset_index(drop=True)

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯終極版")
    st.title("💊 PMDA 藥品清單翻譯 (JAPIC 深度路徑修正版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 讓使用者可以選擇分頁
        sheet_selected = st.selectbox("選擇要處理的分頁 (月份)：", xls.sheet_names)
        
        if sheet_selected:
            raw_df = pd.read_excel(xls, sheet_name=sheet_selected, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 成功辨識 {len(df)} 筆紀錄 (已過濾藍框外無效區域)")
                st.dataframe(df.head(5), use_container_width=True)
                
                if st.button(f"開始執行 {sheet_selected} 翻譯"):
                    results = []
                    status = st.status("正在進行深度檢索...", expanded=True)
                    log_area = st.empty()
                    pbar = st.progress(0)
                    
                    for idx, row in df.iterrows():
                        # 執行檢索
                        en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        
                        results.append({
                            "No.": row.get('No.', idx+1),
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_trade if en_trade else "[查無結果]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_ing if en_ing else "[查無結果]"
                        })
                        pbar.progress((idx + 1) / len(df))
                        time.sleep(0.3) # 防止請求過快
                        
                    status.update(label="✅ 檢索完成", state="complete")
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    st.download_button("📥 下載翻譯結果", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), f"PMDA_{sheet_selected}.csv")
            else:
                st.error("⚠️ 無法辨識有效紀錄。請確認分頁第 3 行包含『販賣名』與『成分名』。")

if __name__ == "__main__":
    main()
