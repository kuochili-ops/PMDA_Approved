import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io

# 版本標記：2025-12-29 14:45

# --- 1. 片假名提取工具 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    # 找尋第一組出現的片假名（包含長音符與中點）
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 2. 核心檢索邏輯 ---
def get_kegg_advanced_info(kw, is_trade=True):
    if not kw or len(kw) < 2: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()

    try:
        # 搜尋 JAPIC
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        html = resp.text

        # 找 JAPIC Code
        japic_match = re.search(r'japic_code=(\d+)', html)
        if not japic_match:
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
        
        # 備援：D編號
        entry_match = re.search(r'/entry/(D\d+)', html)
        if entry_match:
            d_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}").text
            name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', d_resp)
            if name_match: return name_match.group(1).strip()
            
    except: pass
    return None

# --- 3. 資料清理與獨立欄位生成 ---
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
        if not val_no.isdigit():
            if len(final_rows) > 0: break
            continue
            
        trade_full = str(row.iloc[cols['Trade']]).strip()
        ing_full = str(row.iloc[cols['Ing']]).strip()
        
        # 生成獨立片假名欄位
        kw_t = get_katakana_prefix(trade_full)
        kw_i = get_katakana_prefix(ing_full)
            
        final_rows.append({
            "No.": val_no,
            "商品名(日)": trade_full,
            "商品名(關鍵字)": kw_t, # 獨立出的欄位
            "成分名(日)": ing_full,
            "成分名(關鍵字)": kw_i  # 獨立出的欄位
        })
    return pd.DataFrame(final_rows)

# --- 4. Streamlit UI ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (片假名獨立顯示版：2025-12-29 14:45)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    xls = pd.ExcelFile(f)
    sheet = st.selectbox("選擇分頁", xls.sheet_names)
    if sheet:
        df = clean_dataframe(pd.read_excel(xls, sheet_name=sheet, header=None))
        if df is not None:
            st.success(f"✅ 辨識成功！請檢查下方「關鍵字」欄位是否提取正確。")
            # 讓使用者先看資料提取得對不對
            st.dataframe(df, use_container_width=True)
            
            if st.button("🚀 確認關鍵字正確，開始翻譯"):
                results = []
                bar = st.progress(0)
                log = st.empty()
                for i, r in df.iterrows():
                    log.text(f"正在檢索: {r['商品名(關鍵字)']}...")
                    
                    en_t = get_kegg_advanced_info(r['商品名(關鍵字)'], True)
                    en_i = get_kegg_advanced_info(r['成分名(關鍵字)'], False)
                    
                    results.append({
                        "No.": r['No.'],
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": en_t or "[查無結果]",
                        "成分名(日)": r['成分名(日)'],
                        "Ingredient (EN)": en_i or "[查無結果]"
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                res_df = pd.DataFrame(results)
                st.subheader("📊 翻譯結果")
                st.dataframe(res_df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載翻譯結果", output.getvalue(), f"PMDA_EN_{sheet}.xlsx")
