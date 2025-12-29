import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 修正版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：代入 JapicID 至網址並搜尋英文字串 ---
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
        
        # 提取 8 位數的 japic_code
        japic_codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
        
        if japic_codes:
            japic_code = japic_codes[0]
            res["target_id"] = japic_code
            
            # 2. 核心要求：代入 japic_code 到指定網址
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding # 確保日文編碼正確
            
            soup = BeautifulSoup(resp_med.text, 'html.parser')
            
            # --- 策略 A：使用「2. 禁忌」物理位置切分提取英文字串 ---
            temp_soup = BeautifulSoup(resp_med.text, 'html.parser')
            for script in temp_soup(["script", "style"]):
                script.decompose()
            full_text = temp_soup.get_text(separator="\n")
            
            if "2. 禁忌" in full_text:
                pre_contra_text = full_text.split("2. 禁忌")[0]
                # 尋找連續英文單字 (包含空格與連字號)
                found_names = re.findall(r'\b[A-Z][a-zA-Z\s\-]{3,}\b', pre_contra_text)
                
                clean_names = []
                for n in found_names:
                    n = n.strip()
                    if n.upper() not in ["JAPIC", "KEGG", "MEDICUS", "PDF"] and len(n) > 2:
                        if n not in clean_names:
                            clean_names.append(n)
                
                # 規則：1.成分名 2.商品名
                if len(clean_names) >= 1: res["ing_en"] = clean_names[0]
                if len(clean_names) >= 2: res["trade_en"] = clean_names[1]
            
            # --- 策略 B：若物理切分失敗，精確搜尋表格中的歐文字串 (<th>標籤定位) ---
            if res["trade_en"] == "[查無結果]" or res["ing_en"] == "[查無結果]":
                # 找尋「欧文商標名」
                th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
                if th_trade and th_trade.find_next_sibling('td'):
                    res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)
                
                # 找尋「欧文一般名」
                th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
                if th_ing and th_ing.find_next_sibling('td'):
                    res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[錯誤: {str(e)}]"
    
    return res

# --- UI 與 檔案解析 (維持您的 21:00 邏輯) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i]])
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
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
        t_f = str(row.iloc[cols['Trade']]).strip()
        i_f = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no, "商品名(日)": t_f, "關鍵字": get_katakana_prefix(t_f), "成分名(日)": i_f
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (JapicID 網址代入搜尋版)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 檔案辨識成功")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始代入 JapicID 網址並解析"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"正在分析 No.{r['No.']} (關鍵字: {r['關鍵字']})")
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
                time.sleep(1.2) # 延遲確保請求成功
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載翻譯結果", output.getvalue(), "PMDA_KEGG_Result.xlsx")
