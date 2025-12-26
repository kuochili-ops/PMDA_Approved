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
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "eastasia")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 核心解析：第一片假名原則 (KEGG 優先) ---
def get_kegg_by_first_katakana(full_text, log_container, is_ingredient=False):
    if not full_text or pd.isna(full_text) or str(full_text).lower() == 'nan':
        return None
    
    # 【原則實作】: 提取第一個片假名詞彙 (排除括號、漢字、符號)
    # 規則：只取字首開始的連續片假名
    match = re.search(r'^[\u30A0-\u30FF]+', str(full_text).strip())
    if not match:
        return None
    
    keyword = match.group(0)
    
    # 檢查快取
    cache_key = f"{keyword}_{'ing' if is_ingredient else 'trade'}"
    if cache_key in st.session_state.trans_cache:
        return st.session_state.trans_cache[cache_key]

    try:
        # Step 1: 透過片假名關鍵字尋找 KEGG ID
        find_url = f"https://rest.kegg.jp/find/drug/{keyword}"
        f_resp = requests.get(find_url, timeout=5)
        
        if f_resp.ok and f_resp.text.strip():
            # 取得第一筆藥物 ID (如 D11581)
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: 取得詳細內容
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content) # 歐文商標名
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content) # 歐文一般名
                
                result = None
                if is_ingredient:
                    # 成分名：優先找 EN_NAME (歐文一般名)
                    result = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    # 商品名：優先找 TH_NAME (歐文商標名)
                    result = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if result:
                    # 去除分號後的別名
                    final_name = result.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中 ({keyword}): `{final_name}`")
                    st.session_state.trans_cache[cache_key] = final_name
                    return final_name
    except:
        pass
    return None

# --- 3. 備援：Azure 翻譯 ---
def ms_translator(text):
    if not text or pd.isna(text) or not AZURE_KEY:
        return str(text)
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if r.ok:
            return r.json()[0]["translations"][0]["text"]
    except:
        pass
    return str(text)

# --- 4. 表格清理與標題定位 ---
def clean_dataframe(df_raw):
    h_idx = None
    for i, row in df_raw.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        # 兼容包含空格的標題
        if ('成分' in row_str) and ('販' in row_str):
            h_idx = i
            break
    
    if h_idx is None: return None
    
    df = df_raw.iloc[h_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_str = str(col).replace(' ', '').replace('\n', '')
        if '販賣名' in c_str or '販売名' in c_str: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_str: rename_map[col] = 'JP_Ingredient'
    
    df = df.rename(columns=rename_map)
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        return df.dropna(subset=['JP_Trade']).reset_index(drop=True)
    return None

# --- 5. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA KEGG 專業校正")
    st.title("💊 PMDA 翻譯校正 (第一片假名原則版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(io.BytesIO(uploaded_file.read()))
        for sheet_name in xls.sheet_names:
            df = clean_dataframe(pd.read_excel(xls, sheet_name=sheet_name, header=None))
            
            if df is not None and not df.empty:
                st.markdown(f"---")
                st.subheader(f"📄 分頁：{sheet_name}")
                
                results = []
                with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                    log_area = st.empty()
                    for idx, row in df.iterrows():
                        raw_t = row['JP_Trade']
                        raw_i = row['JP_Ingredient']
                        
                        # 1. 商品名：提取首個片假名 -> 找 KEGG TH_NAME
                        en_t = get_kegg_by_first_katakana(raw_t, log_area, is_ingredient=False)
                        t_src = "KEGG (商標名)" if en_t else "Azure"
                        if not en_t: en_t = ms_translator(raw_t)
                        
                        # 2. 成分名：提取首個片假名 -> 找 KEGG EN_NAME
                        en_i = get_kegg_by_first_katakana(raw_i, log_area, is_ingredient=True)
                        i_src = "KEGG (一般名)" if en_i else "Azure"
                        if not en_i: en_i = ms_translator(raw_i)
                        
                        results.append({
                            "商品名 (日)": raw_t, "Trade Name (EN)": en_t, "來源(T)": t_src,
                            "成分名 (日)": raw_i, "Ingredient (EN)": en_i, "來源(I)": i_src
                        })
                    status.update(label="處理完成", state="complete")
                
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(f"📥 下載 {sheet_name}", csv, f"{sheet_name}.csv", "text/csv")

if __name__ == "__main__":
    main()
