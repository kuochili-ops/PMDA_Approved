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

# --- 1. 依照您的原則：提取開頭連續片假名 ---
def get_katakana_prefix(text):
    """
    辨識欄位一開始的片假名，直到非片假名為止。
    """
    if not text or pd.isna(text): return None
    text = str(text).strip()
    # 規則：^ 表示從頭開始，[ァ-ヶー・]+ 表示連續的片假名、長音、中點
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. KEGG REST API 深度查詢 (修正編碼與路徑) ---
def get_kegg_info(jp_text, log_container, is_trade=True):
    # 提取您的關鍵字（如：スリンダ）
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    try:
        # 步驟 A: Find Drug ID
        # 使用 URL 編碼確保片假名能被 API 識別
        encoded_kw = quote(kw)
        find_url = f"https://rest.kegg.jp/find/drug/{encoded_kw}"
        
        resp = requests.get(find_url, timeout=10)
        if not resp.ok or not resp.text.strip():
            log_container.write(f"❌ KEGG 找不到關鍵字: `{kw}`")
            return None
            
        # 取得第一筆 Entry ID (例如 dr:D03917)
        first_line = resp.text.split('\n')[0]
        drug_id = first_line.split('\t')[0] # 這裡會拿到 'drug:D03917'
        
        # 步驟 B: Get Entry Details
        get_url = f"https://rest.kegg.jp/get/{drug_id}"
        get_resp = requests.get(get_url, timeout=10)
        
        if get_resp.ok:
            content = get_resp.text
            
            # 商品名邏輯：從 PRODUCTS 欄位提取英文
            if is_trade:
                # 匹配 PRODUCTS 後方的英文，通常在括號前
                prod_match = re.search(r'PRODUCTS\s+([A-Za-z0-9\s\-\/]+)', content)
                if prod_match:
                    res = prod_match.group(1).strip()
                    log_container.write(f"✅ KEGG 商品名命中: `{kw}` -> `{res}`")
                    return res
            
            # 成分名邏輯：從 NAME 欄位找第一個分號後的英文字串
            # 格式範例: NAME    Sulindac (JP18/USP/INN); Clinoril (TN)
            lines = content.split('\n')
            for line in lines:
                if line.startswith('NAME'):
                    # 抓取分號後的內容
                    parts = line.split(';')
                    target_part = parts[1] if len(parts) > 1 else parts[0]
                    # 提取純英文字母的部分 (過濾掉 JP18/USP 等)
                    en_match = re.search(r'([A-Za-z][A-Za-z\s\-\/]{2,})', target_part)
                    if en_match:
                        res = en_match.group(1).strip()
                        log_container.write(f"✅ KEGG 成分名命中: `{kw}` -> `{res}`")
                        return res
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {str(e)}")
    
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

# --- 3. 精確資料清理 (維持 10 筆項目) ---
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
        df = df.dropna(subset=['JP_Trade'])
        if 'No.' in df.columns:
            # 濾除 Excel 底部雜質，只留數字編號行
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主執行邏輯 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯器")
    st.title("💊 PMDA 日本新藥清單翻譯 (KEGG REST API 修正版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel", type=['xlsx'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"處理中...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    jp_trade = row['JP_Trade']
                    jp_ing = row.get('JP_Ingredient', '')

                    # 執行翻譯邏輯
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
                
                status.update(label="✅ 處理完成", state="complete")
            
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
