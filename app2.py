import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 穩定修復版

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
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]", "target_id": "None", "source_url": ""}

    try:
        # 1. 處理 JapicID
        final_id = None
        if japic_id and str(japic_id).lower() != 'none' and str(japic_id).strip() != "":
            final_id = str(japic_id).split('.')[0].strip().zfill(8)
        
        # 若 ID 無效，則嘗試用關鍵字搜尋
        if not final_id or final_id == "0000None":
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            resp_search = session.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            res["target_id"] = final_id
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["source_url"] = target_url
            
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding
            soup = BeautifulSoup(resp_med.text, 'html.parser')

            # --- 抓取位置 A：成分名 (欧文一般名) ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- 抓取位置 B：商品名 (規制区分) ---
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    # 抓取最後一段連續英文
                    en_matches = re.findall(r'\b[A-Z][A-Z0-9\s\-\.]{3,}\b', raw_text)
                    if en_matches:
                        res["trade_en"] = en_matches[-1].strip()

    except Exception as e:
        res["trade_en"] = f"[解析異常]"
    
    return res

# --- UI 與 檔案解析 (加強容錯) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    
    # 遍歷前 20 行尋找表頭
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        row_str = "".join(row)
        
        # 只要包含這些關鍵字就判定為表頭列
        if any(k in row_str for k in ['商品', '商標', '販', '成', '一般名']):
            header_idx = i
            for idx, cell in enumerate(row):
                if any(k in cell for k in ['No', '編號']): cols['No'] = idx
                if any(k in cell for k in ['商品', '商標', '販賣']): cols['Trade'] = idx
                if any(k in cell for k in ['成分', '一般名']): cols['Ing'] = idx
                if any(k in cell for k in ['Japic', 'ID', '代碼']): cols['ID'] = idx
            break
            
    # 檢查是否漏掉必要欄位
    if header_idx is None or 'Trade' not in cols or 'Ing' not in cols:
        st.error("❌ 找不到必要的表頭欄位（需要有包含 '商品' 與 '成分' 的列）。請檢查 Excel 格式。")
        return None
    
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        # 取得 No. 進行結尾判定
        raw_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not raw_no.isdigit() and len(rows) > 0: 
            break
        
        rows.append({
            "No.": raw_no,
            "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
            "成分名(日)": str(row.iloc[cols['Ing']]).strip(),
            "JapicID": str(row.iloc[cols['ID']]).strip() if 'ID' in cols else "None"
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (來源網址註記修正版)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    raw_df = pd.read_excel(f, header=None)
    df = clean_dataframe(raw_df)
    
    if df is not None:
        st.success(f"✅ 成功辨識 {len(df)} 筆藥品資料")
        st.dataframe(df, use_container_width=True)
        
        if st.button("🚀 開始深度解析 (含來源網址)"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            
            for i, r in df.iterrows():
                log.text(f"正在處理 No.{r['No.']}：{r['商品名(日)']}")
                info = fetch_by_japic_logic(r['JapicID'], get_katakana_prefix(r['商品名(日)']))
                
                results.append({
                    "No.": r['No.'], 
                    "JapicID": info["target_id"],
                    "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"],
                    "資料來源網址": info["source_url"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(1.1)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 解析完成")
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Final_With_Source.xlsx")
