import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- 1. 設定區域：您的 Azure 翻譯資訊已填入 ---
AZURE_KEY = "9JDF24qrsW8rXiYmChS17yEPyNRI96nNXXqEKn5CyI6ql6iYcTOFJQQJ99BLAC3pKaRXJ3w3AAAbACOGVYVU"
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com"
AZURE_REGION = "eastasia"

# --- 2. 核心功能函式 ---

def translate_to_en(text):
    """
    使用 Azure Translator API 翻譯，並強化編碼處理以防止 latin-1 錯誤
    """
    if pd.isna(text) or not str(text).strip():
        return ""
    
    # 清理文本：移除換行並確保為字串
    clean_text = str(text).replace('\n', ' ').strip()
    
    # 確保端點與路徑正確
    base_url = AZURE_ENDPOINT.strip().rstrip('/')
    url = f"{base_url}/translate?api-version=3.0&from=ja&to=en"
    
    # 關鍵修復：嚴格清理 Headers，確保 Key/Region 沒有不可見字元，並宣告 UTF-8
    headers = {
        'Ocp-Apim-Subscription-Key': str(AZURE_KEY).strip(),
        'Ocp-Apim-Subscription-Region': str(AZURE_REGION).strip(),
        'Content-type': 'application/json; charset=utf-8' 
    }
    
    try:
        # 使用 json=[...] 會自動處理 UTF-8 序列化
        response = requests.post(url, headers=headers, json=[{'text': clean_text}], timeout=15)
        
        if response.status_code != 200:
            return f"[API 錯誤 {response.status_code}: {response.text}]"
            
        res_data = response.json()
        return res_data[0]['translations'][0]['text']
    except Exception as e:
        return f"[連線失敗: {str(e)}]"

def fetch_japic_data(trade_jp_full):
    """
    提取片假名核心藥名並搜尋 KEGG/Japic 資料 (針對12月新藥優化)
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    # 只取商品名前段連續的片假名（排除劑型、規格與公司名）
    raw_clean = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    katakana_match = re.match(r'^[\u30A0-\u30FF\u30FB\u30FC]+', raw_clean)
    search_keyword = katakana_match.group(0) if katakana_match else raw_clean
    
    if len(search_keyword) < 2: return res

    try:
        # 1. 搜尋 JapicID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if codes:
            jid = codes[0].zfill(8)
            res["target_id"] = jid
            
            # 2. 抓取英文商標名 (Trade Name)
            rt = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}", headers=headers)
            rt.encoding = rt.apparent_encoding
            t_soup = BeautifulSoup(rt.text, 'html.parser')
            t_text = t_soup.get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # 3. 抓取英文成分名 (Ingredient)
            ri = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}", headers=headers)
            ri.encoding = ri.apparent_encoding
            i_soup = BeautifulSoup(ri.text, 'html.parser')
            th = i_soup.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except: pass
    return res

# --- 3. Streamlit UI ---

st.set_page_config(layout="wide", page_title="𓃥 白 六 PMDA 上市品解析工具")
st.title("𓃥 白 六 PMDA 上市品解析工具")

f = st.file_uploader("請上傳 PMDA 原始 Excel 檔案 (.xlsx)", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    selected_sheet = st.selectbox("請選擇解析分頁：", xl.sheet_names, index=len(xl.sheet_names)-1)
    
    if st.button("開始解析"):
        df_raw = pd.read_excel(f, sheet_name=selected_sheet, header=None)
        
        # 欄位自動定位
        h_idx, t_col, n_col, ind_col, status_col = -1, -1, -1, -1, -1
        for i in range(min(20, len(df_raw))):
            row_vals = [str(x) for x in df_raw.iloc[i]]
            if any('販' in x for x in row_vals):
                h_idx = i
                for idx, v in enumerate(row_vals):
                    v_clean = str(v).replace(' ', '').replace('\n', '')
                    if '販' in v_clean: t_col = idx
                    if 'No' in v_clean: n_col = idx
                    if '効能' in v_clean or '效果' in v_clean: ind_col = idx
                    if '承認' in v_clean and idx != t_col: status_col = idx
                break

        if h_idx != -1:
            valid_rows = df_raw.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            bar = st.progress(0)
            
            for i, (idx, row) in enumerate(valid_rows.iterrows()):
                # 過濾非數據行 (確認 No 欄位)
                no_raw = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_raw.isdigit(): continue
                
                # A. 識別新藥/變更 (承認欄位)
                raw_stat = str(row.iloc[status_col]).strip() if status_col != -1 else ""
                status_label = "新藥" if ("承" in raw_stat and "認" in raw_stat) else "變更"
                
                # B. 片假名核心搜尋
                jp_name = str(row.iloc[t_col]).strip()
                info = fetch_japic_data(jp_name)
                
                # C. 適應症翻譯
                jp_ind = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_ind = translate_to_en(jp_ind)
                
                results.append({
                    "No.": no_raw,
                    "分類": status_label,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "適應症 (EN)": en_ind,
                    "適應症原文 (日)": jp_ind
                })
                bar.progress((i+1)/len(valid_rows))
                time.sleep(0.5)
            
            final_df = pd.DataFrame(results)
            st.success(f"『{selected_sheet}』解析翻譯完成！")
            st.dataframe(final_df, use_container_width=True)
            
            # 下載 Excel 成果
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 下載解析成果報告", out.getvalue(), f"白六_PMDA_Report_{selected_sheet}.xlsx")
        else:
            st.error("定位失敗，找不到含有『販売名』的標題列。")
