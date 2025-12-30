import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- Azure 翻譯設定 (請務必填寫) ---
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
    
    # --- 關鍵修正：只提取開頭的片假名 ---
    # 去除換行與括號內容
    raw_clean = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    # 使用 Regex 抓取開頭連續的片假名 (含長音 ─ 和點 ・)
    katakana_match = re.match(r'^[\u30A0-\u30FF\u30FB\u30FC]+', raw_clean)
    search_keyword = katakana_match.group(0) if katakana_match else raw_clean
    
    if len(search_keyword) < 2: return res

    try:
        # 第一步：搜尋 JapicID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if codes:
            jid = codes[0].zfill(8)
            res["target_id"] = jid
            
            # 第二步：抓 Trade Name (EN) - 進入 Product 頁
            rt = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}", headers=headers)
            rt.encoding = rt.apparent_encoding
            t_text = BeautifulSoup(rt.text, 'html.parser').get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # 第三步：抓 Ingredient (EN) - 進入 Med 頁
            ri = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}", headers=headers)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except: pass
    return res

st.title("🧪 PMDA 12月專用解析器 (片假名提取 + Azure 翻譯)")

f = st.file_uploader("請上傳您的原始 Excel (xlsx)", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    s_names = xl.sheet_names
    # 強制顯示所有分頁，方便您點選「承認品目12月分」
    selected_sheet = st.selectbox("請手動選擇 12 月的分頁：", s_names, index=len(s_names)-1)
    
    if st.button("🚀 開始針對 12 月執行精準解析"):
        df_raw = pd.read_excel(f, sheet_name=selected_sheet, header=None)
        
        # 動態定位欄位
        h_idx, t_col, n_col, ind_col = -1, -1, -1, -1
        for i in range(min(20, len(df_raw))):
            row_str = [str(x) for x in df_raw.iloc[i]]
            if any('販' in x for x in row_str):
                h_idx = i
                for idx, v in enumerate(row_str):
                    if '販' in v: t_col = idx
                    if 'No' in v: n_col = idx
                    if '効' in v or '效果' in v: ind_col = idx
                break

        if h_idx != -1:
            # 濾掉沒有販賣名的行
            valid_rows = df_raw.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            bar = st.progress(0)
            
            for i, (idx, row) in enumerate(valid_rows.iterrows()):
                # 只處理 No. 是數字的行
                no_str = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_str.isdigit(): continue
                
                jp_name = str(row.iloc[t_col]).strip()
                # 執行「片假名核心」搜尋
                info = fetch_data_by_katakana(jp_name)
                
                # 執行 Azure 翻譯
                jp_ind = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_ind = translate_to_en(jp_ind)
                
                results.append({
                    "No.": no_str,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "Indication (EN)": en_ind,
                    "適應症原文": jp_ind
                })
                bar.progress((i+1)/len(valid_rows))
                time.sleep(0.6) # 穩定連線
            
            final_df = pd.DataFrame(results)
            st.subheader(f"✅ {selected_sheet} 解析完成")
            st.dataframe(final_df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 下載 12 月翻譯修復版", output.getvalue(), f"PMDA_Dec_Katakana_{int(time.time())}.xlsx")
        else:
            st.error("無法在該分頁中定位到『販売名』欄位，請確認分頁內容。")
