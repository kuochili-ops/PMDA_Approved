import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 環境變數與配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# --- 1. KEGG 關鍵字極限清理 ---
def clean_for_kegg(text):
    if not text or pd.isna(text): return ""
    # 移除括號及其後的所有內容 (移除公司名、規格)
    name = re.split(r'\(|（|［|\[', str(text))[0]
    # 移除藥物常見後綴與劑型
    noise = ['錠', 'カプセル', '注', 'シリンジ', '配合', '散', '顆粒', '軟膏', '液', '點眼', '28', '21', '5mg', '10mg', '20mg']
    for n in noise:
        name = name.replace(n, '')
    return name.strip()

# --- 2. KEGG REST API 查詢 ---
def get_kegg_rest_translation(jp_name, log_container, is_ingredient=False):
    search_term = clean_for_kegg(jp_name)
    if not search_term: return None

    try:
        # Step 1: Find ID
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        log_container.write(f"🧬 KEGG 檢索: `{search_term}`")
        
        find_resp = requests.get(find_url, timeout=5)
        if find_resp.ok and find_resp.text.strip():
            # 取得第一筆匹配結果
            first_line = find_resp.text.split('\n')[0]
            drug_id = first_line.split('\t')[0].replace('dr:', '')
            
            # Step 2: Get Details
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content) # 商標名
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content) # 一般名
                
                th_val = th_match.group(1).strip() if th_match else None
                en_val = en_match.group(1).strip() if en_match else None
                
                # 判斷邏輯：成分名優先給 EN_NAME，商品名優先給 TH_NAME
                res = (en_val if en_val else th_val) if is_ingredient else (th_val if th_val else en_val)
                if res:
                    log_container.write(f"✅ KEGG 命中: `{res}`")
                    return res
    except:
        pass
    return None

# --- 3. Azure Fallback ---
def azure_fallback(text):
    if not text or pd.isna(text) or "YOUR" in AZURE_KEY: return text
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate", 
                          params=params, headers=headers, json=body, timeout=5)
        return r.json()[0]["translations"][0]["text"] if r.ok else text
    except:
        return text

# --- 4. 資料清理邏輯 ---
def process_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if '成分名' in row_str and '販' in row_str:
            header_idx = i
            break
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位對齊
    rename_map = {}
    for col in df.columns:
        c = str(col).replace('\n', '')
        if '販' in c and '名' in c: rename_map[col] = 'JP_Trade'
        elif '成' in c and '名' in c: rename_map[col] = 'JP_Ingredient'
    
    return df.rename(columns=rename_map).dropna(subset=['JP_Trade', 'JP_Ingredient'])

# --- 5. 主程式 ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯器")
st.title("💊 PMDA 日本新藥清單翻譯 (REST API 優先版)")

uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet_name in xls.sheet_names:
        raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        df = process_dataframe(raw_df)
        
        if df is None or df.empty: continue
        
        st.subheader(f"📄 分頁：{sheet_name}")
        
        # 使用 status 容器包裝，確保處理中畫面不消失
        with st.status(f"正在翻譯 {sheet_name}...", expanded=True) as status:
            log_area = st.empty()
            results = []
            
            for idx, row in df.iterrows():
                # 處理商品名
                en_t = get_kegg_rest_translation(row['JP_Trade'], log_area, False)
                t_src = "KEGG" if en_t else "Azure"
                if not en_t: en_t = azure_fallback(row['JP_Trade'])
                
                # 處理成分名
                en_i = get_kegg_rest_translation(row['JP_Ingredient'], log_area, True)
                i_src = "KEGG" if en_i else "Azure"
                if not en_i: en_i = azure_fallback(row['JP_Ingredient'])
                
                results.append({
                    "商品名 (日)": row['JP_Trade'],
                    "Trade Name (EN)": en_t,
                    "商品來源": t_src,
                    "成分名 (日)": row['JP_Ingredient'],
                    "Ingredient (EN)": en_i,
                    "成分來源": i_src
                })
                time.sleep(0.05)
            
            status.update(label=f"✅ {sheet_name} 完成", state="complete", expanded=False)
        
        # 顯示與下載
        res_df = pd.DataFrame(results)
        st.dataframe(res_df, use_container_width=True)
        csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(f"📥 下載 {sheet_name}", csv, f"{sheet_name}.csv", "text/csv")
