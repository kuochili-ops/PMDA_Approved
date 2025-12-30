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
VERSION_TIME = "23:20" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：放棄表格定位，改用「全網頁文字流」掃描，解決 Scemblix 等 Trade Name 未檢出問題。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    # 提取第一個連貫的片假名區塊作為關鍵字
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. ID 處理
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

            # --- [策略 A] 成分名 (定位 欧文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [策略 B] 商品名 (全網頁文字掃描) ---
            # 取得整頁純文字並壓縮空白
            page_text = soup.get_text(separator=" ", strip=True)
            
            # 尋找關鍵字 (如 セムブリックス) 後面的英文字塊
            # 規則：在關鍵字後 100 字元內，尋找最像商標名的英文字 (大寫開頭, 4個字母以上)
            pattern = re.escape(kw_trade) + r'.*?([A-Z][A-Za-z0-9\s\-\.]{4,})'
            match = re.search(pattern, page_text)
            
            if match:
                extracted = match.group(1).strip()
                # 排除掉一些明顯不是商品名的日文字干擾
                clean_en = re.split(r'[^A-Za-z0-9\s\-\.]', extracted)[0]
                res["trade_en"] = clean_en.strip()
            
            # 備援：如果正則失敗，找網頁前 1/4 區塊中最長的大寫字串
            if res["trade_en"] == "[未檢出]":
                all_en = re.findall(r'\b[A-Z][A-Z\s\-]{4,}\b', page_text[:2000])
                if all_en:
                    res["trade_en"] = all_en[0].strip()

    except Exception:
        res["trade_en"] = "[異常]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("1. 請上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
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
            st.subheader("📋 待處理預覽")
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
                st.subheader("📊 最終解析結果")
                st.dataframe(res_df, use_container_width=True)
                
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載成果", out.getvalue(), f"PMDA_Final_TextScan_{VERSION_DATE}.xlsx")
    except Exception as e:
        st.error(f"錯誤: {e}")
