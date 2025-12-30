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
VERSION_TIME = "15:45" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：改用產品情報頁面 (`japic_med_product`) 作為主要資料源，精確抓取標題 JapicID 與 XPath 路徑英文。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. ID 預處理
        final_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        if not (final_id and 5 <= len(final_id) <= 10):
            # 若無 ID，先去搜尋頁面抓 ID
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            # 使用您建議的「產品情報」專屬網址
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [策略 A] Trade Name (根據您提供的 XPath 邏輯) ---
            # XPath: /html/body/div[2]/div[2]/p[3]
            # 在 BS4 中我們直接找 div[class=main] 裡面的 p 標籤
            main_div = soup.find('div', id='main') or soup.find('div', class_='main')
            if not main_div: 
                # 備援：直接找 body 下的第二個或第三個 div
                all_divs = soup.find_all('div', recursive=False)
                if len(all_divs) >= 2: main_div = all_divs[1]

            if main_div:
                ps = main_div.find_all('p')
                # 通常英文商品名出現在前幾個 <p> 標籤中
                for p in ps:
                    txt = p.get_text(strip=True)
                    # 尋找純英文區塊 (排除常見日文)
                    en_match = re.search(r'([A-Z][A-Z\s\-\.]{3,})', txt)
                    if en_match and not any(c in txt for c in "あいうえお"):
                        res["trade_en"] = en_match.group(1).strip()
                        break
            
            # --- [策略 B] 成分名 (欧文一般名) ---
            # 在 product 頁面通常也在 table 中
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)
            else:
                # 備援：若 product 頁面找不到，改去 japic_med 頁面抓成分 (這部分結構通常很穩)
                med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
                r_med = requests.get(med_url, headers=headers, timeout=10)
                s_med = BeautifulSoup(r_med.text, 'html.parser')
                th_m = s_med.find('th', string=re.compile(r'欧文.*一般名'))
                if th_m: res["ing_en"] = th_m.find_next_sibling('td').get_text(strip=True)

    except Exception:
        res["trade_en"] = "[異常]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
        # 尋找表頭
        for i in range(min(30, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            if any(k in "".join(row_vals) for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    v = str(val)
                    if 'No' in v: cols['No'] = idx
                    if any(k in v for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in v: cols['Ing'] = idx
                    if ('ID' in v or 'Japic' in v) and not any(x in v for x in ['適應', '效能', '治療']):
                        cols['ID'] = idx
                break
        
        if header_idx is not None:
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                
                # JapicID 清洗：解決全部變 [待搜尋] 的問題
                raw_id = str(row.iloc[cols.get('ID', -1)]).strip()
                # 只有當內容包含過多中文或是 None 時才設為待搜尋
                if re.search(r'[\u4e00-\u9fff]{3,}', raw_id) or raw_id.lower() in ['none', 'nan', '']:
                    id_val = "[待搜尋]"
                else:
                    id_val = re.sub(r'[^0-9]', '', raw_id)
                
                trade_jp = str(row.iloc[cols.get('Trade', 1)]).strip()
                data_rows.append({
                    "No.": no_raw,
                    "商品名(日)": trade_jp,
                    "關鍵字(片假名)": get_pure_katakana(trade_jp),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": id_val
                })
            
            df = pd.DataFrame(data_rows)
            st.subheader("📋 1. 待處理清單預覽")
            st.dataframe(df, use_container_width=True)

            if st.button("🚀 開始深度解析"):
                results = []
                bar = st.progress(0)
                for i, r in df.iterrows():
                    info = fetch_dual_strings(r['JapicID'], r['關鍵字(片假名)'])
                    results.append({
                        "No.": r['No.'],
                        "JapicID": info["target_id"],
                        "Trade Name (EN)": info["trade_en"],
                        "Ingredient (EN)": info["ing_en"],
                        "來源網址": info["url"]
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                res_df = pd.DataFrame(results)
                st.subheader("📊 2. 最終解析結果")
                st.dataframe(res_df, use_container_width=True)
                
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載成果", out.getvalue(), f"PMDA_ProductMode_{VERSION_DATE}.xlsx")
    except Exception as e:
        st.error(f"錯誤: {e}")
