import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- Azure 翻譯設定 (請填入您的金鑰) ---
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
    
    # --- 核心邏輯：提取片假名關鍵字 ---
    # 1. 先切掉換行與括號公司名
    clean_name = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    # 2. 正則提取開頭連續的片假名 (含長音符 ─ 和中點 ・)
    katakana_match = re.match(r'^[\u30A0-\u30FF\u30FB\u30FC]+', clean_name)
    search_keyword = katakana_match.group(0) if katakana_match else clean_name
    
    if len(search_keyword) < 2: return res

    try:
        # 搜尋 JapicID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if codes:
            final_id = codes[0].zfill(8)
            res["target_id"] = final_id
            
            # A. 抓 Trade Name (EN)
            rt = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}", headers=headers)
            rt.encoding = rt.apparent_encoding
            t_text = BeautifulSoup(rt.text, 'html.parser').get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # B. 抓 Ingredient (EN)
            ri = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}", headers=headers)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except: pass
    return res

st.title("🧪 PMDA 12月專用：片假名精準搜尋 + Azure 翻譯")

f = st.file_uploader("上傳 12 月 Excel", type=['xlsx'])
if f:
    xl = pd.ExcelFile(f)
    sheet_name = st.selectbox("選擇分頁", xl.sheet_names, index=len(xl.sheet_names)-1)
    
    if st.button("🚀 執行精準解析"):
        df = pd.read_excel(f, sheet_name=sheet_name, header=None)
        
        # 尋找 販賣名(t_col)、No(n_col)、效能效果(ind_col)
        h_idx, t_col, n_col, ind_col = -1, -1, -1, -1
        for i in range(min(15, len(df))):
            row_vals = [str(x) for x in df.iloc[i]]
            if any('販' in x for x in row_vals):
                h_idx = i
                for idx, v in enumerate(row_vals):
                    if '販' in v: t_col = idx
                    if 'No' in v: n_col = idx
                    if '効' in v or '效果' in v: ind_col = idx
                break

        if h_idx != -1:
            rows = df.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            bar = st.progress(0)
            
            for i, (idx, row) in enumerate(rows.iterrows()):
                no_val = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_val.isdigit(): continue
                
                jp_name = str(row.iloc[t_col]).strip()
                # 執行「片假名優先」抓取
                info = fetch_data_by_katakana(jp_name)
                
                # 翻譯適應症
                jp_ind = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_ind = translate_to_en(jp_ind)
                
                results.append({
                    "No.": no_val,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "Indication (EN)": en_ind
                })
                bar.progress((i+1)/len(rows))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載解析結果", out.getvalue(), "PMDA_Dec_Katakana_Azure.xlsx")
