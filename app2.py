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
VERSION_TIME = "17:00" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

# --- UI 頂部註記 ---
st.title("💊 PMDA 雙英文字串精確對位版")
st.markdown(f"""
> **版本更新紀錄** > 📅 更新日期：`{VERSION_DATE}` | ⏰ 更新時間：`{VERSION_TIME}`  
> 🛠️ **修正重點**：鎖定「商品情報」區塊搜尋（排除臨床數據）、解決 JapicID 誤抓適應症問題。
""")
st.divider()

def get_pure_katakana(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_info": ""}
    
    try:
        # 1. 嚴格 ID 提取 (長度限制 + 數字檢查)
        final_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        if len(final_id) < 5 or len(final_id) > 10:
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

            # --- [位置 B] 商品名 (鎖定 商品情報 區塊) ---
            # 找到包含「商品情報」字樣的標題
            info_section = soup.find(['h4', 'div', 'b'], string=re.compile(r'商品情報'))
            if info_section:
                # 取得該區塊後的緊鄰內容 (通常是表格或段落)
                parent_container = info_section.find_parent()
                # 尋找與日文關鍵字最接近的英文字串
                search_area = parent_container.get_text(separator=" ", strip=True)
                res["raw_info"] = search_area[:200] # 只取前200字，避免抓到後段臨床數據
                
                # 正則：抓取在大寫字母開頭、位於日文字後的英文 (排除常見劑型數字)
                # 優先匹配：SCEMBLIX tablets 這種結構
                en_pattern = re.findall(r'\b[A-Z][A-Z\s\-\.a-z]{3,}\b', res["raw_info"])
                if en_pattern:
                    # 商品名通常出現在「商品情報」區塊的第一個或第二個英文字串
                    res["trade_en"] = en_pattern[0].strip()
                        
    except Exception as e:
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
            row_str = "".join(row_vals)
            if any(k in row_str for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    # 辨識 JapicID，排除「適應症」、「效能」
                    if 'No' in val: cols['No'] = idx
                    if any(k in val for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in val: cols['Ing'] = idx
                    if ('ID' in val or 'Japic' in val) and not any(x in val for x in ['適應', '效能', '治療']):
                        cols['ID'] = idx
                break
        
        if header_idx is not None:
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                
                # 取得 ID 並判斷是否誤抓適應症
                raw_id = str(row.iloc[cols.get('ID', -1)]).strip()
                # 如果內容包含超過 3 個中文字，判定為非 ID
                if len(re.findall(r'[\u4e00-\u9fff]', raw_id)) > 3:
                    final_id = "[待搜尋]"
                else:
                    final_id = raw_id if (raw_id.lower() != 'none' and raw_id != "nan") else "[待搜尋]"
                
                trade_jp = str(row.iloc[cols.get('Trade', 1)]).strip()
                data_rows.append({
                    "No.": no_raw,
                    "商品名(日)": trade_jp,
                    "關鍵字(片假名)": get_pure_katakana(trade_jp),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": final_id
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
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": info["trade_en"],
                        "Ingredient (EN)": info["ing_en"],
                        "商品情報預覽": info["raw_info"],
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
                st.download_button("📥 下載 Excel", out.getvalue(), f"PMDA_Refined_{VERSION_DATE}.xlsx")
    except Exception as e:
        st.error(f"錯誤: {e}")
