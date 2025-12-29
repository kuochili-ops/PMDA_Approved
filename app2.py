import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 16:45

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心檢索邏輯：改用 BeautifulSoup 進行結構化解析，避免 Regex 失效 ---
def get_kegg_perfect_info(kw_trade, kw_ing):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]"}

    try:
        # --- A. 處理成分名 (從搜尋結果頁的一般名欄位抓取) ---
        search_ing_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_ing)}"
        resp_ing = session.get(search_ing_url, headers=headers, timeout=10)
        soup_ing = BeautifulSoup(resp_ing.text, 'html.parser')
        
        # 尋找所有 <td>，如果內容包含片假名成分名且有括號，就提取括號內容
        for td in soup_ing.find_all('td'):
            if kw_ing in td.get_text():
                ing_match = re.search(r'\(([^)]+)\)', td.get_text())
                if ing_match:
                    res["ing_en"] = ing_match.group(1).strip()
                    break

        # --- B. 處理商品名 (進入 JAPIC 頁面抓取 欧文商標名) ---
        search_trade_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_trade = session.get(search_trade_url, headers=headers, timeout=10)
        
        # 提取 JAPIC Code
        japic_code = None
        japic_match = re.search(r'japic_code=(\d+)', resp_trade.text)
        if japic_match:
            japic_code = japic_match.group(1)
        else:
            list_link = BeautifulSoup(resp_trade.text, 'html.parser').find('a', href=re.compile(r'japic_code='))
            if list_link:
                japic_code = re.search(r'japic_code=(\d+)', list_link['href']).group(1)

        if japic_code:
            time.sleep(0.5)
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            resp_med = session.get(med_url, headers=headers, timeout=10)
            soup_med = BeautifulSoup(resp_med.text, 'html.parser')
            
            # 尋找 <th> 內容為「欧文商標名」的標籤，取其下一個 <td>
            th_trade = soup_med.find('th', string=re.compile(r'欧文商標名'))
            if th_trade and th_trade.find_next_sibling('td'):
                res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

    except: pass
    return res

# --- 資料清理邏輯 (保持穩定) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        if '販' in "".join(row) and '成' in "".join(row):
            header_idx = i
            for idx, cell in enumerate(row):
                if 'No' in str(cell): cols['No'] = idx
                if '販' in str(cell): cols['Trade'] = idx
                if '成' in str(cell): cols['Ing'] = idx
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
            "No.": val_no, "商品名(日)": t_full,
            "商品名(關鍵字)": get_katakana_prefix(t_full),
            "成分名(日)": i_full, "成分名(關鍵字)": get_katakana_prefix(i_full)
        })
    return pd.DataFrame(rows)

# --- UI ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (結構解析版：2025-12-29 16:45)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 辨識成功！")
        st.dataframe(df, use_container_width=True)
        
        if st.button("🚀 開始深度翻譯"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"正在搜尋 No.{r['No.']}...")
                info = get_kegg_perfect_info(r['商品名(關鍵字)'], r['成分名(關鍵字)'])
                results.append({
                    "No.": r['No.'], "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載結果", output.getvalue(), "PMDA_EN_Final.xlsx")
