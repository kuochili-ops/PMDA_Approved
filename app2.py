import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 完全保留您的：精確提取開頭連續片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 完全保留您的：真人模擬深度爬取邏輯 (針對 JAPIC 細節頁) ---
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
        med_resp = session.get(med_url, headers=headers, timeout=15)
        med_html = med_resp.text

        if not is_trade:
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return ing_match.group(1).strip() if ing_match else None
        else:
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                time.sleep(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers, timeout=15)
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp.text, re.S)
                if trade_match:
                    return trade_match.group(1).strip()
    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 請求失敗")
    return None

# --- 3. 修正後的資料清洗：專治 PMDA 標題全形空格 ---
def clean_dataframe_v9_5(df):
    header_idx = None
    # 掃描前 10 行，尋找包含「販賣名」特徵的行
    for i in range(min(10, len(df))):
        # 關鍵：將整行內容轉為字串並移除所有空格、全形空格、換行
        row_str = "".join([str(c) for c in df.iloc[i] if pd.notnull(c)])
        row_str = re.sub(r'[\s\u3000\n]+', '', row_str) 
        
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 找到標題後，手動定位欄位 Index
    header_row = df.iloc[header_idx].astype(str).tolist()
    col_map = {}
    for idx, name in enumerate(header_row):
        clean_name = re.sub(r'[\s\u3000\n]+', '', name)
        if 'No' in clean_name: col_map['No'] = idx
        if '販賣名' in clean_name: col_map['Trade'] = idx
        if '成分名' in clean_name: col_map['Ing'] = idx

    # 提取資料並進行「藍框」邊界截斷
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    valid_rows = []
    for _, row in temp_df.iterrows():
        val_no = str(row.iloc[col_map.get('No', 0)]).strip().replace('.0','')
        val_trade = str(row.iloc[col_map['Trade']]).strip()
        val_ing = str(row.iloc[col_map['Ing']]).strip()

        # 🛑 核心保護：一旦 No 不是數字（遇到注1或空行），立刻停止讀取（藍框外）
        if not val_no.isdigit():
            if len(valid_rows) > 0: break 
            continue 
            
        if val_trade == "" or val_trade.lower() == 'nan': break
        
        valid_rows.append({
            "No.": val_no,
            "JP_Trade": val_trade,
            "JP_Ingredient": val_ing
        })
        
    return pd.DataFrame(valid_rows)

# --- 4. Streamlit 介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
    st.title("💊 PMDA 藥品翻譯 (採用您的 JAPIC 檢索邏輯)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        sheet_name = st.selectbox("請選擇分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe_v9_5(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 辨識成功！分頁「{sheet_name}」有效數據：{len(df)} 筆")
                st.dataframe(df, use_container_width=True)
                
                if st.button("🚀 開始執行您的深度檢索"):
                    results = []
                    log_area = st.empty()
                    for idx, row in df.iterrows():
                        log_area.write(f"正在檢索 No.{row['No.']}: {row['JP_Trade'][:15]}...")
                        # 呼叫您的邏輯
                        en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        
                        results.append({
                            "No.": row['No.'],
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_trade if en_trade else "[查無結果]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_ing if en_ing else "[查無結果]"
                        })
                        time.sleep(0.5)
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.error("⚠️ 仍無法辨識。請確認分頁標題是否包含『販賣名』。")

if __name__ == "__main__":
    main()
