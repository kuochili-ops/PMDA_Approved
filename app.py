import streamlit as st
import pandas as pd
import requests
import re
import time
import os
import io

# --- 1. 環境與快取配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "eastasia")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 核心：提取第一片假名並查詢 KEGG ---
def get_kegg_by_rules(full_text, log_container, is_ingredient=False):
    if not full_text or pd.isna(full_text) or str(full_text).lower() == 'nan':
        return None
    
    # 【執行第一片假名原則】
    # 使用正則表達式 ^[\u30A0-\u30FF]+ 確保只抓取從字首開始的連續片假名
    # 例如： "スリンダ錠28(あすか製薬...)" -> 匹配結果: "スリンダ"
    match = re.search(r'^[\u30A0-\u30FF]+', str(full_text).strip())
    if not match:
        return None
    
    keyword = match.group(0)
    
    # 檢查快取以節省網路開銷
    cache_key = f"{keyword}_{'ING' if is_ingredient else 'TRADE'}"
    if cache_key in st.session_state.trans_cache:
        return st.session_state.trans_cache[cache_key]

    try:
        # Step 1: 搜尋 KEGG ID
        find_url = f"https://rest.kegg.jp/find/drug/{keyword}"
        f_resp = requests.get(find_url, timeout=5) # 縮短 timeout 避免網路慢時卡死
        
        if f_resp.ok and f_resp.text.strip():
            # 取得第一條結果的 ID
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: 取得詳細欄位
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th_name = re.search(r'TH_NAME\s+(.*?)\n', content) # 歐文商標名
                en_name = re.search(r'EN_NAME\s+(.*?)\n', content) # 歐文一般名
                
                target = None
                if is_ingredient:
                    # 成分名：優先找 EN_NAME (歐文一般名)
                    target = en_name.group(1) if en_name else (th_name.group(1) if th_name else None)
                else:
                    # 商品名：優先找 TH_NAME (歐文商標名)
                    target = th_name.group(1) if th_name else (en_name.group(1) if en_name else None)
                
                if target:
                    # 僅取主名（過濾掉分號後的內容）
                    final_name = target.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中 ({keyword}): `{final_name}`")
                    st.session_state.trans_cache[cache_key] = final_name
                    return final_name
    except Exception as e:
        log_container.write(f"⚠️ KEGG 連線異常: {keyword}")
        
    return None

# --- 3. 備援翻譯：Azure ---
def ms_translator(text):
    if not text or pd.isna(text) or not AZURE_KEY: return str(text)
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

# --- 4. 表格清理 ---
def clean_pmda_df(df_raw):
    # 定位標題行：包含「成分」與「販」的行
    header_idx = None
    for i, row in df_raw.iterrows():
        row_str = "".join(row.astype(str))
        if '成分' in row_str and '販' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df = df_raw.iloc[header_idx:].copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # 欄位重新映射
    new_cols = {}
    for c in df.columns:
        c_clean = str(c).replace(" ", "").replace("\n", "")
        if '販売名' in c_clean or '販賣名' in c_clean: new_cols[c] = 'T_NAME'
        elif '成分名' in c_clean: new_cols[c] = 'I_NAME'
    
    df = df.rename(columns=new_cols)
    if 'T_NAME' in df.columns and 'I_NAME' in df.columns:
        return df.dropna(subset=['T_NAME']).reset_index(drop=True)
    return None

# --- 5. 主程式介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA KEGG 校正工具")
    st.title("💊 PMDA 專業翻譯 (第一片假名精準校正版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(io.BytesIO(uploaded_file.read()))
        for sheet_name in xls.sheet_names:
            df = clean_pmda_df(pd.read_excel(xls, sheet_name=sheet_name, header=None))
            
            if df is not None and not df.empty:
                st.markdown(f"---")
                st.subheader(f"📄 分頁：{sheet_name} (有效資料: {len(df)} 筆)")
                
                results = []
                with st.status(f"正在分析 {sheet_name}...", expanded=True) as status:
                    log_area = st.empty()
                    for idx, row in df.iterrows():
                        raw_t = row['T_NAME']
                        raw_i = row['I_NAME']
                        
                        # 商品名校正
                        en_t = get_kegg_by_rules(raw_t, log_area, is_ingredient=False)
                        t_src = "KEGG (歐文商標)" if en_t else "Azure (音譯)"
                        if not en_t: en_t = ms_translator(raw_t)
                        
                        # 成分名校正
                        en_i = get_kegg_by_rules(raw_i, log_area, is_ingredient=True)
                        i_src = "KEGG (歐文一般)" if en_i else "Azure (音譯)"
                        if not en_i: en_i = ms_translator(raw_i)
                        
                        results.append({
                            "商品名 (日)": raw_t, "Trade Name (EN)": en_t, "來源(T)": t_src,
                            "成分名 (日)": raw_i, "Ingredient (EN)": en_i, "來源(I)": i_src
                        })
                    status.update(label="分頁處理完成", state="complete")
                
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                # CSV 下載
                csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(f"📥 下載 {sheet_name} 結果", csv, f"{sheet_name}.csv", "text/csv")

if __name__ == "__main__":
    main()
