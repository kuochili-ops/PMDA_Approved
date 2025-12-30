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
VERSION_TIME = "16:00" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：回歸醫療用主頁面，使用「全字串後向匹配」，專攻 Scemblix 等難抓欄位。
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

            # --- [策略 1] 抓成分 (歐文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [策略 2] 暴力掃描 Trade Name ---
            # 將整頁轉為純文字，移除多餘空白
            full_text = soup.get_text(separator=" ", strip=True)
            
            # 尋找「日文關鍵字」後面的 150 個字元
            search_pattern = re.escape(kw_trade) + r"(.{1,150})"
            match = re.search(search_pattern, full_text)
            
            if match:
                context = match.group(1)
                # 從這段文字中提取「連續大寫字母開頭的英文字」
                # 排除常見的日文字、單位(mg)等
                en_candidates = re.findall(r'\b[A-Z][A-Za-z\s\-\.]{4,}\b', context)
                if en_candidates:
                    # 篩選掉長得像成分名的 (如果已經抓到成分名了)
                    for candidate in en_candidates:
                        cand_clean = candidate.strip()
                        if len(cand_clean) > 3 and cand_clean.lower() not in res["ing_en"].lower():
                            res["trade_en"] = cand_clean
                            break

    except Exception:
        res["trade_en"] = "[解析異常]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        # 讀取 Excel 且不設 header，手動掃描表頭
        raw_df = pd.read_excel(f, header=None)
        header_row = 0
        cols = {'No': 0, 'Trade': 1, 'Ing': 2, 'ID': 3}
        
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
            no_val = str(row.iloc[cols['No']]).strip().replace('.0','')
            if not no_val.isdigit() and len(data_rows) > 0: break
            
            trade_jp = str(row.iloc[cols['Trade']]).strip()
            # JapicID 修正邏輯
            id_raw = str(row.iloc[cols['ID']]).strip()
            if len(re.findall(r'[0-9]', id_raw)) < 5: 
                id_clean = "[待搜尋]"
            else:
                id_clean = re.sub(r'[^0-9]', '', id_raw)[:8]

            data_rows.append({
                "No.": no_val,
                "商品名(日)": trade_jp,
                "關鍵字": get_pure_katakana(trade_jp),
                "JapicID": id_clean,
                "成分(日)": str(row.iloc[cols['Ing']]).strip()
            })

        df = pd.DataFrame(data_rows)
        st.subheader("📋 待處理預覽")
        st.dataframe(df)

        if st.button("🚀 執行全自動對位"):
            results = []
            bar = st.progress(0)
            for i, r in df.iterrows():
                info = fetch_dual_strings(r['JapicID'], r['關鍵字'])
                results.append({
                    "No.": r['No.'],
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "來源網址": info["url"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(0.6)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 最終解析結果")
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_Final_Fix.xlsx")

    except Exception as e:
        st.error(f"Excel 讀取失敗: {e}")
