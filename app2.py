import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- 1. 設定區域：請填入您的 Azure 資訊 ---
# 建議將這些資訊設定在 Streamlit 的 Secrets 中以維護安全
AZURE_KEY = "您的_Azure_Key"
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com"
AZURE_REGION = "您的區域(例如: japaneast 或 global)"

# --- 2. 核心功能函式 ---

def translate_to_en(text):
    """
    使用 Azure Translator API 將日文翻譯成英文
    """
    if pd.isna(text) or not str(text).strip():
        return ""
    
    # 清洗：移除內容中的換行符號，這常是造成 API 解析錯誤的原因
    clean_text = str(text).replace('\n', ' ').strip()
    
    path = '/translate?api-version=3.0&from=ja&to=en'
    constructed_url = AZURE_ENDPOINT + path
    
    headers = {
        'Ocp-Apim-Subscription-Key': AZURE_KEY,
        'Ocp-Apim-Subscription-Region': AZURE_REGION,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(time.time())
    }
    
    body = [{'text': clean_text}]
    
    try:
        response = requests.post(constructed_url, headers=headers, json=body, timeout=15)
        # 如果失敗，回傳狀態碼以便排查問題
        if response.status_code != 200:
            return f"[API 錯誤 {response.status_code}]"
        
        res_data = response.json()
        return res_data[0]['translations'][0]['text']
    except Exception as e:
        return f"[連線失敗: {str(e)}]"

def fetch_japic_data(trade_jp_full):
    """
    提取片假名核心藥名並從 KEGG/Japic 抓取英文商標與成分
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    # 邏輯：只取日文商品名前面的片假名部分作為關鍵字
    raw_clean = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
    katakana_match = re.match(r'^[\u30A0-\u30FF\u30FB\u30FC]+', raw_clean)
    search_keyword = katakana_match.group(0) if katakana_match else raw_clean
    
    if len(search_keyword) < 2: return res

    try:
        # 第一階段：搜尋 JapicID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if codes:
            jid = codes[0].zfill(8)
            res["target_id"] = jid
            
            # 第二階段：抓取英文商標 (Trade Name)
            rt = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}", headers=headers)
            rt.encoding = rt.apparent_encoding
            soup_t = BeautifulSoup(rt.text, 'html.parser')
            t_text = soup_t.get_text(separator=" ", strip=True)
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # 第三階段：抓取英文成分 (Ingredient)
            ri = requests.get(f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}", headers=headers)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except: pass
    return res

# --- 3. Streamlit UI 介面 ---

st.set_page_config(layout="wide", page_title="PMDA 解析翻譯器")
st.title("💊 PMDA 萬能解析系統")
st.markdown("""
- **片假名精準搜尋**：自動提取商品名首段片假名，優化 12 月新藥命中率。
- **分類識別**：自動判斷『新藥』(承認) 與 『變更』(一変、二変)。
- **適應症翻譯**：串接 Azure Translator 將『効能・効果等』轉為英文。
""")

f = st.file_uploader("請上傳原始承認品目 Excel (xlsx)", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    selected_sheet = st.selectbox("請選擇要解析的分頁 (如: 承認品目12月分)", xl.sheet_names, index=len(xl.sheet_names)-1)
    
    if st.button("開始解析"):
        df_raw = pd.read_excel(f, sheet_name=selected_sheet, header=None)
        
        # 欄位動態定位邏輯
        h_idx, t_col, n_col, ind_col, status_col = -1, -1, -1, -1, -1
        for i in range(min(20, len(df_raw))):
            row_str = [str(x) for x in df_raw.iloc[i]]
            if any('販' in x for x in row_str):
                h_idx = i
                for idx, v in enumerate(row_str):
                    v_clean = str(v).replace(' ', '').replace('\n', '')
                    if '販' in v_clean: t_col = idx
                    if 'No' in v_clean: n_col = idx
                    if '効能' in v_clean or '效果' in v_clean: ind_col = idx
                    if '承認' in v_clean and idx != t_col: status_col = idx
                break

        if h_idx != -1:
            rows = df_raw.iloc[h_idx+1:].dropna(subset=[t_col])
            results = []
            progress_bar = st.progress(0)
            
            for i, (idx, row) in enumerate(rows.iterrows()):
                # 過濾非數據行 (檢查 No 欄位是否為數字)
                no_str = str(row.iloc[n_col]).split('.')[0] if n_col != -1 else ""
                if not no_str.isdigit(): continue
                
                # A. 識別新藥/變更
                raw_status = str(row.iloc[status_col]).strip() if status_col != -1 else ""
                # 如果包含 "承" 且包含 "認" 則為新藥，其餘為變更
                status_label = "新藥" if ("承" in raw_status and "認" in raw_status) else "變更"
                
                # B. 抓取 Japic 核心資料
                jp_name = str(row.iloc[t_col]).strip()
                info = fetch_japic_data(jp_name)
                
                # C. 適應症翻譯
                jp_indication = str(row.iloc[ind_col]).strip() if ind_col != -1 else ""
                en_indication = translate_to_en(jp_indication)
                
                results.append({
                    "No.": no_str,
                    "分類": status_label,
                    "日文販賣名": jp_name.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "適應症 (EN)": en_indication,
                    "適應症原文 (日)": jp_indication
                })
                
                progress_bar.progress((i+1)/len(rows))
                time.sleep(0.5) # 防止請求過快觸發 API 限制
            
            final_df = pd.DataFrame(results)
            st.success(f"『{selected_sheet}』解析完成！")
            st.dataframe(final_df, use_container_width=True)
            
            # 匯出 Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 下載解析成果報告", output.getvalue(), f"PMDA_Report_{selected_sheet}.xlsx")
        else:
            st.error("無法辨識標題列，請確認 Excel 格式。")
