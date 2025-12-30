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
VERSION_TIME = "16:30" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

# --- UI 頂部註記 ---
st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：解決 JapicID 誤抓適應症問題、改用「全網頁文本掃描」抓取英商名（解決空白問題）。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_reg_text": ""}
    
    try:
        # 1. 嚴格 ID 提取 (排除中文字多的欄位)
        final_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        if len(final_id) < 5: # 如果 ID 太短或不對，改用搜尋
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

            # --- [策略 A] 抓取成分名 (欧文一般名) ---
            all_text = soup.get_text(separator=" ", strip=True)
            ing_match = re.search(r'欧文一般名\s*[:：]?\s*([A-Za-z0-9\s\-\.\,（）\(\)]+)', all_text)
            if ing_match:
                res["ing_en"] = ing_match.group(1).split(' 日局')[0].strip()

            # --- [策略 B] 全網頁掃描抓取 Trade Name ---
            # 直接尋找片假名商品名後面的英文字
            # 範例：セムブリックス錠20mg SCEMBLIX tablets
            res["raw_reg_text"] = "已執行全頁掃描" 
            
            # 找出所有包含大寫英文的段落
            blocks = soup.find_all(['td', 'div', 'p'])
            potential_names = []
            for b in blocks:
                t = b.get_text(strip=True)
                if kw_trade in t:
                    # 提取該區塊中的連續英文
                    en = re.findall(r'\b[A-Z][A-Z\s\-\.a-z]{3,}\b', t)
                    if en: potential_names.extend(en)
            
            if potential_names:
                # 篩選掉明顯是成分名的（通常較長或在括號內）
                # 取最後一個通常是商品商標名
                res["trade_en"] = potential_names[-1].strip()
                res["raw_reg_text"] = f"從區塊中提取: {potential_names}"
                        
    except Exception as e:
        res["trade_en"] = f"[異常: {str(e)[:10]}]"
        
    return res

# --- 主程式 ---
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        header_idx, cols = None, {}
        for i in range(min(30, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            row_str = "".join(row_vals)
            if any(k in row_str for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    # 強化 JapicID 的辨識，排除「效能」、「適應」等關鍵字
                    if 'No' in val: cols['No'] = idx
                    if any(k in val for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in val: cols['Ing'] = idx
                    if ('Japic' in val or 'ID' in val) and '適應' not in val: 
                        cols['ID'] = idx
                break
        
        if header_idx is not None:
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                
                # 取得 JapicID 並再次確認內容不是長篇大論的中文（適應症）
                id_val = str(row.iloc[cols.get('ID', -1)]).strip()
                if len(id_val) > 15: # 如果 ID 長度超過 15 碼，很可能是抓到適應症了
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
                        "抓取詳情": info["raw_reg_text"],
                        "來源網址": info["url"]
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                st.subheader("📊 2. 最終解析結果")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
                
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    pd.DataFrame(results).to_excel(writer, index=False)
                st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_Fix_{VERSION_DATE}.xlsx")
    except Exception as e:
        st.error(f"錯誤: {e}")
