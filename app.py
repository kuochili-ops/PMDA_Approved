import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure Translator Setup ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 1. 極致片假名提取器 ---
def extract_clean_katakana(text, is_trade=True):
    """
    依照您的原則：
    商品名：第一個漢字前的片假名
    成分名：第一個片假名
    """
    if not text or pd.isna(text): return None
    # 移除換行與括號內容 (包含公司名、編號)
    text = str(text).replace('\n', ' ').strip()
    text = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', text)
    
    # 移除劑型干擾（這是 KEGG 搜尋最容易失敗的原因）
    text = re.sub(r'錠|散|カプセル|シロップ|液|注|配合|内容|容量|用', '', text)

    if is_trade:
        # 商品名原則：第一個片假名詞 (漢字前)
        match = re.search(r'^([ァ-ヶー・]+)', text)
    else:
        # 成分名原則：第一個片假名詞
        match = re.search(r'([ァ-ヶー・]+)', text)
    
    return match.group(1) if match else None

# --- 2. 強化版 KEGG 查詢 (帶重試機制) ---
def get_kegg_info_enhanced(jp_text, log_container, is_trade=True):
    kw = extract_clean_katakana(jp_text, is_trade)
    if not kw: return None
    
    # 若關鍵字太長，嘗試原詞與縮短詞（提高命中率）
    search_list = [kw]
    if len(kw) > 5: search_list.append(kw[:4]) 

    for search_kw in search_list:
        try:
            # Step 1: Find Drug ID
            find_url = f"https://rest.kegg.jp/find/drug/{search_kw}"
            resp = requests.get(find_url, timeout=5)
            if resp.ok and resp.text.strip():
                # 取得第一筆結果
                drug_id = resp.text.split('\n')[0].split('\t')[0]
                
                # Step 2: Get Detail
                get_url = f"https://rest.kegg.jp/get/{drug_id}"
                get_resp = requests.get(get_url, timeout=5)
                if get_resp.ok:
                    content = get_resp.text
                    
                    # 邏輯 A: 從 NAME 欄位找第一個分號後的英文
                    name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-\,\/]+)', content)
                    # 邏輯 B: 從 PRODUCTS 欄位找 (如果是商品名)
                    prod_match = re.search(r'PRODUCTS\s+([A-Za-z0-9\s\-\/]+)', content)
                    
                    res = None
                    if is_trade and prod_match: res = prod_match.group(1).strip()
                    elif name_match: res = name_match.group(1).strip()
                    
                    if res:
                        log_container.write(f"✅ KEGG 命中 `{search_kw}`: `{res}`")
                        return res
        except:
            continue
    return None

def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if not AZURE_KEY: return text
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if resp.ok: return resp.json()[0]["translations"][0]["text"]
    except: pass
    return text

# --- 3. 精確資料清理 (還原 10 筆項目的邏輯) ---
def clean_dataframe_precise(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(c) for c in row if pd.notnull(c)])
        row_str_clean = re.sub(r'[\s\u3000]+', '', row_str)
        if '販' in row_str_clean and '名' in row_str_clean:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
        
    df = df.rename(columns=rename_map)
    
    # 關鍵過濾：確保商品名不為空，且 No. 必須存在，避免抓到千行雜質
    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        df = df[df['JP_Trade'].astype(str).str.strip() != '']
        # 額外過濾：如果 No. 欄位存在，過濾掉非數字或空白的行
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主執行環境 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯器")
    st.title("💊 PMDA 列表翻譯 (KEGG API 診斷版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe_precise(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"正在搜尋 KEGG...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    jp_trade = row['JP_Trade']
                    jp_ing = row.get('JP_Ingredient', '')

                    # 執行 KEGG 檢索
                    en_trade = get_kegg_info_enhanced(jp_trade, log_area, is_trade=True)
                    en_ing = get_kegg_info_enhanced(jp_ing, log_area, is_trade=False)
                    
                    t_src = "KEGG" if en_trade else "Azure"
                    i_src = "KEGG" if en_ing else "Azure"
                    
                    if not en_trade: en_trade = ms_translator(jp_trade)
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
                    time.sleep(0.1)
                
                status.update(label="處理完成", state="complete")
            
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
