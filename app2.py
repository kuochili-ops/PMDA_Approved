import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 最終修正版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：代入 JapicID 並根據 HTML 標籤物理定位 ---
def fetch_by_japic_logic(japic_id, kw_trade):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]", "target_id": "None"}

    try:
        # 1. 取得 JapicID (如果傳入的是 None，則嘗試搜尋一次)
        final_id = str(japic_id).strip().zfill(8) if japic_id and str(japic_id).lower() != 'none' else None
        
        if not final_id:
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            resp_search = session.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
            if codes: final_id = codes[0]

        if final_id:
            res["target_id"] = final_id
            # 2. 直攻目標網址
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding
            soup = BeautifulSoup(resp_med.text, 'html.parser')

            # --- 策略 A：抓取成分名 (定位：欧文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- 策略 B：抓取商品名 (定位：規制区分) ---
            # 根據您的觀察，商品英文名在「規制区分」後的 <td> 內
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    # 取得單元格文字，通常格式為：日文商品名 英文商品名
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    # 提取最後一段連續英文 (包含空格與劑型)
                    en_matches = re.findall(r'\b[A-Z][A-Z0-9\s\-\.]{3,}\b', raw_text)
                    if en_matches:
                        # 取最後一個匹配項，這通常是正確的歐文商標名
                        res["trade_en"] = en_matches[-1].strip()

    except Exception as e:
        res["trade_en"] = f"[解析錯誤]"
    
    return res

# --- UI 與 檔案解析 ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    # 尋找表頭
    for i in range(min(20, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i]])
        if '商品' in row_str or '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
                c_str = str(cell)
                if 'No' in c_str: cols['No'] = idx
                if '商' in c_str: cols['Trade'] = idx
                if '成' in c_str: cols['Ing'] = idx
                if 'Japic' in c_str: cols['ID'] = idx
            break
            
    if header_idx is None: return None
    
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit() and len(rows) > 0: break
        
        rows.append({
            "No.": val_no,
            "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
            "成分名(日)": str(row.iloc[cols['Ing']]).strip(),
            "JapicID": str(row.iloc[cols.get('ID', -1)]).strip() if 'ID' in cols else "None"
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (規制区分物理定位版)")
st.info("邏輯：由 JapicID 直攻網頁，成分取自『欧文一般名』，商品名取自『規制区分』格內最後一段英文。")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    raw_df = pd.read_excel(f, header=None)
    df = clean_dataframe(raw_df)
    
    if df is not None:
        st.success("✅ 檔案辨識成功")
        st.dataframe(df, use_container_width=True)
        
        if st.button("🚀 開始精確解析"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            
            for i, r in df.iterrows():
                log.text(f"正在處理 No.{r['No.']}：{r['商品名(日)']}")
                # 傳入 ID 與商品名(作為搜尋備案)
                info = fetch_by_japic_logic(r['JapicID'], get_katakana_prefix(r['商品名(日)']))
                
                results.append({
                    "No.": r['No.'], 
                    "JapicID": info["target_id"],
                    "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(1.1)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 最終解析結果")
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Final_Regulatory.xlsx")
