import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 搜索強化版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯強化 ---
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
            
            # 取得純文字內容供物理定位使用
            clean_soup = BeautifulSoup(resp_med.text, 'html.parser')
            for s in clean_soup(["script", "style"]): s.decompose()
            full_text = clean_soup.get_text(separator=" ")

            # --- 策略 1：針對「成分名 (Ingredient)」的標籤定位 ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)
            
            # --- 策略 2：針對「商品名 (Trade Name)」的多重搜索 ---
            # A. 優先嘗試您提到的「商品情報」後方字串邏輯
            if "商品情報" in full_text:
                after_info = full_text.split("商品情報")[1]
                # 尋找前幾個大寫英文單字，並排除常見的劑型干擾
                potential_trade = re.findall(r'\b[A-Z][A-Z0-9\s\-]{3,}\b', after_info)
                if potential_trade:
                    # 過濾掉明顯不是商品名的雜訊 (如 JAPIC, PDF)
                    filtered = [n.strip() for n in potential_trade if n.strip().upper() not in ["JAPIC", "PDF", "KEGG"]]
                    if filtered:
                        # 取得第一個匹配項，並移除尾隨的 tablets/capsules (若有)
                        trade_candidate = filtered[0]
                        trade_candidate = re.sub(r'(?i)\s(tablets?|capsules?|injection|yield).*', '', trade_candidate)
                        res["trade_en"] = trade_candidate

            # B. 備援：若上方沒抓到，嘗試「欧文商標名」標籤
            if res["trade_en"] == "[查無結果]":
                th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
                if th_trade and th_trade.find_next_sibling('td'):
                    res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

            # C. 最後備援：使用您原有的「2. 禁忌」前提取邏輯
            if res["ing_en"] == "[查無結果]" and "2. 禁忌" in full_text:
                pre_text = full_text.split("2. 禁忌")[0]
                found = re.findall(r'\b[A-Z][a-zA-Z\s\-]{3,}\b', pre_text)
                clean = [n.strip() for n in found if n.strip().upper() not in ["JAPIC", "KEGG", "PDF"]]
                if clean: res["ing_en"] = clean[0]

    except Exception as e:
        res["trade_en"] = f"[錯誤: {str(e)}]"
    
    return res

# --- UI 與 檔案解析部分維持原樣 ---
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
st.title("💊 PMDA 翻譯 (搜索能力強化版)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 檔案辨識成功")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始深度解析"):
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
            st.download_button("📥 下載最終結果", output.getvalue(), "PMDA_Enhanced_Result.xlsx")
