import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 23:30

def fetch_by_html_tags(japic_code):
    # 確保 JapicID 是 8 位數格式
    if not japic_code or str(japic_code).lower() in ["none", "nan", ""]: 
        return {"trade_en": "[無ID]", "ing_en": "[無ID]"}
    
    clean_code = str(japic_code).strip().zfill(8)
    url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 直接定位標籤
        # 1. 抓取成分名 (欧文一般名)
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing and th_ing.find_next_sibling('td'):
            res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

        # 2. 抓取商品名 (欧文商標名)
        th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
        if th_trade and th_trade.find_next_sibling('td'):
            res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- 介面設計 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 精確翻譯 (十筆資料專用版)")

st.write("這是一個針對小量資料優化的版本，將直接依照 JapicID 抓取標籤內容。")

f = st.file_uploader("上傳含有 JapicID 的 Excel/CSV", type=['xlsx', 'csv'])

if f:
    df_raw = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
    st.write("資料預覽：")
    st.dataframe(df_raw)
    
    # 使用者指定 JapicID 欄位
    id_col = st.selectbox("請選擇 JapicID 所在的欄位", df_raw.columns)

    if st.button("🚀 開始翻譯這十筆資料"):
        results = []
        bar = st.progress(0)
        
        for i, row in df_raw.iterrows():
            code = str(row[id_col]).strip()
            # 呼叫解析邏輯
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
            time.sleep(1.2) # 友善延遲
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 翻譯結果")
        st.dataframe(res_df, use_container_width=True)
        
        # 下載 Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 結果", output.getvalue(), "May_10_Result.xlsx")
