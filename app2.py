import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 完全保留您的：片假名提取 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 完全保留您的：核心檢索邏輯 ---
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
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match:
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade:
                api_url = f"https://rest.kegg.jp/get/{entry_match.group(1)}"
                api_resp = session.get(api_url, timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None
        japic_code = japic_match.group(1)
        time.sleep(1) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers, timeout=15).text
        if not is_trade:
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return ing_match.group(1).strip() if ing_match else None
        else:
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                time.sleep(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers, timeout=15).text
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 3. 關鍵修正：確保能認出 PMDA 的特殊標題 (如 5 月份) ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        # 改良點：先移除格子裡所有的空格與換行，再找關鍵字
        row_str = ''.join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in row if pd.notnull(c)])
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        # 同樣移除空白後進行欄位對齊
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        # 排除 5、6 月份後方幾千行空白的關鍵：確保 No. 是純數字
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
    st.title("💊 PMDA 藥品清單翻譯 (深度路徑修復版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 增加分頁選擇，這是處理 5 月份檔案的必備步驟
        sheet_name = st.selectbox("請選擇月份分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 辨識成功！分頁：{sheet_name} (有效數據: {len(df)} 筆)")
                if st.button("🚀 開始檢索"):
                    log_area = st.empty()
                    results = []
                    for _, row in df.iterrows():
                        en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        results.append({
                            "No.": row.get('No.', ''),
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_trade if en_trade else "[查無結果]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_ing if en_ing else "[查無結果]"
                        })
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.error("⚠️ 仍無法辨識。請確認分頁標題包含『販賣名』。")

if __name__ == "__main__":
    main()
