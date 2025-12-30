import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- 版本資訊 ---
VERSION_DATE = "2025-12-30"
VERSION_TIME = "23:58" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：鎖定「欧文商標名」與「欧文一般名」標籤，大幅提升對位精準度。
""")
st.divider()

def fetch_dual_strings(japic_id_input, trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. JapicID 強制清洗
        raw_id = str(japic_id_input).split('.')[0].strip()
        final_id = re.sub(r'[^0-9]', '', raw_id).zfill(8)
        
        if len(final_id) == 8:
            res["target_id"] = final_id
            
            # --- [位置 A] 英文商品名：前往 japic_med_product 頁面 ---
            product_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            res["url"] = product_url
            r_prod = requests.get(product_url, headers=headers, timeout=10)
            r_prod.encoding = r_prod.apparent_encoding
            s_prod = BeautifulSoup(r_prod.text, 'html.parser')
            
            # 尋找包含「欧文商標名」的標籤
            target_span = s_prod.find(string=re.compile(r'欧文商標名'))
            if target_span:
                # 獲取該標籤後方的純文字內容
                parent_p = target_span.find_parent()
                full_txt = parent_p.get_text(strip=True) if parent_p else ""
                # 提取「欧文商標名」之後的英文部分
                en_part = full_txt.replace("欧文商標名", "").strip()
                if en_part:
                    res["trade_en"] = en_part

            # --- [位置 B] 英文成分名：前往 japic_med 頁面 ---
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            r_med = requests.get(med_url, headers=headers, timeout=10)
            r_med.encoding = r_med.apparent_encoding
            s_med = BeautifulSoup(r_med.text, 'html.parser')
            
            # 尋找 <th> 為「欧文一般名」的格子
            th_ing = s_med.find('th', string=re.compile(r'欧文一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[異常: {str(e)[:10]}]"
        
    return res

# --- 主程式介面 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        # 掃描表頭
        header_row, cols = 0, {'No': 0, 'Trade': 1, 'ID': 2}
        for i in range(min(20, len(raw_df))):
            row_str = "".join([str(x) for x in raw_df.iloc[i]])
            if any(k in row_str for k in ['商', '販', 'ID', 'Japic']):
                header_row = i
                for idx, val in enumerate(raw_df.iloc[i]):
                    v = str(val)
                    if 'No' in v: cols['No'] = idx
                    if any(k in v for k in ['商', '販']): cols['Trade'] = idx
                    if ('ID' in v or 'Japic' in v) and '適應' not in v: cols['ID'] = idx
                break

        # 整理清單
        data_list = []
        for _, row in raw_df.iloc[header_row + 1:].iterrows():
            no_val = str(row.iloc[cols['No']]).strip().split('.')[0]
            if not no_val.isdigit() and len(data_list) > 0: break
            
            data_list.append({
                "No.": no_val,
                "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
                "JapicID": str(row.iloc[cols['ID']]).strip()
            })

        st.subheader("📋 待處理清單預覽")
        st.dataframe(pd.DataFrame(data_list))

        if st.button("🚀 開始精確抓取"):
            results = []
            bar = st.progress(0)
            for i, r in enumerate(data_list):
                info = fetch_dual_strings(r['JapicID'], r['商品名(日)'])
                results.append({
                    "No.": r['No.'],
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "來源網址": info["url"]
                })
                bar.progress((i + 1) / len(data_list))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 最終解析結果")
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_
