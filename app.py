import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 核心邏輯：依照您的原則提取片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 核心邏輯：JAPIC Code 深度檢索 ---
def get_kegg_japic_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    try:
        # Step 1: 搜尋關鍵字獲取 JAPIC Code
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(search_url, headers=headers, timeout=10)
        
        # 尋找 japic_code=XXXXX
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match:
            return None
        
        japic_code = japic_match.group(1)
        log_container.write(f"🔍 `{kw}` 找到 JAPIC Code: `{japic_code}`")

        # Step 2: 進入 japic_med 頁面
        info_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        info_resp = requests.get(info_url, headers=headers, timeout=10)
        info_html = info_resp.text

        if is_trade:
            # 商品名：尋找表格中的歐文商品名
            # 規則：在 japic_med_product 連結旁的 <td> 內容
            trade_match = re.search(r'japic_med_product\?id=.*?>.*?</a></td><td>(.*?)</td>', info_html)
            if trade_match:
                res = trade_match.group(1).strip()
                log_container.write(f"✅ 商品名: `{res}`")
                return res
        else:
            # 成分名：尋找 <th>欧文一般名</th> 之後的 <td>
            ing_match = re.search(r'<th>欧文一般名</th><td>(.*?)</td>', info_html)
            if ing_match:
                res = ing_match.group(1).strip()
                log_container.write(f"✅ 成分名: `{res}`")
                return res
                
    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 檢索出錯")
    return None

# --- 資料清理邏輯 (確保 No. 1~10 正確) ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(c) for c in row if pd.notnull(c)])
        if '販' in row_str and '名' in row_str:
            header_idx = i
            break
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        if 'No.' in df.columns:
            # 僅保留 No. 欄位為純數字的行
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 翻譯 (JAPIC 深度檢索版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            if df is None or df.empty: continue
                
            st.write(f"### 📄 分頁：{sheet_name}")
            with st.status(f"執行中...", expanded=True) as status:
                log_area = st.empty()
                results = []
                for _, row in df.iterrows():
                    en_trade = get_kegg_japic_info(row['JP_Trade'], log_area, is_trade=True)
                    en_ing = get_kegg_japic_info(row['JP_Ingredient'], log_area, is_trade=False)
                    
                    results.append({
                        "No.": row.get('No.', ''),
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_trade if en_trade else "[Azure] " + str(row['JP_Trade']),
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_ing if en_ing else "[Azure] " + str(row['JP_Ingredient'])
                    })
                status.update(label="完成", state="complete")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
