import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 03:00 直攻網址版

def fetch_data_from_direct_url(japic_code):
    """
    這裏是核心修正：直接代入 JapicID 構造網址，不經過搜尋引擎。
    """
    if not japic_code or str(japic_code).lower() in ["nan", "none", "", "0"]:
        return None
    
    # 確保 ID 為 8 位數格式
    clean_code = str(japic_code).split('.')[0].strip().zfill(8)
    target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={clean_code}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "url": target_url}

    try:
        # 直接請求目標網頁
        resp = requests.get(target_url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')

        # --- 1. 定位成分名 (欧文一般名) ---
        th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
        if th_ing and th_ing.find_next_sibling('td'):
            res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

        # --- 2. 定位商品名 (根據您的指定：規制区分 旁的 td) ---
        # 物理位置：<th>規制区分</th> 之後的 <td>
        th_reg = soup.find('th', string=re.compile(r'規制区分'))
        if th_reg:
            td_reg = th_reg.find_next_sibling('td')
            if td_reg:
                # 取得 td 內的完整文字
                full_td_text = td_reg.get_text(separator=" ", strip=True)
                # 搜尋英文字串 (例如 SCEMBLIX tablets)
                # 邏輯：找尋連續的大寫英文字母開頭的字串
                en_match = re.search(r'\b[A-Z][A-Z0-9\s\-]{3,}\b', full_td_text)
                if en_match:
                    res["trade_en"] = en_match.group(0).strip()
                else:
                    res["trade_en"] = full_td_text # 若無正則匹配則取全文

    except Exception as e:
        pass
    return res

# --- UI 介面 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (JapicID 網址直攻版)")

f = st.file_uploader("上傳含有 JapicID 的 Excel", type=['xlsx'])

if f:
    df_raw = pd.read_excel(f)
    cols = df_raw.columns.tolist()
    
    st.write("### 欄位指定")
    c1, c2, c3 = st.columns(3)
    with c1: id_col = st.selectbox("JapicID 欄位", cols)
    with c2: trade_jp_col = st.selectbox("商品名(日) 欄位", cols)
    with c3: ing_jp_col = st.selectbox("成分名(日) 欄位", cols)

    if st.button("🚀 執行網址代入解析"):
        # 只處理有 ID 的行
        df_valid = df_raw[df_raw[id_col].notna()].copy()
        
        results = []
        bar = st.progress(0)
        status_text = st.empty()
        
        for i, (idx, row) in enumerate(df_valid.iterrows()):
            code = str(row[id_col]).strip()
            status_text.text(f"⏳ 正在存取網址：...japic_code={code}")
            
            info = fetch_data_from_direct_url(code)
            
            results.append({
                "JapicID": code,
                "商品名(日)": row[trade_jp_col],
                "Trade Name (EN)": info["trade_en"] if info else "[錯誤]",
                "成分名(日)": row[ing_jp_col],
                "Ingredient (EN)": info["ing_en"] if info else "[錯誤]",
                "存取網址": info["url"] if info else ""
            })
            bar.progress((i + 1) / len(df_valid))
            time.sleep(1.0) 
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 解析結果")
        st.dataframe(res_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Direct_URL_Result.xlsx")
