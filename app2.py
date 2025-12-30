import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

st.set_page_config(layout="wide", page_title="PMDA Tool Final Precision")

st.title("💊 PMDA 雙英文字串精確提取器")
st.markdown("> **2025-12-30 最終修正**：解決 `SCEMBLIX` 等商品名因換行導致抓取失敗或抓到日文的問題。")

def fetch_precise_data(japic_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    
    try:
        # 強制格式化 JapicID 為 8 位數字
        clean_id = re.sub(r'[^0-9]', '', str(japic_id).split('.')[0]).zfill(8)
        
        # --- 1. 抓商品名 (Trade Name) ---
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={clean_id}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        soup_t = BeautifulSoup(rt.text, 'html.parser')
        
        # 尋找含有「欧文商標名」的標籤
        anchor = soup_t.find(string=re.compile(r'欧文商標名'))
        if anchor:
            # 獲取該標籤所在 P 標籤的所有文字，並用空格取代換行符
            # 這是解決 SCEMBLIX tablets (Novartis) 被換行切斷的關鍵
            p_tag = anchor.find_parent('p')
            if p_tag:
                full_text = p_tag.get_text(separator=" ", strip=True)
                
                # 核心邏輯：從「欧文商標名」之後開始切分
                parts = full_text.split("欧文商標名")
                if len(parts) > 1:
                    after_anchor = parts[1].strip()
                    
                    # 使用雷達正則：只抓取首個大寫字母開始的英文字串，遇到日文即停
                    # \b[A-Z] 確保是大寫開頭
                    match = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after_anchor)
                    if match:
                        candidate = match.group(1).strip()
                        # 二次過濾：移除可能被包含進來的日文字 (截斷至第一個非 ASCII 字符)
                        res["trade_en"] = re.split(r'[^\x00-\x7F]+', candidate)[0].strip()

        # --- 2. 抓成分名 (Ingredient) ---
        i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_id}"
        ri = requests.get(i_url, headers=headers, timeout=10)
        ri.encoding = ri.apparent_encoding
        soup_i = BeautifulSoup(ri.text, 'html.parser')
        th = soup_i.find('th', string=re.compile(r'欧文一般名'))
        if th and th.find_next_sibling('td'):
            res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- Streamlit 介面 ---
f = st.file_uploader("1. 上傳包含 JapicID 的 Excel", type=['xlsx'])
if f:
    df_raw = pd.read_excel(f)
    # 自動尋找 JapicID 欄位
    id_col = next((c for c in df_raw.columns if 'ID' in str(c).upper() or 'JAPIC' in str(c).upper()), None)
    
    if id_col:
        st.success(f"已識別 JapicID 欄位：{id_col}")
        if st.button("🚀 執行深度對位分析"):
            results = []
            bar = st.progress(0)
            rows = df_raw.to_dict('records')
            
            for i, row in enumerate(rows):
                val = row.get(id_col)
                if pd.isna(val): continue
                
                info = fetch_precise_data(val)
                results.append({
                    "JapicID": val,
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "Check_URL": f"https://www.kegg.jp/medicus-bin/japic_med_product?id={str(val).split('.')[0].zfill(8)}"
                })
                bar.progress((i + 1) / len(rows))
                time.sleep(0.5) # 避開伺服器封鎖
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 解析結果預覽")
            st.dataframe(res_df, use_container_width=True)
            
            # 下載 Excel
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載修正成果 Excel", out.getvalue(), "PMDA_Final_Precision_Report.xlsx")
    else:
        st.error("❌ 找不到 JapicID 欄位，請檢查 Excel 表頭。")
