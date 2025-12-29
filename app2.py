import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io

# 版本標記：2025-12-29 14:15

# --- 1. 片假名提取 (修正版：不論位置，抓取第一串連續片假名) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    # 修正邏輯：搜尋字串中第一組出現的片假名（包含長音符與點）
    match = re.search(r'([ァ-ヶー・]+)', text)
    if match:
        result = match.group(1)
        # 排除掉太短的無意義字元
        return result if len(result) > 1 else None
    return None

# --- 2. 檢索邏輯 (強化 JAPIC 第一順位) ---
def get_kegg_advanced_info(jp_text, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()

    try:
        # 優先搜尋 JAPIC
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        html = resp.text

        # 1. 嘗試抓取 JAPIC Code (可能是直接進入或列表頁)
        japic_match = re.search(r'japic_code=(\d+)', html)
        if not japic_match:
            # 列表頁備援
            list_match = re.search(r'href="[^"]*japic_code=(\d+)"', html)
            japic_code = list_match.group(1) if list_match else None
        else:
            japic_code = japic_match.group(1)

        if japic_code:
            time.sleep(0.3)
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            med_html = session.get(med_url, headers=headers).text
            
            if not is_trade:
                ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
                if ing_match: return re.sub(r'<.*?>', '', ing_match.group(1)).strip()
            else:
                prod_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
                if prod_match:
                    p_resp = session.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_match.group(1)}", headers=headers).text
                    trade_match = re.search(r'class="md_td_en">([^<]*)</td>', p_resp, re.S)
                    if trade_match: return trade_match.group(1).strip()
        
        # 2. 備援：如果 JAPIC 沒結果，嘗試Rest API (D編號)
        entry_match = re.search(r'/entry/(D\d+)', html)
        if entry_match:
            d_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}").text
            name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', d_resp)
            if name_match: return name_match.group(1).strip()
            
    except: pass
    return None

# --- 3. 資料清理 (強化座標校正) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        row_str = "".join(row)
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(row):
                if 'No' in cell: cols['No'] = idx
                if '販' in cell: cols['Trade'] = idx
                if '成' in cell: cols['Ing'] = idx
            break
            
    if header_idx is None or 'Trade' not in cols: return None
    
    final_rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        # 遇到非數字 No 且已經有資料，視為結尾
        if not val_no.isdigit():
            if len(final_rows) > 0: break
            continue
            
        final_rows.append({
            "No.": val_no,
            "JP_Trade": str(row.iloc[cols['Trade']]).strip(),
            "JP_Ingredient": str(row.iloc[cols['Ing']]).strip()
        })
    return pd.DataFrame(final_rows)

# --- 4. Streamlit UI ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 藥品清單翻譯 (片假名強化版：2025-12-29 14:15)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    xls = pd.ExcelFile(f)
    sheet = st.selectbox("選擇分頁", xls.sheet_names)
    if sheet:
        df = clean_dataframe(pd.read_excel(xls, sheet_name=sheet, header=None))
        if df is not None:
            st.success(f"✅ 辨識成功！數據：{len(df)} 筆")
            if st.button("🚀 執行片假名精確檢索"):
                results = []
                bar = st.progress(0)
                log = st.empty()
                for i, r in df.iterrows():
                    # 這裡會在 UI 顯示抓到的關鍵字，您可以確認是否正確
                    kw_t = get_katakana_prefix(r['JP_Trade'])
                    kw_i = get_katakana_prefix(r['JP_Ingredient'])
                    log.text(f"No.{r['No.']} 關鍵字：[{kw_t}] / [{kw_i}]")
                    
                    en_t = get_kegg_advanced_info(r['JP_Trade'], True)
                    en_i = get_kegg_advanced_info(r['JP_Ingredient'], False)
                    
                    results.append({
                        "No.": r['No.'],
                        "商品名(日)": r['JP_Trade'],
                        "Trade Name (EN)": en_t or "[查無結果]",
                        "成分名(日)": r['JP_Ingredient'],
                        "Ingredient (EN)": en_i or "[查無結果]"
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載 Excel", output.getvalue(), f"{sheet}_EN.xlsx")
