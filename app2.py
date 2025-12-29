import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 23:45 完整修正版

# --- 1. 核心抓取邏輯：定位 HTML 標籤 ---
def fetch_by_html_tags(japic_code):
    if not japic_code or str(japic_code).lower() in ["none", "nan", ""]: 
        return {"trade_en": "[無ID]", "ing_en": "[無ID]"}
    
    clean_code = str(japic_code).strip().zfill(8)
    url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 抓取成分名 (欧文一般名)
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing and th_ing.find_next_sibling('td'):
            res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

        # 抓取商品名 (欧文商標名)
        th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
        if th_trade and th_trade.find_next_sibling('td'):
            res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

# --- 2. Excel 欄位自動辨識邏輯 ---
def clean_and_extract_df(df):
    header_idx = None
    for i in range(min(15, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i]])
        if '商品' in row_str or '販' in row_str:
            header_idx = i
            break
    
    if header_idx is not None:
        df.columns = df.iloc[header_idx]
        df = df.iloc[header_idx+1:].reset_index(drop=True)
    
    # 清理並確保 JapicID 欄位存在
    cols = df.columns.astype(str).tolist()
    target_id_col = next((c for c in cols if 'ID' in c.upper() or 'JAPIC' in c.upper()), None)
    trade_col = next((c for c in cols if '商品' in c or '販' in c), None)
    ing_col = next((c for c in cols if '成分' in c or '成' in c), None)
    
    return df, target_id_col, trade_col, ing_col

# --- 3. Streamlit UI ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (Excel 解析 + 標籤精確版)")

f = st.file_uploader("請上傳您的 Excel 檔案", type=['xlsx', 'csv'])

if f:
    raw_df = pd.read_excel(f, header=None) if f.name.endswith('.xlsx') else pd.read_csv(f, header=None)
    df, id_col, trade_col, ing_col = clean_and_extract_df(raw_df)
    
    if id_col:
        st.success(f"✅ 辨識成功！使用欄位: [ID: {id_col}] [商品: {trade_col}] [成分: {ing_col}]")
        st.dataframe(df.head(10))
        
        if st.button("🚀 開始翻譯這 10 筆資料"):
            results = []
            bar = st.progress(0)
            
            # 僅處理前 10 筆或有效 JapicID 的資料
            process_df = df.head(15) 
            for i, row in process_df.iterrows():
                code = str(row[id_col]).strip().replace('.0','')
                if not code or code == 'nan': continue
                
                info = fetch_by_html_tags(code)
                results.append({
                    "JapicID": code,
                    "商品名(日)": row[trade_col],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": row[ing_col],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((len(results)) / 10 if len(results)<=10 else 1.0)
                time.sleep(1.2)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 翻譯結果")
            st.dataframe(res_df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載翻譯後的 Excel", output.getvalue(), "PMDA_10_Result.xlsx")
    else:
        st.error("❌ 找不到 JapicID 欄位，請確認 Excel 內容。")
