import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 19:30

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心檢索邏輯：基於「2. 禁忌」錨點的文字提取 ---
def get_kegg_by_anchor(kw_trade):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]"}

    try:
        # 1. 搜尋並獲取 JAPIC ID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_search = session.get(search_url, timeout=10)
        
        japic_code = None
        code_match = re.search(r'japic_code=(\d+)', resp_search.url + resp_search.text)
        if code_match:
            japic_code = code_match.group(1)

        if japic_code:
            time.sleep(0.5)
            # 2. 進入詳情頁
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            resp_med = session.get(target_url, timeout=10)
            
            # 取得「2. 禁忌」之前的內容
            # 使用 BeautifulSoup 轉為純文字，避免標籤干擾
            soup = BeautifulSoup(resp_med.text, 'html.parser')
            full_text = soup.get_text(separator=" ", strip=True)
            
            # 截取到「2. 禁忌」為止的字串
            anchor = "2. 禁忌"
            if anchor in full_text:
                useful_part = full_text.split(anchor)[0]
                
                # 使用正則表達式尋找英文單字串（包含空格、連字號）
                # 排除掉長度太短或純數字的內容
                english_names = re.findall(r'[A-Za-z][A-Za-z\s\-]{3,}', useful_part)
                
                # 清洗結果：去除頭尾空格
                english_names = [n.strip() for n in english_names if len(n.strip()) > 2]
                
                # 根據您的定義：
                # 第一個通常是成分 (Generic)，第二個是商品 (Trade)
                # 註：如果順序相反或抓取過多，我們可以再微調 index
                if len(english_names) >= 1:
                    res["ing_en"] = english_names[0]
                if len(english_names) >= 2:
                    res["trade_en"] = english_names[1]
                    
    except Exception as e:
        pass
    return res

# --- 檔案清理與 UI (保持一致) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        if '販' in "".join(row) and '成' in "".join(row):
            header_idx = i
            for idx, cell in enumerate(row):
                if 'No' in str(cell): cols['No'] = idx
                if '販' in str(cell): cols['Trade'] = idx
                if '成' in str(cell): cols['Ing'] = idx
            break
    if header_idx is None: return None
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
        t_full = str(row.iloc[cols['Trade']]).strip()
        i_full = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no, "商品名(日)": t_full,
            "商品名(關鍵字)": get_katakana_prefix(t_full),
            "成分名(日)": i_full
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (2.禁忌 錨點版：2025-12-29 19:30)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 辨識成功！")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始執行"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"處理中 No.{r['No.']}: {r['商品名(關鍵字)']}...")
                info = get_kegg_by_anchor(r['商品名(關鍵字)'])
                results.append({
                    "No.": r['No.'], "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(1.0)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel", output.getvalue(), "PMDA_Anchor_Result.xlsx")
