import streamlit as st
import pandas as pd
import requests
import re
import time
import os
from urllib.parse import quote

# --- Azure Translator Setup ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "")
    AZURE_REGION = os.environ.get("AZURE_REGION", "")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 1. 依照原則：提取開頭連續片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    # 規則：從頭開始辨識片假名(含長音與中點)，直到遇到非片假名字元停止
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. KEGG REST API 深度查詢 (含 URL 編碼處理) ---
def get_kegg_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    try:
        # 關鍵修正：必須對片假名進行 URL 編碼
        encoded_kw = quote(kw)
        find_url = f"https://rest.kegg.jp/find/drug/{encoded_kw}"
        
        log_container.write(f"📡 檢索中: `{kw}`")
        resp = requests.get(find_url, timeout=10)
        
        if not resp.ok or not resp.text.strip():
            return None
            
        # 取得第一個搜尋結果 ID
        first_line = resp.text.split('\n')[0]
        drug_id = first_line.split('\t')[0]
        
        # 獲取詳細資料
        get_url = f"https://rest.kegg.jp/get/{drug_id}"
        get_resp = requests.get(get_url, timeout=10)
        
        if get_resp.ok:
            content = get_resp.text
            
            # 優先找 PRODUCTS 區塊 (商品名專用)
            if is_trade:
                prod_match = re.search(r'PRODUCTS\s+([A-Za-z0-9\s\-\/]+)', content)
                if prod_match:
                    return prod_match.group(1).strip()
            
            # 找 NAME 區塊中的英文 (分號後)
            # 格式：NAME 日文名; 英文名
            lines = content.split('\n')
            for line in lines:
                if line.startswith('NAME'):
                    parts = line.split(';')
                    if len(parts) > 1:
                        # 提取包含英文字母的部分，並去除括號
                        en_part = parts[1].strip()
                        en_part = re.sub(r'\(.*?\)', '', en_part).strip()
                        if re.search(r'[A-Za-z]', en_part):
                            return en_part
    except:
        pass
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

# --- 3. 精確資料清理 (防止項目膨脹) ---
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
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        # 過濾空行
        df = df.dropna(subset=['JP_Trade'])
        # 核心：透過 No. 欄位過濾掉表格外雜訊
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯器")
    st.title("💊 PMDA 日本新藥翻譯 (KEGG URL 編碼修正版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"### 📄 分頁：{sheet_name}")
            
            with st.status(f"處理中...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    jp_trade = row['JP_Trade']
                    jp_ing = row.get('JP_Ingredient', '')

                    # 執行翻譯
                    en_trade = get_kegg_info(jp_trade, log_area, is_trade=True)
                    en_ing = get_kegg_info(jp_ing, log_area, is_trade=False)
                    
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
                
                status.update(label="✅ 完成", state="complete")
            
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
