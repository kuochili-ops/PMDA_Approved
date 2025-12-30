import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- Azure 翻譯設定 ---
# 建議將金鑰放在 st.secrets 中以保安全
AZURE_KEY = "您的_Azure_Key"
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/"
AZURE_REGION = "您的區域(如japaneast)"

def translate_to_en(text):
    if pd.isna(text) or not str(text).strip(): return ""
    path = '/translate?api-version=3.0&from=ja&to=en'
    url = AZURE_ENDPOINT + path
    headers = {
        'Ocp-Apim-Subscription-Key': AZURE_KEY,
        'Ocp-Apim-Subscription-Region': AZURE_REGION,
        'Content-type': 'application/json'
    }
    body = [{'text': str(text)}]
    try:
        request = requests.post(url, headers=headers, json=body, timeout=10)
        response = request.json()
        return response[0]['translations'][0]['text']
    except:
        return "[翻譯失敗]"

def fetch_data_robust(trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    # 12 月專用清洗：針對「ルンスミオ皮下注...」這種併列劑型，只取最核心藥名
    # 移除劑型、劑量、公司名
    clean_keyword = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    clean_keyword = re.sub(r'(配合|注|錠|カプセル|點滴|シリンジ|ペン|分散錠|\d+).*$', '', clean_keyword)

    if len(clean_keyword) < 2: return res

    # 搜尋策略：直接搜尋藥名
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(clean_keyword)}"
    try:
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        if codes:
            final_id = codes[0].zfill(8)
            res["target_id"] = final_id
            
            # 進入產品頁抓 Trade Name
            t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            rt = requests.get(t_url, headers=headers)
            rt.encoding = rt.apparent_encoding
            soup_t = BeautifulSoup(rt.text, 'html.parser')
            t_text = soup_t.get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # 進入成分頁抓 Ingredient
            i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            ri = requests.get(i_url, headers=headers)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

st.title("🧪 PMDA 12 月新藥解析 + Azure 翻譯補完版")

f = st.file_uploader("上傳 12 月 Excel", type=['xlsx'])
if f:
    xl = pd.ExcelFile(f)
    sheet_name = st.selectbox("選擇 12 月分頁", xl.sheet_names, index=len(xl.sheet_names)-1)
    
    if st.button("🚀 開始深度修復與翻譯"):
        df = pd.read_excel(f, sheet_name=sheet_name, header=None)
        
        # 尋找欄位位置
        h_idx, t_col, n_col, ind_col = -1, -1, -1, -1
        for i in range(min(15, len(df))):
            row_str = [str(x) for x in df.iloc[i]]
            if any('販' in x for x in row_str):
                h_idx = i
                for idx, v in enumerate(row_str):
                    if '販' in v: t_col = idx
                    if 'No' in v: n_col = idx
                    if '効能' in v or '效果' in v: ind_col = idx
                break

        if h_idx != -1:
            rows = df.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            bar = st.progress(0)
            
            for i, (idx, row) in enumerate(rows.iterrows()):
                no_val = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_val.isdigit(): continue
                
                # 1. 抓取 Japic 資料
                jp_name = str(row.iloc[t_col]).strip()
                info = fetch_data_robust(jp_name)
                
                # 2. 翻譯適應症 (Indication)
                jp_indication = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_indication = translate_to_en(jp_indication)
                
                results.append({
                    "No.": no_val,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "Indication (EN)": en_indication,
                    "適應症(日文原文)": jp_indication
                })
                bar.progress((i+1)/len(rows))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df)
            
            # 匯出
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 12 月修復翻譯版", out.getvalue(), "PMDA_Dec_Fixed_Translated.xlsx")
