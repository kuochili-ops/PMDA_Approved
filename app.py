import streamlit as st
import pandas as pd
import requests
import re
import time
import os
import io

# --- 1. 環境配置 (Azure) ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 核心查詢函數：第一片假名 + REST API ---
def get_kegg_rest_optimized(jp_name, log_container, is_ingredient=False):
    if not jp_name or pd.isna(jp_name) or str(jp_name).lower() == 'nan':
        return None
    
    # 【執行第一片假名原則】精準提取 keyword
    match = re.search(r'^[\u30A0-\u30FF]+', str(jp_name).strip())
    if not match:
        return None
    
    keyword = match.group(0)
    cache_key = f"{keyword}_{'I' if is_ingredient else 'T'}"
    if cache_key in st.session_state.trans_cache:
        return st.session_state.trans_cache[cache_key]

    try:
        # 使用快速的 REST API 代替網頁爬蟲
        find_url = f"https://rest.kegg.jp/find/drug/{keyword}"
        resp = requests.get(find_url, timeout=5)
        
        if resp.ok and resp.text.strip():
            # 獲取第一個匹配的藥物 ID
            drug_id = resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # 獲取該 ID 的詳細資料
            info_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if info_resp.ok:
                content = info_resp.text
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content) # 歐文商標名
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content) # 歐文一般名
                
                res = None
                if is_ingredient:
                    # 成分名：優先找 EN_NAME (歐文一般名)
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    # 商品名：優先找 TH_NAME (歐文商標名)
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中 ({keyword}): `{final_res}`")
                    st.session_state.trans_cache[cache_key] = final_res
                    return final_res
    except:
        pass
    return None

# --- 3. 備援翻譯：Azure Translator ---
def ms_translator(text):
    if not text or pd.isna(text) or "YOUR" in AZURE_KEY: return str(text)
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if r.ok: return r.json()[0]["translations"][0]["text"]
    except: pass
    return str(text)

# --- 4. 資料清理邏輯 (參考舊代碼並強化) ---
def clean_dataframe_robust(df_raw):
    # 尋找標題行
    header_idx = None
    for i, row in df_raw.iterrows():
        row_str = "".join(row.astype(str))
        row_str_clean = re.sub(r'[\s\u3000\r\n\t]+', '', row_str)
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
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        return df.dropna(subset=['JP_Trade']).reset_index(drop=True)
    return None

# --- 5. 主介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("💊 PMDA 日本新藥翻譯 (第一片假名 + REST API 版)")
    
    uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx', 'xls'])
    if uploaded_file:
        xls = pd.ExcelFile(io.BytesIO(uploaded_file.read()))
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe_robust(raw_df)
            
            if df is None or df.empty: continue
            
            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name} ({len(df)} 筆)")
            
            results = []
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                
                for idx, row in df.iterrows():
                    # 1. 商品名處理
                    jp_t = row['JP_Trade']
                    en_t = get_kegg_rest_optimized(jp_t, log_area, is_ingredient=False)
                    src_t = "KEGG" if en_t else "Azure"
                    if not en_t: en_t = ms_translator(jp_t)
                    
                    # 2. 成分名處理
                    jp_i = row['JP_Ingredient']
                    en_i = get_kegg_rest_optimized(jp_i, log_area, is_ingredient=True)
                    src_i = "KEGG" if en_i else "Azure"
                    if not en_i: en_i = ms_translator(jp_i)
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "商品名 (日)": jp_t, "Trade Name (EN)": en_t, "來源(T)": src_t,
                        "成分名 (日)": jp_i, "Ingredient (EN)": en_i, "來源(I)": src_i
                    })
                    progress_bar.progress((idx + 1) / len(df))
                
                status.update(label=f"✅ {sheet_name} 完成", state="complete")
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(label=f"📥 下載 {sheet_name} 結果", data=csv, file_name=f"PMDA_{sheet_name}.csv", mime='text/csv', key=f"dl_{sheet_name}")

if __name__ == "__main__":
    main()
