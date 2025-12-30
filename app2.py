import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 網址註記強化版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：直攻 JapicID 網址並記錄來源 ---
def fetch_by_japic_logic(japic_id, kw_trade):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    session = requests.Session()
    # 初始化結果，新增 source_url 欄位
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]", "target_id": "None", "source_url": ""}

    try:
        # 1. 取得 JapicID 
        final_id = str(japic_id).strip().zfill(8) if japic_id and str(japic_id).lower() != 'none' else None
        
        # 若 Excel 無 ID 則嘗試搜尋
        if not final_id:
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            resp_search = session.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
            if codes: final_id = codes[0]

        if final_id:
            res["target_id"] = final_id
            # 2. 定義目標網址並存入結果
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["source_url"] = target_url
            
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding
            soup = BeautifulSoup(resp_med.text, 'html.parser')

            # --- 抓取位置 A：成分名 (來自「欧文一般名」) ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- 抓取位置 B：商品名 (來自「規制区分」旁的 td) ---
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    # 邏輯：抓取最後一段英文字串 (如 SCEMBLIX tablets)
                    en_matches = re.findall(r'\b[A-Z][A-Z0-9\s\-\.]{3,}\b', raw_text)
                    if en_matches:
                        res["trade_en"] = en_matches[-1].strip()

    except Exception as e:
        res["trade_en"] = f"[解析錯誤]"
    
    return res

# --- UI 與 檔案解析 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (自動網址註記版)")

# 在畫面上清楚標註抓取規則
st.markdown("""
### 🔍 抓取規則說明
* **網頁網址**：`https://www.kegg.jp/medicus-bin/japic_med?japic_code=` + `JapicID`
* **成分名 (Ingredient)**：抓取該網頁中 `<th>欧文一般名</th>` 標籤旁的內容。
* **商品名 (Trade Name)**：抓取該網頁中 `<th>規制区分</th>` 標籤旁內容的**最後一段英文字串**。
---
""")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    # (此處省略部分 clean_dataframe 代碼，與先前邏輯一致)
    # ... 為了簡潔直接進入執行部分 ...
    raw_df = pd.read_excel(f, header=None)
    # 假設使用先前的辨識邏輯處理後的 df 為 df_processed
    
    # 模擬簡化版欄位處理
    st.info("正在準備解析資料...")
    # (此處僅為結構示意的核心按鈕邏輯)
    if st.button("🚀 開始精確解析"):
        # ... 迴圈呼叫 fetch_by_japic_logic ...
        # 在結果的字典中加入:
        # "資料來源網址": info["source_url"]
        pass
