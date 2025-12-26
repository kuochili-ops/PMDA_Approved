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
    # 這裡建議保留空字串或環境變數，避免程式因 API Key 缺失而崩潰
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "eastasia")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# 初始化快取，確保重新整理時不會丟失已查詢數據
if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 核心校正函數：KEGG REST API ---
def get_kegg_rest_final(jp_name, log_container, is_ingredient=False):
    if not jp_name or pd.isna(jp_name) or str(jp_name).lower() == 'nan':
        return None
    
    # 清洗名稱：移除括號、劑型、商號
    clean_term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    clean_term = re.sub(r'錠|カプセル|注|シリンジ|配合|\d+|分|末|％|%|株式会社|製薬|㈱|アステラス|外用|液', '', clean_term).strip()
    
    if not clean_term or len(clean_term) < 2:
        return None
    if clean_term in st.session_state.trans_cache:
        return st.session_state.trans_cache[clean_term]

    try:
        # 使用 REST API 搜尋
        find_url = f"https://rest.kegg.jp/find/drug/{clean_term}"
        f_resp = requests.get(find_url, timeout=5)
        
        if f_resp.ok and f_resp.text.strip():
            # 取得首選藥物 ID
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # 獲取詳細資料
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                res = None
                if is_ingredient:
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 校正: `{clean_term}` -> `{final_res}`")
                    st.session_state.trans_cache[clean_term] = final_res
                    return final_res
    except:
        pass
    return None

# --- 3. 備援翻譯：Azure ---
def ms_translator(text):
    if not text or pd.isna(text) or str(text).lower() == 'nan':
        return ""
    if not AZURE_KEY:
        return f"[未設定Key] {text}"
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        if r.ok:
            return r.json()[0]["translations"][0]["text"]
    except:
        pass
    return str(text)

# --- 4. 表格清理函數 ---
def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if ('成分名' in row_str or '成分' in row_str) and ('販賣名' in row_str or '販' in row_str):
            return i
    return None

def clean_dataframe(df_raw):
    h_idx = find_header_row(df_raw)
    if h_idx is None:
        return None
    
    # 複製資料避免警告
    df = df_raw.iloc[h_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_str = str(col)
        if '販' in c_str and '名' in c_str: rename_map[col] = 'JP_Trade'
        elif '成' in c_str and '名' in c_str: rename_map[col] = 'JP_Ingredient'
    
    df = df.rename(columns=rename_map)
    # 確保關鍵欄位存在且不為空
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        return df.dropna(subset=['JP_Trade', 'JP_Ingredient']).reset_index(drop=True)
    return None

# --- 5. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯校正器")
    st.title("💊 PMDA 專業翻譯 (修復版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx'])
    
    if uploaded_file:
        file_bytes = uploaded_file.read()
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        
        for sheet_name in xls.sheet_names:
            raw_df_data = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df_data) # 這裡會回傳處理後的 df 或 None
            
            # 關鍵修正：確保 df 存在且不為空，才進入處理迴圈
            if df is not None and not df.empty:
                st.markdown(f"---")
                st.subheader(f"📄 分頁：{sheet_name} ({len(df)} 筆)")
                
                results = []
                with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                    log_area = st.empty()
                    progress_bar = st.progress(0)
                    
                    for idx, row in df.iterrows():
                        jp_t = row['JP_Trade']
                        jp_i = row['JP_Ingredient']
                        
                        # 處理商品名
                        en_t = get_kegg_rest_final(jp_t, log_area, is_ingredient=False)
                        t_src = "KEGG" if en_t else "Azure"
                        if not en_t: en_t = ms_translator(jp_t)
                        
                        # 處理成分名
                        en_i = get_kegg_rest_final(jp_i, log_area, is_ingredient=True)
                        i_src = "KEGG" if en_i else "Azure"
                        if not en_i: en_i = ms_translator(jp_i)
                        
                        results.append({
                            "商品名 (日)": jp_t,
                            "Trade Name (EN)": en_t,
                            "來源(T)": t_src,
                            "成分名 (日)": jp_i,
                            "Ingredient (EN)": en_i,
                            "來源(I)": i_src
                        })
                        progress_bar.progress((idx + 1) / len(df))
                    
                    status.update(label=f"✅ {sheet_name} 完成", state="complete")
                
                if results:
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    
                    csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button(
                        label=f"📥 下載 {sheet_name} 翻譯結果",
                        data=csv,
                        file_name=f"PMDA_{sheet_name}.csv",
                        mime='text/csv',
                        key=f"dl_{sheet_name}"
                    )
            else:
                # 如果該分頁沒有可解析的資料，安靜地跳過
                continue

if __name__ == "__main__":
    main()
