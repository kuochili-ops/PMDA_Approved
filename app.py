import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 設定區域 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 1. 關鍵字提取強化版 ---
def extract_keyword(text, is_trade_name=True):
    if not text or pd.isna(text): return None
    
    # 移除括號、換行
    text = str(text).replace('\n', ' ').strip()
    text = re.sub(r'［.*?］|（.*?）|\(.*?\)|\d+.*$', '', text)
    
    if is_trade_name:
        # 商品名原則：漢字前的片假名
        # 抓取第一串片假名，遇到漢字就停止
        match = re.search(r'^([ァ-ヶー・]+)', text)
    else:
        # 成分名原則：第一個片假名詞
        match = re.search(r'([ァ-ヶー・]+)', text)
    
    return match.group(1) if match else None

# --- 2. KEGG REST API 強化版 ---
def get_kegg_drug_info(jp_raw_text, log_container, is_trade_name=True):
    search_term = extract_keyword(jp_raw_text, is_trade_name)
    if not search_term: return None
    
    # 嘗試清單：原詞、以及縮短後的詞（避免劑型干擾）
    attempts = [search_term]
    if len(search_term) > 4:
        attempts.append(search_term[:4])

    for kw in attempts:
        try:
            log_container.write(f"📡 KEGG 檢索關鍵字: `{kw}`")
            # Step 1: Find ID
            find_url = f"https://rest.kegg.jp/find/drug/{kw}"
            resp = requests.get(find_url, timeout=5)
            
            if resp.ok and resp.text.strip():
                # 取第一筆結果的 ID
                drug_id = resp.text.split('\n')[0].split('\t')[0]
                
                # Step 2: Get Details
                get_url = f"https://rest.kegg.jp/get/{drug_id}"
                get_resp = requests.get(get_url, timeout=5)
                
                if get_resp.ok:
                    content = get_resp.text
                    
                    if is_trade_name:
                        # 優先從 PRODUCTS 找 (英文商標名)
                        # 格式通常為: PRODUCTS    Name (Company); Name2 (Company2)
                        prod_match = re.search(r'PRODUCTS\s+([A-Za-z0-9\s\-\/]+)', content)
                        if prod_match:
                            return prod_match.group(1).strip()
                        
                        # 次優先：從 NAME 找括號內的英文
                        name_match = re.search(r'NAME\s+[^\n]*?\((.*?)\)', content)
                        if name_match and re.search(r'[A-Za-z]', name_match.group(1)):
                            return name_match.group(1).strip()
                    else:
                        # 成分名：從 NAME 找分號後的英文，或括號外的英文
                        name_line = re.search(r'NAME\s+(.*)', content)
                        if name_line:
                            # 尋找第一組純英文字串
                            parts = re.split(r'[;,\(\)]', name_line.group(1))
                            for p in parts:
                                clean_p = p.strip()
                                if re.search(r'^[A-Za-z\s\-]{3,}$', clean_p):
                                    return clean_p
            
            time.sleep(0.1) # 稍微緩衝
        except:
            continue
            
    return None

# --- 3. Azure 翻譯保底 ---
def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if not AZURE_KEY: return f"[未配置 API] {text}"
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if resp.ok:
            return resp.json()[0]["translations"][0]["text"]
    except:
        pass
    return text

# --- 4. 資料處理 ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(c) for c in row if pd.notnull(c)])
        if '販' in row_str and '名' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c = re.sub(r'\s+', '', str(col))
        if '販' in c and '名' in c: rename_map[col] = 'JP_Trade'
        elif '成' in c and '名' in c: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c: rename_map[col] = 'No.'
        
    df = df.rename(columns=rename_map)
    if 'JP_Trade' in df.columns:
        return df.dropna(subset=['JP_Trade']).reset_index(drop=True)
    return None

# --- 5. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯器 (強化版)")
    st.title("💊 PMDA 藥品翻譯 (KEGG REST API 優先)")

    

    uploaded_file = st.file_uploader("請上傳 PMDA 新藥列表 Excel", type=['xlsx', 'xls'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"### 📄 分頁: {sheet_name}")
            
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    # 商品名處理
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_drug_info(jp_trade, log_area, is_trade_name=True)
                    t_src = "KEGG" if en_trade else "Azure"
                    if not en_trade: en_trade = ms_translator(jp_trade)
                    
                    # 成分名處理
                    jp_ing = row.get('JP_Ingredient', '')
                    en_ing = get_kegg_drug_info(jp_ing, log_area, is_trade_name=False)
                    i_src = "KEGG" if en_ing else "Azure"
                    if not en_ing: en_ing = ms_translator(jp_ing)
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "商品名(日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "來源(T)": t_src,
                        "成分名(日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "來源(I)": i_src
                    })
                    progress_bar.progress((idx + 1) / len(df))
                
                status.update(label="處理完成", state="complete")
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(f"📥 下載 {sheet_name}", csv, f"{sheet_name}.csv", "text/csv")

if __name__ == "__main__":
    main()
