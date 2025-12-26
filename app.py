import streamlit as st
import pandas as pd
import requests
import re
from urllib.parse import quote

# --- 1. 依照您的原則：提取開頭連續片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯：網頁深度爬取 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        # Step 1: 搜尋並獲取 JAPIC Code (例如 00071731)
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = requests.get(search_url, headers=headers, timeout=10)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        
        if not japic_match:
            return None
        japic_code = japic_match.group(1)

        # Step 2: 進入 JAPIC 總表頁 (japic_med)
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_resp = requests.get(med_url, headers=headers, timeout=10)
        med_html = med_resp.text

        if not is_trade:
            # 成分名：在總表頁找 "欧文一般名"
            ing_match = re.search(r'<th>欧文一般名</th><td>(.*?)</td>', med_html)
            if ing_match:
                res = ing_match.group(1).strip()
                log_container.write(f"✅ 成分名命中: `{kw}` -> `{res}`")
                return res
        else:
            # 商品名：必須進入產品細節頁 (japic_med_product)
            # 找到第一個出現的 product id (例如 00071731-001)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_id = prod_id_match.group(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id}"
                prod_resp = requests.get(prod_url, headers=headers, timeout=10)
                prod_html = prod_resp.text
                
                # 關鍵修正：針對您提到的 スピジア 頁面結構
                # 英文商品名通常放在 class="md_td_en" 的 <td> 中
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_html)
                if trade_match:
                    res = trade_match.group(1).strip()
                    log_container.write(f"✅ 商品名命中: `{kw}` -> `{res}`")
                    return res
                
                # 備案：如果沒有標籤，找包含藥品劑型關鍵字的英文字串
                backup_match = re.search(r'<td>([A-Za-z\s]{3,}(?:Nasal|Spray|Tablet|Capsule|Injection).*?)</td>', prod_html)
                if backup_match:
                    return backup_match.group(1).strip()

    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 檢索出錯")
    return None

# --- 3. 精確資料清理 ---
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
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 藥品清單翻譯 (JAPIC 深度爬取版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            if df is None or df.empty: continue
                
            st.write(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            with st.status(f"執行深度檢索...", expanded=True) as status:
                log_area = st.empty()
                results = []
                for _, row in df.iterrows():
                    en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                    en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                    
                    results.append({
                        "No.": row.get('No.', ''),
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_trade if en_trade else "[Azure] " + str(row['JP_Trade']),
                        "來源(T)": "KEGG/JAPIC" if en_trade else "Azure",
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_ing if en_ing else "[Azure] " + str(row['JP_Ingredient']),
                        "來源(I)": "KEGG/JAPIC" if en_ing else "Azure"
                    })
                status.update(label="檢索完成", state="complete")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
