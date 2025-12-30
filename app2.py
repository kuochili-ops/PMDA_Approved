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

# --- UI 頂部註記 ---
st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：解決 [解析異常]、強化日文與英文同框鎖定邏輯、嚴格修正 JapicID 欄位錯位。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "loc_info": ""}
    
    try:
        # 1. JapicID 嚴格清洗 (僅保留數字)
        final_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        if not (final_id and 5 <= len(final_id) <= 10):
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [位置 A] 成分名 (歐文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [位置 B] 商品名 (關鍵字同框搜尋法) ---
            # 直接在所有 td 中尋找包含片假名關鍵字的儲存格
            all_tds = soup.find_all('td')
            found = False
            for td in all_tds:
                txt = td.get_text(separator=" ", strip=True)
                # 如果這格裡面有日文關鍵字，且有大寫英文
                if kw_trade in txt:
                    # 正則：抓取大寫開頭的英文字串 (包含空格、劑型)
                    en_match = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', txt)
                    if en_match:
                        # 排除掉只有劑型或單位的情況，取最像商標名的那一組
                        res["trade_en"] = en_match[0].strip()
                        res["loc_info"] = f"Found in TD: {txt[:40]}..."
                        found = True
                        break
            
            # 備援：如果上面沒抓到，改抓特定結構 tr[2]/td[2]
            if not found:
                tables = soup.find_all('table')
                for tb in tables:
                    trs = tb.find_all('tr')
                    if len(trs) >= 2:
                        tds = trs[1].find_all('td')
                        if len(tds) >= 2 and kw_trade in tds[1].get_text():
                            txt = tds[1].get_text(strip=True)
                            en = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', txt)
                            if en:
                                res["trade_en"] = en[0].strip()
                                break

    except Exception as e:
        res["trade_en"] = f"[解析錯誤: {str(e)[:15]}]"
        
    return res

# --- 主程式介面 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
        # 遍歷前 30 行尋找表頭
        for i in range(min(30, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            row_str = "".join(row_vals)
            if any(k in row_str for k in ['商', '成', '販']):
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
                
                # 判斷 JapicID 是否誤抓 (如果有中文字就視為誤抓)
                id_val = str(row.iloc[cols.get('ID', -1)]).strip()
                if re.search(r'[\u4e00-\u9fff]', id_val) or len(id_val) > 12:
                    id_val = "[待搜尋]"
                else:
                    id_val = id_val if (id_val.lower() != 'none' and id_val != "nan") else "[待搜尋]"
                
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
                        "定位資訊": info["loc_info"],
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
                st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_Final_Fix_{VERSION_DATE}.xlsx")
        else:
            st.error("❌ 找不到表頭。")
    except Exception as e:
        st.error(f"錯誤: {e}")
