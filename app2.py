import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 07:30 標籤對位強化版

st.set_page_config(layout="wide", page_title="PMDA 解析工具")

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_reg_text": ""}
    
    try:
        # --- 1. 嚴謹的 ID 處理邏輯 ---
        final_id = None
        # 清除掉所有非數字的提示字眼
        clean_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        
        if clean_id and len(clean_id) >= 5:
            final_id = clean_id.zfill(8)
        else:
            # 如果沒有有效 ID，則使用片假名搜尋
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [位置 1] 成分名：定位「欧文一般名」 ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing:
                td_ing = th_ing.find_next_sibling('td')
                if td_ing:
                    res["ing_en"] = td_ing.get_text(strip=True)

            # --- [位置 2] 商品名：定位「規制区分」 ---
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    # 取得原始文字：例如 "セムブリックス錠20mg SCEMBLIX tablets"
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    res["raw_reg_text"] = raw_text
                    
                    # 抓取邏輯：抓取日文字元之後的所有英文部分
                    # 我們找尋包含大寫字母開頭且長度足夠的英文組合
                    en_pattern = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', raw_text)
                    if en_pattern:
                        # 根據您的觀察，正確的 Trade Name 通常在該單元格的最末端
                        res["trade_en"] = en_pattern[-1].strip()
                        
    except Exception as e:
        res["trade_en"] = f"[解析異常]"
        
    return res

# --- UI 介面維持穩定 ---
st.title("💊 PMDA 雙英文字串精確對位版")

f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    raw_df = pd.read_excel(f, header=None)
    # ... (省略表頭辨識邏輯，與前版本一致) ...
    # 這裡確保 data_rows 建立時 JapicID 只存數字或空字串
    
    # [假設表頭已辨識成功]
    # (此處為執行按鈕後的重點邏輯修正)
    if st.button("🚀 開始解析"):
        results = []
        # ... (進度條) ...
        for i, r in df.iterrows():
            # 傳入 ID 前先做一次清理，避免 "[待搜尋]" 被傳進去
            current_id = r['JapicID'] if r['JapicID'] != "[待搜尋]" else ""
            info = fetch_dual_strings(current_id, r['關鍵字(片假名)'])
            
            results.append({
                "No.": r['No.'],
                "JapicID": info["target_id"],
                "商品名(日)": r['商品名(日)'],
                "Trade Name (EN)": info["trade_en"],
                "成分名(日)": r['成分名(日)'],
                "Ingredient (EN)": info["ing_en"],
                "規制区分原始內容": info["raw_reg_text"],
                "來源網址": info["url"]
            })
        # ... (結果展示與下載) ...
