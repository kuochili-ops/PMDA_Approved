import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- Azure 翻譯設定 ---
AZURE_KEY = "您的_Azure_Key"
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/"
AZURE_REGION = "您的區域"

def translate_to_en(text):
    if pd.isna(text) or not str(text).strip(): return ""
    url = f"{AZURE_ENDPOINT}/translate?api-version=3.0&from=ja&to=en"
    headers = {
        'Ocp-Apim-Subscription-Key': AZURE_KEY,
        'Ocp-Apim-Subscription-Region': AZURE_REGION,
        'Content-type': 'application/json'
    }
    try:
        request = requests.post(url, headers=headers, json=[{'text': str(text)}], timeout=10)
        return request.json()[0]['translations'][0]['text']
    except: return "[翻譯失敗]"

def fetch_data_by_katakana(trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    # 提取片假名核心藥名
    raw_clean = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    katakana_match = re.match(r'^[\u30A0-\u30FF\u30FB\u30FC]+', raw_clean)
    search_keyword = katakana_match.group(0) if katakana_match else raw_clean
    
    if len(search_keyword) < 2: return res

    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if codes:
            jid = codes[0].zfill(8)
            res["target_id"] = jid
            # 抓英文商標
            rt = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}", headers=headers)
            rt.encoding = rt.apparent_encoding
            t_text = BeautifulSoup(rt.text, 'html.parser').get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()
            # 抓英文成分
            ri = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}", headers=headers)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except: pass
    return res

st.title("💊 PMDA 萬能解析器 (新藥/變更識別版)")

f = st.file_uploader("上傳原始 Excel", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    s_names = xl.sheet_names
    selected_sheet = st.selectbox("請選擇分頁 (例如 12 月)：", s_names, index=len(s_names)-1)
    
    if st.button("開始解析"):
        df_raw = pd.read_excel(f, sheet_name=selected_sheet, header=None)
        
        # 欄位定位
        h_idx, t_col, n_col, ind_col, status_col = -1, -1, -1, -1, -1
        for i in range(min(20, len(df_raw))):
            row_str = [str(x) for x in df_raw.iloc[i]]
            if any('販' in x for x in row_str):
                h_idx = i
                for idx, v in enumerate(row_str):
                    if '販' in v: t_col = idx
                    if 'No' in v: n_col = idx
                    if '效' in v or '效能' in v or '效果' in v: ind_col = idx
                    if '承認' in v and idx != t_col: status_col = idx
                break

        if h_idx != -1:
            valid_rows = df_raw.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            bar = st.progress(0)
            
            for i, (idx, row) in enumerate(valid_rows.iterrows()):
                no_str = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_str.isdigit(): continue
                
                # A. 識別新藥或變更
                raw_status = str(row.iloc[status_col]).strip() if status_col != -1 else ""
                status_label = "新藥" if "承" in raw_status and "認" in raw_status else "變更"
                
                # B. 片假名核心搜尋
                jp_name = str(row.iloc[t_col]).strip()
                info = fetch_data_by_katakana(jp_name)
                
                # C. Azure 翻譯適應症
                jp_ind = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_ind = translate_to_en(jp_ind)
                
                results.append({
                    "No.": no_str,
                    "分類": status_label,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "Indication (EN)": en_ind
                })
                bar.progress((i+1)/len(valid_rows))
                time.sleep(0.6)
            
            final_df = pd.DataFrame(results)
            st.dataframe(final_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 下載最終解析成果", out.getvalue(), "PMDA_Final_Report.xlsx")
