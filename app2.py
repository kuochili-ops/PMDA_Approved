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
VERSION_TIME = "16:50" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：改用產品情報頁面 (`japic_med_product`) 作為主要資料源，精確提取 XPath 路徑對應的英文商標名。
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
        # 1. 修正 JapicID 格式 (解決 71700.0 與長 ID 錯位問題)
        raw_id = str(japic_id_input).split('.')[0].strip()
        clean_id = re.sub(r'[^0-9]', '', raw_id)
        
        # 如果 ID 長度不對 (正確應為 8 位)，則啟動搜尋補完
        if not (5 <= len(clean_id) <= 9):
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            final_id = codes[0].zfill(8) if codes else ""
        else:
            final_id = clean_id.zfill(8)

        if final_id:
            # 使用您提供的專用產品情報網址
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [策略 A] Trade Name (EN) ---
            # 鎖定 /html/body/div[2]/div[2] 區域
            main_content = soup.find('div', id='main') or soup.find('div', class_='main')
            if not main_content:
                divs = soup.find_all('div')
                if len(divs) >= 2: main_content = divs[1]

            if main_content:
                # 在該區域尋找前 5 個 P 標籤
                ps = main_content.find_all('p')
                for p in ps:
                    txt = p.get_text(strip=True)
                    # 邏輯：日文商品名之後的第一組大寫英文字
                    # 排除掉只有劑型或單位的字串
                    en_match = re.search(r'([A-Z][A-Z\s\-\.]{4,})', txt)
                    if en_match and not any(c in txt for c in "あいうえお"):
                        res["trade_en"] = en_match.group(1).strip()
                        break
            
            # --- [策略 B] Ingredient (EN) ---
            # 因為產品頁不一定有成分英文，若沒抓到，改去醫療頁補抓
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            r_med = requests.get(med_url, headers=headers, timeout=10)
            s_med = BeautifulSoup(r_med.text, 'html.parser')
            th_ing = s_med.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

    except Exception as e:
        res["trade_en"] = f"[異常: {str(e)[:10]}]"
        
    return res

# --- 主介面 ---
f = st.file_uploader("1. 請上傳包含 JapicID 的 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        # 自動掃描表頭位置
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

        # 整理表一預覽資料
        preview_data = []
        for _, row in raw_df.iloc[header_row + 1:].iterrows():
            no_val = str(row.iloc[cols['No']]).strip().split('.')[0]
            if not no_val.isdigit() and len(preview_data) > 0: break
            
            trade_jp = str(row.iloc[cols['Trade']]).strip()
            # 初步清洗 ID，如果不符合長度就標記待搜尋
            raw_id_str = re.sub(r'[^0-9]', '', str(row.iloc[cols['ID']]).split('.')[0])
            
            preview_data.append({
                "No.": no_val,
                "商品名(日)": trade_jp,
                "關鍵字": get_pure_katakana(trade_jp),
                "JapicID": raw_id_str if (5 <= len(raw_id_str) <= 9) else "[待搜尋]"
            })

        st.subheader("📋 1. 待處理清單 (已修正 ID 與 網址模式)")
        st.dataframe(pd.DataFrame(preview_data))

        if st.button("🚀 執行深度對位 (Product 模式)"):
            results = []
            bar = st.progress(0)
            for i, r in enumerate(preview_data):
                info = fetch_dual_strings(r['JapicID'], r['關鍵字'])
                results.append({
                    "No.": r['No.'],
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "來源網址": info["url"]
                })
                bar.progress((i + 1) / len(preview_data))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 2. 最終解析結果")
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載成果 Excel", out.getvalue(), f"PMDA_ProductMode_Result.xlsx")

    except Exception as e:
        st.error(f"錯誤: {e}")
