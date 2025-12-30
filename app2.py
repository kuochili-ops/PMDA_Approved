import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 04:00 標籤定位精確版

def fetch_kegg_data_fixed(japic_code):
    """
    直攻 JapicID 網址，並嚴格區分 一般名(成分) 與 規制区分(商品)
    """
    if not japic_code or str(japic_code).lower() in ["nan", "none", "", "0"]:
        return None
    
    clean_code = str(japic_code).split('.')[0].strip().zfill(8)
    target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "url": target_url}

    try:
        resp = requests.get(target_url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # --- 1. 抓取 成分名 (英) ---
        # 標籤定位：<th>欧文一般名</th>
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing:
            td_ing = th_ing.find_next_sibling('td')
            if td_ing:
                res["ing_en"] = td_ing.get_text(strip=True)

        # --- 2. 抓取 商品名 (英) ---
        # 標籤定位：<th>規制区分</th>
        # 邏輯：在該 td 中，英文字串通常出現在日文商品名之後
        th_reg = soup.find('th', string=re.compile(r'規制区分'))
        if th_reg:
            td_reg = th_reg.find_next_sibling('td')
            if td_reg:
                text_content = td_reg.get_text(separator=" ", strip=True)
                # 正則表達式：尋找最後一段連續的英文（包含空格與劑型，如 SCEMBLIX tablets）
                # 排除掉前面可能連在一起的日文字
                en_matches = re.findall(r'\b[A-Z][A-Z0-9\s\-\.]{3,}\b', text_content)
                if en_matches:
                    # 根據 KEGG 結構，最後一個大寫英文字串通常是歐文商標名
                    res["trade_en"] = en_matches[-1].strip()

    except:
        pass
    return res

# --- UI 介面 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (成分/商品精確分離版)")

f = st.file_uploader("上傳含有 JapicID 的 Excel", type=['xlsx'])

if f:
    df_raw = pd.read_excel(f)
    cols = df_raw.columns.tolist()
    
    st.write("### 1. 欄位設定")
    c1, c2, c3 = st.columns(3)
    with c1: id_col = st.selectbox("JapicID 欄位", cols)
    with c2: trade_jp_col = st.selectbox("商品名(日) 欄位", cols)
    with c3: ing_jp_col = st.selectbox("成分名(日) 欄位", cols)

    if st.button("🚀 開始解析 (代入網址)") :
        df_valid = df_raw[df_raw[id_col].notna()].copy()
        results = []
        bar = st.progress(0)
        status_log = st.empty()
        
        for i, (idx, row) in enumerate(df_valid.iterrows()):
            code = str(row[id_col]).strip()
            status_log.text(f"⏳ 處理中 ({i+1}/{len(df_valid)}): {code}")
            
            info = fetch_kegg_data_fixed(code)
            
            results.append({
                "JapicID": code,
                "商品名(日)": row[trade_jp_col],
                "Trade Name (EN)": info["trade_en"],
                "成分名(日)": row[ing_jp_col],
                "Ingredient (EN)": info["ing_en"]
            })
            bar.progress((i + 1) / len(df_valid))
            time.sleep(1.0)
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 解析結果")
        st.dataframe(res_df, use_container_width=True)
        
        # 導出
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載修正後的結果", output.getvalue(), "PMDA_Fixed_Final.xlsx")
