import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure API 配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# 初始化快取 (避免重複查同樣的藥)
if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 1. 穩定版 KEGG REST API ---
def get_kegg_rest(jp_name, is_ingredient=False):
    """使用 REST API 替代爬蟲模式"""
    if not jp_name or pd.isna(jp_name): return None
    
    # 清理名稱：移除括號內容，如 (5mg) 或 [配合錠]
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21', '', term).strip()
    
    if term in st.session_state.trans_cache:
        return st.session_state.trans_cache[term]

    try:
        # Step 1: Find ID (使用 REST API)
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        f_resp = requests.get(find_url, timeout=5)
        if f_resp.ok and f_resp.text.strip():
            # 取第一筆回傳的 ID
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: Get Info
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th = re.search(r'TH_NAME\s+(.*?)\n', content)
                en = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                # 取得結果
                res = (en.group(1) if en else th.group(1)) if is_ingredient else (th.group(1) if th else en.group(1))
                if res:
                    st.session_state.trans_cache[term] = res.strip()
                    return res.strip()
    except:
        pass
    return None

# --- 2. Azure 翻譯 ---
def ms_translator(text):
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=ja&to=en", 
                          headers=headers, json=body, timeout=5)
        return r.json()[0]["translations"][0]["text"]
    except:
        return text

# --- 3. 欄位偵測邏輯 (保留您原有的 find_header_row) ---
def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if ('成分名' in row_str or '成' in row_str) and '販' in row_str:
            return i
    return None

# --- 主執行介面 ---
st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
st.title("💊 PMDA 穩定版 (REST API + 快取)")

uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet_name in xls.sheet_names:
        raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        h_idx = find_header_row(raw_df)
        
        if h_idx is None: continue
        
        # 清理 DataFrame
        df = raw_df.iloc[h_idx:].copy()
        df.columns = df.iloc[0]
        df = df[1:].reset_index(drop=True)
        
        # 定位欄位
        t_col = next((c for c in df.columns if '販' in str(c) and '名' in str(c)), None)
        i_col = next((c for c in df.columns if '成' in str(c) and '名' in str(c)), None)
        
        if not t_col or not i_col: continue

        st.subheader(f"分頁：{sheet_name}")
        
        with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
            results = []
            progress = st.progress(0)
            
            for idx, row in df.iterrows():
                jp_t, jp_i = str(row[t_col]), str(row[i_col])
                if jp_t == "nan": continue

                # 校正商品名
                en_t = get_kegg_rest(jp_t, is_ingredient=False)
                t_src = "KEGG" if en_t else "Azure"
                if not en_t: en_t = ms_translator(jp_t)
                
                # 校正成分名
                en_i = get_kegg_rest(jp_i, is_ingredient=True)
                i_src = "KEGG" if en_i else "Azure"
                if not en_i: en_i = ms_translator(jp_i)
                
                results.append({
                    "販賣名 (日)": jp_t, "Trade Name (EN)": en_t, "來源(T)": t_src,
                    "成分名 (日)": jp_i, "Ingredient (EN)": en_i, "來源(I)": i_src
                })
                progress.progress((idx + 1) / len(df))
                
            status.update(label="✅ 完成", state="complete")
        
        st.dataframe(pd.DataFrame(results), use_container_width=True)
