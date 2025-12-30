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
VERSION_TIME = "23:30" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

# --- UI 頂部註記 ---
st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：採用 XPath 物理路徑定位（tr[2]/td[2]）精確抓取 SCEMBLIX、嚴格排除非數字 JapicID。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_loc": ""}
    
    try:
        # 1. 嚴格 ID 提取：只接受 5-10 位純數字
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

            # --- [位置 A] 成分名 (欧文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [位置 B] 商品名 (根據您的 XPath 邏輯定位) ---
            # XPath: /html/body/div[2]/div[3]/table/tbody/tr[2]/td[2]
            # 對應到 BeautifulSoup：找第 3 個 div 裡面的第 2 個 tr 的第 2 個 td
            divs = soup.find_all('div', recursive=False) # 找 body 下的第一層 div
            if not divs: # 有時 body 下沒直接 div，改找所有 div
                divs = soup.find_all('div')
                
            # 遍歷 div 尋找包含關鍵字的表格
            found_trade = False
            for d in divs:
                table = d.find('table')
                if table:
                    trs = table.find_all('tr')
                    if len(trs) >= 2:
                        # 檢查第二列 (tr[2]) 的內容
                        tds = trs[1].find_all('td')
                        if len(tds) >= 2:
                            target_text = tds[1].get_text(separator=" ", strip=True)
                            # 如果這格包含片假名商品名，則提取其中的英文
                            if kw_trade in target_text or any(c in target_text for c in "ァアィイゥウェエ"):
                                en_match = re.findall(r'\b[A-Z][A-Z\s\-\.a-z]{3,}\b', target_text)
                                if en_match:
                                    res["trade_en"] = en_match[0].strip()
                                    res["raw_loc"] = f"Match in table/tr[2]/td[2]: {target_text[:50]}"
                                    found_trade = True
                                    break
            
            # 備援：如果物理定位失敗，再嘗試全頁首個大寫英文塊
            if not found_trade:
                reg_th = soup.find('th', string=re.compile(r'規制.*区分|販売.*名'))
                if reg_th:
                    res["trade_en"] = re.findall(r'\b[A-Z][A-Z\s\-\.a-z]{3,}\b', reg_th.find_next_sibling('td').get_text())[0]

    except Exception:
        res["trade_en"] = "[解析異常]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
        for i in range(min(30, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            if any(k in "".join(row_vals) for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    # 嚴格排除包含「適應、效能、治療」的 ID 欄位
                    if 'No' in val: cols['No'] = idx
                    if any(k in val for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in val: cols['Ing'] = idx
                    if ('ID' in val or 'Japic' in val) and not any(x in val for x in ['適應', '效能', '治療', '用量']):
                        cols['ID'] = idx
                break
        
        if header_idx is not None:
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                
                # ID 內容檢查：如果包含中文字則判定為錯位
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
                        "定位資訊": info["raw_loc"],
                        "來源網址": info["url"]
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                st.subheader("📊 2. 最終解析結果")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
                
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    pd.DataFrame(results).to_excel(writer, index=False)
                st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_XPathFix_{VERSION_DATE}.xlsx")
    except Exception as e:
        st.error(f"錯誤: {e}")
