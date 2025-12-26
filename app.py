import streamlit as st
import pandas as pd
import requests
import re
import time
import os
import io

# --- 1. 環境與快取 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "eastasia")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 核心：第一片假名原則與 KEGG 查詢 ---
def get_kegg_by_rules(full_text, log_container, is_ingredient=False):
    if not full_text or pd.isna(full_text): return None
    
    # 提取第一個片假名詞彙 (排除括號與後續公司名)
    match = re.search(r'^[\u30A0-\u30FF]+', str(full_text).strip())
    if not match: return None
    
    keyword = match.group(0)
    cache_key = f"{keyword}_{'I' if is_ingredient else 'T'}"
    if cache_key in st.session_state.trans_cache:
        return st.session_state.trans_cache[cache_key]

    try:
        # 搜尋藥物 ID
        find_url = f"https://rest.kegg.jp/find/drug/{keyword}"
        f_resp = requests.get(find_url, timeout=5)
        
        if f_resp.ok and f_resp.text.strip():
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            # 獲取詳細資料
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th_name = re.search(r'TH_NAME\s+(.*?)\n', content) # 歐文商標名
                en_name = re.search(r'EN_NAME\s+(.*?)\n', content) # 歐文一般名
                
                target = None
                if is_ingredient:
                    target = en_name.group(1) if en_name else (th_name.group(1) if th_name else None)
                else:
                    target = th_name.group(1) if th_name else (en_name.group(1) if en_name else None)
                
                if target:
                    final_name = target.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中 ({keyword}): `{final_name}`")
                    st.session_state.trans_cache[cache_key] = final_name
                    return final_name
    except: pass
    return None

# --- 3. 標題列自動偵測 (強化版) ---
def clean_pmda_df(df_raw):
    header_idx = None
    # 掃描前 20 行，尋找包含關鍵字的一列
    for i, row in df_raw.head(20).iterrows():
        row_str = "".join(row.astype(str))
        # 移除空格與換行，增加匹配率
        clean_row_str = re.sub(r'\s+', '', row_str)
        if ('成分名' in clean_row_str) and ('販' in clean_row_str):
            header_idx = i
            break
    
    if header_idx is None:
        st.error("❌ 找不到有效的標題列（需包含『成分名』與『販売名』）。請檢查 Excel 格式。")
        return None
    
    df = df_raw.iloc[header_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # 欄位映射：容錯空格與換行
    new_cols = {}
    for c in df.columns:
        c_clean = re.sub(r'\s+', '', str(c))
        if '販売名' in c_clean or '販賣名' in c_clean: new_cols[c] = 'T_NAME'
        elif '成分名' in c_clean: new_cols[c] = 'I_NAME'
    
    df = df.rename(columns=new_cols)
    if 'T_NAME' in df.columns and 'I_NAME' in df.columns:
        return df.dropna(subset=['T_NAME']).reset_index(drop=True)
    return None

# --- 4. 主執行介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("💊 PMDA 翻譯校正 (Slinda/スリンダ優化版)")
    
    uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx'])
    
    if uploaded_file:
        # 使用 BytesIO 避免讀取逾時
        xls = pd.ExcelFile(io.BytesIO(uploaded_file.read()))
        
        for sheet_name in xls.sheet_names:
            df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_pmda_df(df_raw)
            
            if df is not None and not df.empty:
                st.markdown(f"---")
                st.subheader(f"📄 分頁：{sheet_name} ({len(df)} 筆)")
                
                results = []
                # 使用進度條與狀態列
                with st.status(f"正在分析 {sheet_name}...", expanded=True) as status:
                    log_area = st.empty()
                    prog_bar = st.progress(0)
                    
                    for idx, row in df.iterrows():
                        raw_t = row['T_NAME']
                        raw_i = row['I_NAME']
                        
                        # 執行第一片假名原則
                        en_t = get_kegg_by_rules(raw_t, log_area, is_ingredient=False)
                        if not en_t: en_t = "[Azure] " + str(raw_t) # 暫代翻譯
                        
                        en_i = get_kegg_by_rules(raw_i, log_area, is_ingredient=True)
                        if not en_i: en_i = "[Azure] " + str(raw_i) # 暫代翻譯
                        
                        results.append({
                            "商品名 (日)": raw_t, "Trade Name (EN)": en_t,
                            "成分名 (日)": raw_i, "Ingredient (EN)": en_i
                        })
                        prog_bar.progress((idx + 1) / len(df))
                    
                    status.update(label=f"✅ {sheet_name} 處理完成", state="complete")
                
                st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.info(f"跳過不符格式的分頁：{sheet_name}")

if __name__ == "__main__":
    main()
