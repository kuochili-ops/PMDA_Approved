import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 商品名精確定位版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：針對「規制区分」定位商品名 ---
def fetch_by_japic_logic(kw_trade, kw_ing):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]", "target_id": "None"}

    try:
        # 1. 搜尋步驟：取得 japic_code
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_search = session.get(search_url, headers=headers, timeout=15)
        japic_codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
        
        if japic_codes:
            japic_code = japic_codes[0]
            res["target_id"] = japic_code
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding
            
            soup = BeautifulSoup(resp_med.text, 'html.parser')

            # --- A. 抓取成分名 (定位：欧文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- B. 抓取商品名 (定位：規制区分 之後的 td) ---
            # 優先使用 HTML Tag 定位 (您提到的 <th>規制区分</th> 之後的 <td>)
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    # 取得內容並清理，只保留英文字串部分 (過濾掉日文劑型干擾)
                    raw_trade = td_reg.get_text(strip=True)
                    # 提取最後一段英文 (通常是 商品名 tablets/capsules)
                    en_match = re.search(r'[A-Z][A-Z0-9\s\-]+(?:tablets|capsules|injection|pills)?', raw_trade, re.IGNORECASE)
                    res["trade_en"] = en_match.group(0).strip() if en_match else raw_trade

            # 備援：如果上方沒抓到，嘗試「欧文商標名」標籤
            if res["trade_en"] == "[查無結果]":
                th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
                if th_trade and th_trade.find_next_sibling('td'):
                    res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[錯誤: {str(e)}]"
    
    return res

# --- UI 與 檔案解析 (維持原樣) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i]])
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
                cell_str = str(cell)
                if 'No' in cell_str: cols['No'] = idx
                if '販' in cell_str: cols['Trade'] = idx
                if '成' in cell_str: cols['Ing'] = idx
            break
    if header_idx is None: return None
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
        t_f = str(row.iloc[cols['Trade']]).strip()
        i_f = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no, "商品名(日)": t_f, "關鍵字": get_katakana_prefix(t_f), "成分名(日)": i_f
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (規制区分精確定位版)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 檔案辨識成功")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始解析"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"正在分析 No.{r['No.']}：{r['商品名(日)']}")
                info = fetch_by_japic_logic(r['關鍵字'], r['成分名(日)'])
                
                results.append({
                    "No.": r['No.'], 
                    "JapicID": info["target_id"],
                    "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(1.2)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載結果", output.getvalue(), "PMDA_Regulatory_Fixed.xlsx")
