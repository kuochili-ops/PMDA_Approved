import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 17:15

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心檢索邏輯：增加自動跳轉與容錯 ---
def get_kegg_perfect_info(kw_trade, kw_ing):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]"}

    try:
        # --- A. 處理成分名 (搜尋後直接在結果頁找括號英文) ---
        search_ing_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_ing)}"
        resp_ing = session.get(search_ing_url, headers=headers, timeout=10)
        
        # 1. 檢查是否直接跳轉到了詳情頁 (URL 包含 japic_code)
        if "japic_code=" in resp_ing.url:
            soup_med = BeautifulSoup(resp_ing.text, 'html.parser')
            th_ing = soup_med.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)
        else:
            # 2. 如果在列表頁，找包含片假名的欄位
            soup_list = BeautifulSoup(resp_ing.text, 'html.parser')
            for td in soup_list.find_all('td'):
                txt = td.get_text()
                if kw_ing in txt:
                    match = re.search(r'\(([^)]+)\)', txt)
                    if match:
                        res["ing_en"] = match.group(1).strip()
                        break

        # --- B. 處理商品名 (必須進入詳情頁抓取 欧文商標名) ---
        search_trade_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_trade = session.get(search_trade_url, headers=headers, timeout=10)
        
        # 判斷是否直接跳轉，或需要從列表點擊
        med_html = ""
        if "japic_code=" in resp_trade.url:
            med_html = resp_trade.text
        else:
            japic_match = re.search(r'japic_code=(\d+)', resp_trade.text)
            if japic_match:
                japic_code = japic_match.group(1)
                time.sleep(0.3)
                med_html = session.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}", headers=headers).text
        
        if med_html:
            soup_med = BeautifulSoup(med_html, 'html.parser')
            # 尋找「欧文商標名」
            th_trade = soup_med.find('th', string=re.compile(r'欧文商標名'))
            if th_trade and th_trade.find_next_sibling('td'):
                res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- 清理與 UI 部分 ---
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

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (路徑自適應版：2025-12-29 17:15)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 辨識成功！")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始翻譯"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"正在分析 No.{r['No.']}...")
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
            st.download_button("📥 下載結果", output.getvalue(), "PMDA_EN.xlsx")
