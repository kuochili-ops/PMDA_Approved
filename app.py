import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 1. 環境配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 針對「スリンダ」優化的 KEGG REST API ---
def get_kegg_rest_final(jp_name, log_container, is_ingredient=False):
    if not jp_name or pd.isna(jp_name): return None
    
    # 【核心優化】: 徹底清洗名稱
    # 範例： "スリンダ錠28(あすか製薬㈱、9010401018375)" -> "スリンダ"
    # 1. 移除括號及其後所有內容
    clean_term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    # 2. 移除數字、劑型、公司相關後綴
    clean_term = re.sub(r'錠|カプセル|注|シリンジ|配合|\d+|分|末|％|%|株式会社|製薬|㈱', '', clean_term).strip()
    
    if not clean_term or len(clean_term) < 2: return None
    if clean_term in st.session_state.trans_cache:
        return st.session_state.trans_cache[clean_term]

    try:
        # 使用 REST API 搜尋 ID
        find_url = f"https://rest.kegg.jp/find/drug/{clean_term}"
        f_resp = requests.get(find_url, timeout=5)
        
        if f_resp.ok and f_resp.text.strip():
            # 取得首選藥物 ID (例如 D12345)
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # 獲取詳細資料 (包含 TH_NAME / EN_NAME)
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                # 商品名優先找 TH_NAME (歐文商標名)，成分名找 EN_NAME
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                res = None
                if is_ingredient:
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    # 針對商品名，優先提取 TH_NAME
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0] # 拿第一個主名稱
                    log_container.write(f"✅ KEGG 校正成功: `{clean_term}` -> `{final_res}`")
                    st.session_state.trans_cache[clean_term] = final_res
                    return final_res
    except Exception:
        pass
    
    return None

# --- 3. Azure 翻譯 ---
def ms_translator(text):
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        return r.json()[0]["translations"][0]["text"]
    except:
        return text

# --- 4. 主介面邏輯 (省略重複的 clean_dataframe 函數以精簡) ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯校正器")
    st.title("💊 PMDA 專業翻譯 (Slinda/スリンダ校正強化版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            # 讀取並偵測標題 (同前版本)
            df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            # ... (此處使用與您版本一致的 clean_dataframe) ...
            
            # 處理每一行
            results = []
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                for _, row in df.iterrows():
                    jp_t = row['JP_Trade'] # 販賣名
                    jp_i = row['JP_Ingredient'] # 成分名
                    
                    # 執行 KEGG REST 校正
                    en_t = get_kegg_rest_final(jp_t, log_area, is_ingredient=False)
                    t_src = "KEGG" if en_t else "Azure"
                    if not en_t: en_t = ms_translator(jp_t)
                    
                    en_i = get_kegg_rest_final(jp_i, log_area, is_ingredient=True)
                    i_src = "KEGG" if en_i else "Azure"
                    if not en_i: en_i = ms_translator(jp_i)
                    
                    results.append({
                        "商品名(日)": jp_t, "Trade Name (EN)": en_t, "來源(T)": t_src,
                        "成分名(日)": jp_i, "Ingredient (EN)": en_i, "來源(I)": i_src
                    })
                status.update(label="完成", state="complete")
            st.dataframe(pd.DataFrame(results))

if __name__ == "__main__":
    main()
