import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 01:00 

def fetch_kegg_data(japic_code):
    # 物理邏輯：檢查 ID 是否為有效 8 位數字
    if not japic_code or str(japic_code).lower() in ["nan", "none", ""]:
        return None
    
    clean_code = str(japic_code).split('.')[0].strip().zfill(8)
    url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "url": url}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 定位：<th>欧文一般名</th> 旁的 <td>
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing:
            res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

        # 定位：<th>欧文商標名</th> 旁的 <td>
        th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
        if th_trade:
            res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (精確十筆專用版)")

f = st.file_uploader("上傳您的 Excel", type=['xlsx'])

if f:
    # 讀取 Excel 並自動尋找含有 'JapicID' 或 '商品名' 的那一列作為標頭
    df_all = pd.read_excel(f, header=None)
    
    # 尋找標頭行
    header_idx = 0
    for i in range(len(df_all)):
        row_str = "".join(df_all.iloc[i].astype(str))
        if 'ID' in row_str.upper() or '商品' in row_str:
            header_idx = i
            break
    
    df = df_all.iloc[header_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # 找出 JapicID 欄位並移除空白行
    id_col = next((c for c in df.columns.astype(str) if 'ID' in c.upper() or 'JAPIC' in c.upper()), None)
    
    if id_col:
        # 重要：只留下真正有 JapicID 的行，避免跑出 1389 筆
        df_valid = df[df[id_col].astype(str).str.contains(r'\d', na=False)].copy()
        
        st.success(f"✅ 偵測到 {len(df_valid)} 筆有效藥品資料")
        st.dataframe(df_valid.head(len(df_valid)))
        
        if st.button("🚀 開始翻譯"):
            results = []
            bar = st.progress(0)
            status = st.empty()
            
            for i, (idx, row) in enumerate(df_valid.iterrows()):
                code = str(row[id_col]).strip()
                status.text(f"⏳ 正在處理：{i+1} / {len(df_valid)} (ID: {code})")
                
                info = fetch_kegg_data(code)
                
                results.append({
                    "No.": i+1,
                    "JapicID": code,
                    "商品名(日)": row.get("商品名(日)", ""),
                    "Trade Name (EN)": info["trade_en"] if info else "[跳過]",
                    "成分名(日)": row.get("成分名(日)", ""),
                    "Ingredient (EN)": info["ing_en"] if info else "[跳過]"
                })
                bar.progress((i + 1) / len(df_valid))
                time.sleep(1.2)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 翻譯結果")
            st.dataframe(res_df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Final_Success.xlsx")
    else:
        st.error("❌ 無法在 Excel 中找到 JapicID 欄位。")
