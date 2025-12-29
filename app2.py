import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io

# 版本標記：2025-12-29 15:30

# --- 1. 片假名提取 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 2. 核心檢索邏輯 (根據您提供的網頁路徑優化) ---
def get_kegg_perfect_info(kw_trade, kw_ing):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]"}

    try:
        # --- A. 處理成分名 (直接從搜尋結果頁的「一般名」欄位抓取) ---
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_ing)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        # 尋找「一般名」欄位後的英文 (例如: ドロスピレノン (Drospirenone))
        ing_match = re.search(rf'{kw_ing}\s*\(([^)]+)\)', resp.text)
        if ing_match:
            res["ing_en"] = ing_match.group(1).strip()

        # --- B. 處理商品名 (點擊進入 JAPIC 頁面抓取 欧文商標名) ---
        # 使用商品名的片假名搜尋
        t_search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        t_resp = session.get(t_search_url, headers=headers, timeout=10)
        
        # 找到進入 JAPIC 頁面的 code
        japic_match = re.search(r'japic_code=(\d+)', t_resp.text)
        if not japic_match:
            # 備援：列表頁連結
            list_match = re.search(r'href="/medicus-bin/japic_med\?japic_code=(\d+)"', t_resp.text)
            japic_code = list_match.group(1) if list_match else None
        else:
            japic_code = japic_match.group(1)

        if japic_code:
            time.sleep(0.3)
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            med_html = session.get(med_url, headers=headers).text
            # 鎖定「欧文商標名」下方的內容
            trade_match = re.search(r'<th>欧文商標名</th>\s*<td>(.*?)</td>', med_html, re.S)
            if trade_match:
                res["trade_en"] = re.sub(r'<.*?>', '', trade_match.group(1)).strip()

    except Exception as e:
        pass
    return res

# --- 3. 資料清理與 UI ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        if '販' in "".join(row) and '成' in "".join(row):
            header_idx = i
            for idx, cell in enumerate(row):
                if 'No' in cell: cols['No'] = idx
                if '販' in cell: cols['Trade'] = idx
                if '成' in cell: cols['Ing'] = idx
            break
            
    if header_idx is None: return None
    
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
        
        t_full = str(row.iloc[cols['Trade']]).strip()
        i_full = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no,
            "商品名(日)": t_full,
            "商品名(關鍵字)": get_katakana_prefix(t_full),
            "成分名(日)": i_full,
            "成分名(關鍵字)": get_katakana_prefix(i_full)
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (網頁路徑優化版：2025-12-29 15:30)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 辨識成功！")
        st.dataframe(df, use_container_width=True)
        
        if st.button("🚀 執行深度檢索"):
            results = []
            bar = st.progress(0)
            for i, r in df.iterrows():
                # 執行您指定的路徑
                info = get_kegg_perfect_info(r['商品名(關鍵字)'], r['成分名(關鍵字)'])
                results.append({
                    "No.": r['No.'],
                    "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 翻譯結果")
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel", output.getvalue(), "PMDA_EN.xlsx")
