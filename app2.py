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
VERSION_TIME = "23:55" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：解決 ID 漂移 (00000001)、嚴格鎖定「欧文商標名」後方首組英文。
""")
st.divider()

def clean_japic_id(val):
    """強效 ID 清洗器"""
    s = str(val).split('.')[0].strip()
    digits = re.sub(r'[^0-9]', '', s)
    if len(digits) >= 5 and len(digits) <= 10:
        return digits.zfill(8)
    return None

def fetch_dual_strings(japic_id_input, trade_jp):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. 決定 JapicID
        final_id = clean_japic_id(japic_id_input)
        if not final_id:
            # 備援：搜尋模式
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(trade_jp[:8])}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            res["target_id"] = final_id
            # --- [位置 A] 抓 Trade Name (產品情報頁) ---
            prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            res["url"] = prod_url
            r_p = requests.get(prod_url, headers=headers, timeout=10)
            r_p.encoding = r_p.apparent_encoding
            s_p = BeautifulSoup(r_p.text, 'html.parser')
            
            # 關鍵錨點：搜尋含有「欧文商標名」的元素
            anchor = s_p.find(string=re.compile(r'欧文商標名'))
            if anchor:
                context = anchor.find_parent().get_text(strip=True)
                # 只取「欧文商標名」後面的英文部分，直到遇到下一個日文字或結尾
                match = re.search(r'欧文商標名\s*([A-Z0-9][A-Za-z0-9\s\-\.]{3,})', context)
                if match:
                    res["trade_en"] = match.group(1).strip()
            
            # --- [位置 B] 抓 Ingredient (醫療主頁) ---
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            r_m = requests.get(med_url, headers=headers, timeout=10)
            r_m.encoding = r_m.apparent_encoding
            s_m = BeautifulSoup(r_m.text, 'html.parser')
            th = s_m.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[異常: {str(e)[:10]}]"
        
    return res

# --- 介面實作 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        # 掃描表頭
        header_row, cols = 0, {'No': 0, 'Trade': 1, 'ID': 2}
        for i in range(min(20, len(raw_df))):
            row_str = "".join([str(x) for x in raw_df.iloc[i]])
            if any(k in row_str for k in ['商', '販', 'ID']):
                header_row = i
                for idx, val in enumerate(raw_df.iloc[i]):
                    v = str(val)
                    if 'No' in v: cols['No'] = idx
                    if any(k in v for k in ['商', '販']): cols['Trade'] = idx
                    if ('ID' in v or 'Japic' in v) and '適應' not in v: cols['ID'] = idx
                break

        data_rows = []
        for _, row in raw_df.iloc[header_row + 1:].iterrows():
            no = str(row.iloc[cols['No']]).strip().split('.')[0]
            if not no.isdigit() and len(data_rows) > 0: break
            data_rows.append({
                "No.": no,
                "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
                "JapicID": str(row.iloc[cols['ID']]).strip()
            })

        st.subheader("📋 1. 預覽清單")
        st.dataframe(pd.DataFrame(data_rows), use_container_width=True)

        if st.button("🚀 開始精確抓取"):
            results = []
            bar = st.progress(0)
            for i, r in enumerate(data_rows):
                info = fetch_dual_strings(r['JapicID'], r['商品名(日)'])
                results.append({
                    "No.": r['No.'],
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "來源網址": info["url"]
                })
                bar.progress((i + 1) / len(data_rows))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 2. 結果清單")
            st.dataframe(res_df, use_container_width=True)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel", out.getvalue(), "PMDA_Final_Report.xlsx")

    except Exception as e:
        st.error(f"錯誤: {e}")
