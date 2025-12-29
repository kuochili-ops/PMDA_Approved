import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 23:00

# --- 核心邏輯：使用 BeautifulSoup 標籤定位 ---
def fetch_by_html_tags(japic_code):
    if not japic_code or str(japic_code) in ["None", "nan"]: 
        return {"trade_en": "[無ID]", "ing_en": "[無ID]"}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}

    try:
        # 格式化 ID (確保為 8 位數)
        clean_code = str(japic_code).strip().zfill(8)
        url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 1. 抓取成分名 (欧文一般名)
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing:
            td_ing = th_ing.find_next_sibling('td')
            if td_ing:
                # 取得文字並清理換行與多餘空格
                res["ing_en"] = td_ing.get_text(strip=True)

        # 2. 抓取商品名 (欧文商標名)
        th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
        if th_trade:
            td_trade = th_trade.find_next_sibling('td')
            if td_trade:
                res["trade_en"] = td_trade.get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"Error: {str(e)}"
        
    return res

# --- 介面與檔案處理 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 標籤精確解析器 (23:00 版)")

st.markdown("""
### 修正說明
* **精確匹配**：直接定位網頁中的 `<th>` 標籤（歐文一般名/歐文商標名）。
* **排除干擾**：不再受「2. 禁忌」位置或英文排序影響，直接抓取表格欄位。
""")

f = st.file_uploader("上傳含有 JapicID 的 Excel/CSV", type=['xlsx', 'csv'])

if f:
    df_raw = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
    st.write("檔案預覽：")
    st.dataframe(df_raw.head(3))
    
    # 選取 ID 欄位
    cols = df_raw.columns.tolist()
    id_col = st.selectbox("請選擇包含 JapicID 的欄位", cols, index=len(cols)-1)

    if st.button("🚀 開始精確抓取"):
        results = []
        bar = st.progress(0)
        status_text = st.empty()
        
        for i, row in df_raw.iterrows():
            code = str(row[id_col]).strip()
            status_text.text(f"正在處理第 {i+1}/{len(df_raw)} 筆 (ID: {code})")
            
            info = fetch_by_html_tags(code)
            
            results.append({
                "No.": row.get("No.", i+1),
                "JapicID": code,
                "商品名(日)": row.get("商品名(日)", ""),
                "Trade Name (EN)": info["trade_en"],
                "成分名(日)": row.get("成分名(日)", ""),
                "Ingredient (EN)": info["ing_en"]
            })
            bar.progress((i + 1) / len(df_raw))
            time.sleep(1.0) # 保持連線穩定
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 抓取結果")
        st.dataframe(res_df, use_container_width=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Final_Success.xlsx")
