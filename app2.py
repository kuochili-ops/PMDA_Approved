import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 11:50 模糊定位強化版 (針對 Scemblix 最佳化)

st.set_page_config(layout="wide", page_title="PMDA 解析工具")

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_reg_text": ""}
    
    try:
        # --- 1. ID 處理 ---
        final_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        if not (final_id and len(final_id) >= 5):
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

            # --- [位置 1] 成分名 (欧文一般名) ---
            # 改用模糊匹配：只要包含 '欧文' 和 '一般名'
            th_ing = soup.find('th', string=re.compile(r'欧文.*一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [位置 2] 商品名 (規制区分 或 販売名) ---
            # 優先找「規制区分」，找不到就找「販売名」
            target_th = soup.find('th', string=re.compile(r'規制.*区分|販売.*名'))
            
            if target_th:
                td_node = target_th.find_next_sibling('td')
                if td_node:
                    raw_text = td_node.get_text(separator=" ", strip=True)
                    res["raw_reg_text"] = raw_text
                    
                    # 邏輯：抓取最後一段大寫開頭的英文字串
                    # [A-Z] 代表大寫開頭, [A-Za-z0-9\s\-\.] 代表後續內容
                    en_matches = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', raw_text)
                    if en_matches:
                        # 排除掉常見的日文單位干擾，並取最後一組
                        res["trade_en"] = en_matches[-1].strip()
                        
    except Exception:
        res["trade_en"] = "[解析異常]"
        
    return res

# --- UI 介面 (完整邏輯) ---
st.title("💊 PMDA 雙英文字串精確對位版 (Scemblix 修正)")

f = st.file_uploader("1. 請上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
        for i in range(min(20, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            if any(k in "".join(row_vals) for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    if 'No' in val: cols['No'] = idx
                    if any(k in val for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in val: cols['Ing'] = idx
                    if any(k in val for k in ['Japic', 'ID']): cols['ID'] = idx
                break
        
        if header_idx is not None:
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                raw_id = str(row.iloc[cols.get('ID', -1)]).strip()
                display_id = raw_id if (raw_id.lower() != 'none' and raw_id != "" and raw_id != "nan") else "[待搜尋]"
                trade_jp = str(row.iloc[cols.get('Trade', 1)]).strip()
                
                data_rows.append({
                    "No.": no_raw,
                    "商品名(日)": trade_jp,
                    "關鍵字(片假名)": get_pure_katakana(trade_jp),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": display_id
                })
            
            df = pd.DataFrame(data_rows)
            st.dataframe(df, use_container_width=True)

            if st.button("🚀 開始深度解析"):
                results = []
                bar = st.progress(0)
                for i, r in df.iterrows():
                    input_id = r['JapicID'] if r['JapicID'] != "[待搜尋]" else ""
                    info = fetch_dual_strings(input_id, r['關鍵字(片假名)'])
                    
                    results.append({
                        "No.": r['No.'],
                        "JapicID": info["target_id"],
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": info["trade_en"],
                        "成分名(日)": r['成分名(日)'],
                        "Ingredient (EN)": info["ing_en"],
                        "原始抓取內容": info["raw_reg_text"],
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
                st.download_button("📥 下載 Excel", out.getvalue(), "PMDA_Scemblix_Fix.xlsx")
        else:
            st.error("❌ 找不到表頭。")
    except Exception as e:
        st.error(f"錯誤: {e}")
