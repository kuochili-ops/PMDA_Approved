import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup
from urllib.parse import quote

# 版本標記：2025-12-30 02:30

def fetch_by_japic_url_v2(japic_code):
    if not japic_code or str(japic_code).lower() in ["nan", "none", "", "0"]:
        return None
    
    # 格式化 JapicID 為 8 位數
    clean_code = str(japic_code).split('.')[0].strip().zfill(8)
    target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "url": target_url}

    try:
        resp = requests.get(target_url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        html_content = resp.text
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- 1. 搜尋成分名 (欧文一般名標籤法) ---
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing and th_ing.find_next_sibling('td'):
            res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

        # --- 2. 搜尋商品名 (根據您的需求：商品情報後的英文字串) ---
        # 先將 HTML 轉為純文字以方便定位
        for s in soup(["script", "style"]):
            s.decompose()
        full_text = soup.get_text(separator="\n")
        
        if "商品情報" in full_text:
            # 截取「商品情報」之後的文字
            after_product_info = full_text.split("商品情報")[1]
            # 搜尋該段落中第一個出現的英文字串 (包含空格、數字與 tablets/capsules 等)
            # 排除掉只有 1-2 個字母的雜訊
            match_trade = re.search(r'\b[A-Z][A-Z0-9\s\-]{3,}\b', after_product_info)
            if match_trade:
                res["trade_en"] = match_trade.group(0).strip()
        
        # 備援：如果上方沒抓到，改用歐文商標名標籤
        if res["trade_en"] == "[未檢出]":
            th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
            if th_trade and th_trade.find_next_sibling('td'):
                res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- UI 介面維持 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (JapicID 網址代入 + 特定搜尋版)")

st.info(f"搜尋規則：\n1. 成分名：取自『欧文一般名』標籤。\n2. 商品名：取自『商品情報』後第一個英文字串。")

f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    df_raw = pd.read_excel(f)
    cols = df_raw.columns.tolist()
    
    st.write("### 欄位指定")
    c1, c2, c3 = st.columns(3)
    with c1: id_col = st.selectbox("JapicID 欄位", cols)
    with c2: trade_jp_col = st.selectbox("商品名(日) 欄位", cols)
    with c3: ing_jp_col = st.selectbox("成分名(日) 欄位", cols)

    if st.button("🚀 開始執行解析"):
        df_valid = df_raw[df_raw[id_col].notna()].copy()
        results = []
        bar = st.progress(0)
        
        for i, (idx, row) in enumerate(df_valid.iterrows()):
            code = str(row[id_col]).strip()
            info = fetch_by_japic_url_v2(code)
            
            results.append({
                "JapicID": code,
                "商品名(日)": row[trade_jp_col],
                "Trade Name (EN)": info["trade_en"] if info else "[跳過]",
                "成分名(日)": row[ing_jp_col],
                "Ingredient (EN)": info["ing_en"] if info else "[跳過]",
                "網址": info["url"] if info else ""
            })
            bar.progress((i + 1) / len(df_valid))
            time.sleep(1.0)
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 解析結果")
        st.dataframe(res_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Scemblix_Fixed.xlsx")
