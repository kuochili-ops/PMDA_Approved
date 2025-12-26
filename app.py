import streamlit as st
import pandas as pd
import requests
import re
import time
import os
from io import StringIO

# --- Azure Translator Setup ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except KeyError:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_AZURE_KEY_HERE")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_AZURE_REGION_HERE")

AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- KEGG API 整合函數 ---
def get_kegg_drug_info(jp_name):
    """
    根據 KEGG REST API 規範獲取藥品資訊。
    1. 使用 find 接口尋找 D-number (Drug ID)
    2. 使用 get 接口獲取詳細資訊
    """
    try:
        # 步驟 1: 尋找藥品 ID (kegg find drug)
        # https://rest.kegg.jp/find/drug/keyword
        find_url = f"https://rest.kegg.jp/find/drug/{jp_name}"
        find_resp = requests.get(find_url, timeout=10)
        
        if not find_resp.ok or not find_resp.text.strip():
            return None, None
        
        # 取得第一個匹配的 D-number (例如 D01234)
        first_line = find_resp.text.split('\n')[0]
        drug_id = first_line.split('\t')[0].replace('dr:', '')
        
        # 步驟 2: 獲取詳細資料 (kegg get)
        # https://rest.kegg.jp/get/drug_id
        get_url = f"https://rest.kegg.jp/get/{drug_id}"
        get_resp = requests.get(get_url, timeout=10)
        
        if not get_resp.ok:
            return None, None
        
        content = get_resp.text
        trade_name_en = ""
        generic_name_en = ""
        
        # 使用正則表達式提取歐文商標名 (TH_NAME)
        # 格式通常為: TH_NAME     Name_En (Trade_Name)
        th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
        if th_match:
            trade_name_en = th_match.group(1).strip()
            
        # 使用正則表達式提取英文通用名 (EN_NAME)
        en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
        if en_match:
            generic_name_en = en_match.group(1).strip()
            
        return trade_name_en, generic_name_en

    except Exception as e:
        print(f"KEGG API Error for {jp_name}: {e}")
        return None, None

# --- Azure Translator 函數 ---
def ms_translator(text, from_lang="ja"):
    if not text or str(text).strip() == "" or "YOUR_AZURE" in AZURE_KEY:
        return text
        
    body = [{"text": text}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    try:
        resp = requests.post(AZURE_ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            return resp.json()[0]["translations"][0]["text"]
    except:
        pass
    return f"[Trans] {text}"

# --- 資料清理與標題偵測 ---
def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if ('成分名' in row_str or '成' in row_str) and ('名' in row_str and '販' in row_str):
            return i
    return None

def clean_dataframe(df):
    header_idx = find_header_row(df)
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 統一列名
    rename_dict = {}
    for col in df.columns:
        c = str(col)
        if '販' in c and '名' in c: rename_dict[col] = 'JP_Trade_Name'
        if '成' in c and '名' in c: rename_dict[col] = 'JP_Ingredient'
    
    df = df.rename(columns=rename_dict)
    # 過濾無效行
    if 'JP_Trade_Name' in df.columns:
        df = df[df['JP_Trade_Name'].notnull() & (df['JP_Trade_Name'].astype(str).strip() != "")]
    return df

# --- 核心處理邏輯 ---
def process_data(df):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(df)

    for idx, row in df.iterrows():
        jp_trade = str(row.get('JP_Trade_Name', '')).split('\n')[0] # 移除換行符（有時包含公司名）
        jp_ingredient = str(row.get('JP_Ingredient', ''))
        
        status_text.text(f"正在處理 ({idx+1}/{total}): {jp_trade}")
        
        # 1. 嘗試從 KEGG 獲取專業資訊
        kegg_trade, kegg_ing = get_kegg_drug_info(jp_trade)
        
        # 商標名處理
        if kegg_trade:
            final_trade = kegg_trade
            trade_src = "KEGG API"
        else:
            final_trade = ms_translator(jp_trade)
            trade_src = "Azure AI"
            
        # 成分名處理 (優先用 KEGG)
        if kegg_ing:
            final_ing = kegg_ing
            ing_src = "KEGG API"
        else:
            final_ing = ms_translator(jp_ingredient)
            ing_src = "Azure AI"
            
        results.append({
            "日文販賣名": jp_trade,
            "英文商標名 (English Trade Name)": final_trade,
            "商標來源": trade_src,
            "日文成分名": jp_ingredient,
            "英文成分名 (Generic Name)": final_ing,
            "成分來源": ing_src
        })
        
        progress_bar.progress((idx + 1) / total)
        time.sleep(0.2) # 防止頻率過高

    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(results)

# --- Streamlit UI ---
def main():
    st.set_page_config(page_title="PMDA 藥品清單翻譯器", layout="wide")
    st.title("💊 PMDA 日本新藥清單自動翻譯 (KEGG API 版)")
    
    with st.sidebar:
        st.header("設定")
        if "YOUR_AZURE" in AZURE_KEY:
            st.error("Azure Key 未設定，將使用標註模式。")
    
    file = st.file_uploader("上傳 PMDA Excel", type=['xlsx'])
    
    if file:
        xls = pd.ExcelFile(file)
        sheets = xls.sheet_names
        selected_sheet = st.selectbox("請選擇分頁", sheets)
        
        raw_df = pd.read_excel(xls, sheet_name=selected_sheet, header=None)
        clean_df = clean_dataframe(raw_df)
        
        if clean_df is not None:
            st.write(f"檢測到 {len(clean_df)} 筆藥品資料")
            if st.button("開始翻譯"):
                final_df = process_data(clean_df)
                st.subheader("翻譯結果")
                st.dataframe(final_df, use_container_width=True)
                
                csv = final_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 下載翻譯後的 CSV", csv, "translated_drugs.csv", "text/csv")
        else:
            st.error("無法解析此分頁的表格結構，請確認是否有『成分名』與『販賣名』標題列。")

if __name__ == "__main__":
    main()
