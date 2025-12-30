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
VERSION_TIME = "23:50" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：強制修正 JapicID 浮點數錯誤 (解決網頁錯誤)、鎖定 `japic_med_product` 頁面物理路徑。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip().split('\n')[0]
    match = re.search(r'([ァ-ヶー・]{2,})', text)
    return match.group(1) if match else text[:5]

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. 精確處理 JapicID (防止出現 71700.0 這種錯誤)
        if pd.isna(japic_id_input) or str(japic_id_input).lower() in ['none', 'nan', '']:
            final_id = ""
        else:
            # 只取數字，並轉為整數再轉字串，確保沒有小數點
            temp_id = re.sub(r'[^0-9]', '', str(japic_id_input).split('.')[0])
            final_id = temp_id.zfill(8) if temp_id else ""

        # 如果 ID 不合法，啟動關鍵字搜尋獲取 ID
        if not (final_id and len(final_id) >= 5):
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            # 優先前往您推薦的產品情報頁 (id=XXXXXXXX)
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [位置 A] Trade Name (物理路徑模式) ---
            # 尋找包含商品名稱的 <p> 標籤
            # 邏輯：在 body 內找第一個包含大寫英文且字數較少的 <p>
            all_ps = soup.find_all('p')
            for p in all_ps:
                p_text = p.get_text(strip=True)
                # 如果包含日文關鍵字，提取其中的大寫英文字
                if kw_trade in p_text:
                    en_matches = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{4,}\b', p_text)
                    if en_matches:
                        res["trade_en"] = en_matches[0].strip()
                        break
            
            # --- [位置 B] 成分名 (去醫療頁面抓比較穩) ---
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            r_med = requests.get(med_url, headers=headers, timeout=10)
            s_med = BeautifulSoup(r_med.text, 'html.parser')
            th_ing = s_med.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[異常: {str(e)[:10]}]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("1. 請上傳包含 JapicID 的 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        # 自動尋找表頭
        header_row, cols = 0, {'No': 0, 'Trade': 1, 'Ing': 2, 'ID': 3}
        for i in range(min(20, len(raw_df))):
            row_str = "".join([str(x) for x in raw_df.iloc[i]])
            if any(k in row_str for k in ['商', '販', '成']):
                header_row = i
                for idx, val in enumerate(raw_df.iloc[i]):
                    v = str(val)
                    if 'No' in v: cols['No'] = idx
                    if any(k in v for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in v: cols['Ing'] = idx
                    if ('ID' in v or 'Japic' in v) and '適應' not in v: cols['ID'] = idx
                break

        data_rows = []
        for _, row in raw_df.iloc[header_row + 1:].iterrows():
            no_val = str(row.iloc[cols['No']]).strip().split('.')[0]
            if not no_val.isdigit() and len(data_rows) > 0: break
            
            trade_jp = str(row.iloc[cols['Trade']]).strip()
            # 強制將 JapicID 轉為純數字字串，避免 .0 錯誤
            raw_id = str(row.iloc[cols['ID']]).strip()
            id_clean = re.sub(r'[^0-9]', '', raw_id.split('.')[0])
            
            data_rows.append({
                "No.": no_val,
                "商品名(日)": trade_jp,
                "關鍵字": get_pure_katakana(trade_jp),
                "JapicID": id_clean if len(id_clean) >= 5 else "[待搜尋]"
            })

        st.subheader("📋 1. 待處理清單 (已修正 ID 格式)")
        st.dataframe(pd.DataFrame(data_rows))

        if st.button("🚀 執行深度對位"):
            results = []
            bar = st.progress(0)
            for i, r in enumerate(data_rows):
                info = fetch_dual_strings(r['JapicID'], r['關鍵字'])
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
            st.subheader("📊 2. 最終解析結果")
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_Refined_Report.xlsx")

    except Exception as e:
        st.error(f"錯誤: {e}")
