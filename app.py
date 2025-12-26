import streamlit as st
import pandas as pd
import requests
import re
import time
import os
import io

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

# --- 2. 核心查詢：KEGG 優先原則 ---
def get_kegg_standard(jp_text, log_container, is_ingredient=False):
    if not jp_text or pd.isna(jp_text): return None
    
    # 【第一片假名原則】
    match = re.search(r'^[\u30A0-\u30FF]+', str(jp_text).strip())
    if not match: return None
    
    keyword = match.group(0)
    cache_key = f"{keyword}_{'I' if is_ingredient else 'T'}"
    if cache_key in st.session_state.trans_cache:
        return st.session_state.trans_cache[cache_key]

    try:
        # 使用 REST API 搜尋
        find_url = f"https://rest.kegg.jp/find/drug/{keyword}"
        resp = requests.get(find_url, timeout=5)
        
        if resp.ok and resp.text.strip():
            drug_id = resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            info_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if info_resp.ok:
                content = info_resp.text
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content) # 商標名
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content) # 一般名
                
                res = None
                if is_ingredient:
                    # 成分名：KEGG 歐文一般名優先
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    # 商品名：KEGG 歐文商標名優先
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中 ({keyword}): `{final_res}`")
                    st.session_state.trans_cache[cache_key] = final_res
                    return final_res
    except: pass
    return None

def ms_translator(text):
    # (Azure 備援翻譯邏輯保持不變)
    if not text or pd.isna(text) or "YOUR" in AZURE_KEY: return str(text)
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY, "Ocp-Apim-Subscription-Region": AZURE_REGION, "Content-type": "application/json"}
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if r.ok: return r.json()[0]["translations"][0]["text"]
    except: pass
    return str(text)

# --- 3. 資料清理：徹底解決空行問題 ---
def clean_dataframe_robust(df_raw):
    header_idx = None
    for i, row in df_raw.iterrows():
        row_str_clean = re.sub(r'[\s\u3000\r\n\t]+', '', "".join(row.astype(str)))
        if ('成分名' in row_str_clean) and ('販' in row_str_clean):
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df = df_raw.iloc[header_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\r\n\t]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
        
    df = df.rename(columns=rename_map)

    # --- 重要：過濾空行 ---
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        # 移除完全沒資料的行，並移除轉成字串後為 "nan" 的偽資料
        df = df[df['JP_Trade'].notna() & df['JP_Ingredient'].notna()]
        df = df[
            (df['JP_Trade'].astype(str).str.strip().ne('')) & 
            (df['JP_Trade'].astype(str).str.strip().ne('nan'))
        ]
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA KEGG 優先翻譯")
    st.title("💊 PMDA 翻譯 (KEGG 優先 + 解決空行版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(io.BytesIO(uploaded_file.read()))
        for sheet_name in xls.sheet_names:
            df = clean_dataframe_robust(pd.read_excel(xls, sheet_name=sheet_name, header=None))
            
            if df is not None and not df.empty:
                st.markdown(f"---")
                st.subheader(f"📄 分頁：{sheet_name} (有效筆數: {len(df)})")
                
                results = []
                with st.status(f"處理中: {sheet_name}", expanded=True) as status:
                    log_area = st.empty()
                    prog = st.progress(0)
                    for idx, row in df.iterrows():
                        # 商品名：KEGG 為主
                        en_t = get_kegg_standard(row['JP_Trade'], log_area, is_ingredient=False)
                        src_t = "KEGG (商標名)" if en_t else "Azure"
                        if not en_t: en_t = ms_translator(row['JP_Trade'])
                        
                        # 成分名：KEGG 為主
                        en_i = get_kegg_standard(row['JP_Ingredient'], log_area, is_ingredient=True)
                        src_i = "KEGG (一般名)" if en_i else "Azure"
                        if not en_i: en_i = ms_translator(row['JP_Ingredient'])
                        
                        results.append({
                            "No.": row.get('No.', idx+1),
                            "商品名 (日)": row['JP_Trade'], "Trade Name (EN)": en_t, "來源(T)": src_t,
                            "成分名 (日)": row['JP_Ingredient'], "Ingredient (EN)": en_i, "來源(I)": src_i
                        })
                        prog.progress((idx + 1) / len(df))
                    status.update(label="完成", state="complete")
                
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
