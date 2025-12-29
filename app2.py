import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 21:00

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：跳過搜尋，直接嘗試從 JAPIC ID 提取 (如果搜尋失敗則暴力掃描) ---
def fetch_by_japic_logic(kw_trade, kw_ing):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]", "target_id": "None"}

    try:
        # 1. 搜尋步驟 (這是為了拿到 japic_code)
        # 增加 Referer 偽裝成從官網進入
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_search = session.get(search_url, headers=headers, timeout=15)
        
        # 暴力提取所有可能是 japic_code 的 8 位數字
        japic_codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
        
        if japic_codes:
            japic_code = japic_codes[0]
            res["target_id"] = japic_code
            
            # 2. 進入目標頁面
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            resp_med = session.get(target_url, headers=headers, timeout=15)
            
            # 使用您的「2. 禁忌」邏輯
            # 為了避免標籤干擾，將 HTML 轉換為乾淨的換行文字
            soup = BeautifulSoup(resp_med.text, 'html.parser')
            # 移除腳本與樣式
            for script in soup(["script", "style"]):
                script.decompose()
            
            full_text = soup.get_text(separator="\n")
            
            # 找到「2. 禁忌」的位置並截斷
            if "2. 禁忌" in full_text:
                pre_contra_text = full_text.split("2. 禁忌")[0]
                
                # 提取英文名詞 (首字母大寫，通常包含多個單字)
                # 我們找連續的英文單字，例如 "Drospirenone" 或 "Slynd"
                found_names = re.findall(r'\b[A-Z][a-zA-Z\s\-]{3,}\b', pre_contra_text)
                
                # 去除重複並過濾 (例如排除掉 "JAPIC" 這種字眼)
                clean_names = []
                for n in found_names:
                    n = n.strip()
                    if n.upper() not in ["JAPIC", "KEGG", "MEDICUS"] and len(n) > 2:
                        if n not in clean_names:
                            clean_names.append(n)
                
                # 您的物理定義：第一個是成分名，第二個是商品名
                if len(clean_names) >= 1:
                    res["ing_en"] = clean_names[0]
                if len(clean_names) >= 2:
                    res["trade_en"] = clean_names[1]
            
            # 備援機制：如果禁忌邏輯沒抓到，改抓表格
            if res["trade_en"] == "[查無結果]":
                th_trade = soup.find('th', string=re.compile(r'欧文商標名'))
                if th_trade: res["trade_en"] = th_trade.find_next_sibling('td').get_text(strip=True)
                th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
                if th_ing: res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- UI 與 檔案處理 ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i]])
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
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
        t_f = str(row.iloc[cols['Trade']]).strip()
        i_f = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no, "商品名(日)": t_f, "關鍵字": get_katakana_prefix(t_f), "成分名(日)": i_f
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (物理定位精準版：2025-12-29 21:00)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    df = clean_dataframe(pd.read_excel(f, header=None))
    if df is not None:
        st.success("✅ 檔案辨識成功")
        st.dataframe(df, use_container_width=True)
        if st.button("🚀 開始檢索 (進入 JAPIC 頁面解析)"):
            results = []
            bar = st.progress(0)
            log = st.empty()
            for i, r in df.iterrows():
                log.text(f"正在分析 No.{r['No.']} (關鍵字: {r['關鍵字']})")
                info = fetch_by_japic_logic(r['關鍵字'], r['成分名(日)'])
                
                results.append({
                    "No.": r['No.'], "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"],
                    "JapicID": info["target_id"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(1.5) # 提高延遲確保安全性
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載最終結果", output.getvalue(), "PMDA_Final_Fix.xlsx")
