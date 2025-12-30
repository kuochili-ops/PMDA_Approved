import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

st.set_page_config(layout="wide", page_title="PMDA Tool Final Fix")

st.title("💊 PMDA 英文字串精確提取器")
st.markdown("> **最後修正重點**：解決抓到整段日文說明的問題。使用「首組大寫英文優先」與「日文自動截斷」技術。")

def fetch_precise_data(japic_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    
    try:
        clean_id = re.sub(r'[^0-9]', '', str(japic_id).split('.')[0]).zfill(8)
        
        # --- 1. 抓商品名 (從 Product 頁面) ---
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={clean_id}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        soup_t = BeautifulSoup(rt.text, 'html.parser')
        
        # 尋找「欧文商標名」
        anchor = soup_t.find(string=re.compile(r'欧文商標名'))
        if anchor:
            # 取得該錨點所在段落的完整文字
            text_block = anchor.find_parent().get_text(separator=" ", strip=True)
            # 核心邏輯：找到「欧文商標名」後方緊接著的英文字
            after_anchor = text_block.split("欧文商標名")[-1].strip()
            
            # 正則表達式：只抓取開頭是大寫英文且包含空格/橫線的字串，遇到日文就停
            # 範例：SCEMBLIX tablets (Novartis) -> 抓 SCEMBLIX tablets
            match = re.search(r'([A-Z][A-Za-z0-9\s\-\.\/]{2,})', after_anchor)
            if match:
                candidate = match.group(1).strip()
                # 再次過濾：如果夾雜日文，則截斷到日文之前
                res["trade_en"] = re.split(r'[^\x00-\x7F]+', candidate)[0].strip()

        # --- 2. 抓成分名 (從 Med 頁面) ---
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

# --- 介面 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df_raw = pd.read_excel(f)
    # 嘗試定位 JapicID 欄位
    id_col = next((c for c in df_raw.columns if 'ID' in str(c).upper() or 'JAPIC' in str(c).upper()), None)
    
    if id_col:
        st.write("✅ 已識別 JapicID 欄位")
        if st.button("🚀 開始執行"):
            results = []
            bar = st.progress(0)
            for i, val in enumerate(df_raw[id_col]):
                if pd.isna(val): continue
                info = fetch_precise_data(val)
                results.append({
                    "JapicID": val,
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df_raw))
                time.sleep(0.4)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載修正後的 Excel", out.getvalue(), "PMDA_Precise_Fix.xlsx")
    else:
        st.error("找不到 JapicID 欄位，請檢查 Excel 表頭。")
