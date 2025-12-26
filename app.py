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
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 核心邏輯：提取規則 ---

def extract_keyword(text, is_trade_name=True):
    """
    實作規則：
    1. 商品名：第一個片假名詞 (漢字前)
    2. 成分名：第一個片假名詞
    """
    if not text or pd.isna(text):
        return None
    
    # 清理掉常見的雜質符號，但保留片假名
    text = str(text).replace('\n', ' ').strip()
    text = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', text)

    if is_trade_name:
        # 尋找開頭的片假名，直到遇到漢字或空格為止
        match = re.search(r'^([ァ-ヶー・]+)', text)
    else:
        # 尋找第一個出現的片假名詞組
        match = re.search(r'([ァ-ヶー・]+)', text)
    
    return match.group(1) if match else None

# --- 核心查詢函數：KEGG REST API ---

def get_kegg_drug_info(jp_raw_text, log_container, is_trade_name=True):
    """
    使用 KEGG REST API (find & get) 進行檢索
    """
    search_term = extract_keyword(jp_raw_text, is_trade_name)
    if not search_term:
        return None
    
    try:
        # 步驟 1: 使用 find 尋找藥品 ID
        # https://rest.kegg.jp/find/drug/keyword
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        resp = requests.get(find_url, timeout=10)
        
        if resp.ok and resp.text.strip():
            # 取結果的第一行第一欄 (dr:Dxxxxx)
            first_line = resp.text.split('\n')[0]
            if not first_line: return None
            drug_id = first_line.split('\t')[0]
            
            # 步驟 2: 使用 get 獲取該 ID 的完整資訊
            # https://rest.kegg.jp/get/dr:Dxxxxx
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=10)
            
            if get_resp.ok:
                content = get_resp.text
                
                if is_trade_name:
                    # 商品名規則：在 PRODUCTS 欄位中尋找 (英文名)
                    # 範例: PRODUCTS    Tamiflu (Roche, Chugai); ...
                    prod_match = re.search(r'PRODUCTS\s+.*?([A-Za-z\s\-,\./]+)\s*\(', content)
                    if prod_match:
                        return prod_match.group(1).strip()
                    # 備案：從 NAME 欄位找逗號後的英文
                    name_match = re.search(r'NAME\s+[^;]+?;\s*([^;\n]+)', content)
                    if name_match and re.search(r'[A-Za-z]', name_match.group(1)):
                        return name_match.group(1).strip()
                else:
                    # 成分名規則：從 NAME 欄位找分號或逗號後的英文
                    # 範例: NAME    Oseltamivir phosphate; ...
                    name_match = re.search(r'NAME\s+[^;]+?;\s*([^;\n]+)', content)
                    if name_match:
                        en_name = name_match.group(1).strip()
                        # 去除可能的括號備註
                        en_name = re.sub(r'\(.*?\)', '', en_name).strip()
                        return en_name

        log_container.write(f"ℹ️ KEGG API 未命中關鍵字: `{search_term}`")
    except Exception as e:
        log_container.write(f"⚠️ KEGG API 異常: {e}")
    
    return None

def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if "YOUR" in AZURE_KEY or AZURE_KEY == "": return f"[未配置 API] {text}"
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            return resp.json()[0]["translations"][0]["text"]
    except:
        pass
    return text

# --- 資料清理與標題偵測 ---

def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        row_str_clean = re.sub(r'[\s\u3000\r\n\t]+', '', row_str)
        if ('成分名' in row_str_clean or '成' in row_str_clean) and '販' in row_str_clean:
            return i
    return None

def clean_dataframe(df):
    header_idx = find_header_row(df)
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\r\n\t]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
        
    df = df.rename(columns=rename_map)
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        return df.dropna(subset=['JP_Trade', 'JP_Ingredient']).reset_index(drop=True)
    return None

# --- 主執行邏輯 ---

def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("🇯🇵 PMDA 日本新藥列表翻譯 (KEGG REST API 版)")
    st.info("本版本優先從 KEGG REST API 獲取官方歐文商標名與一般名。")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx', 'xls'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty:
                continue
                
            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    # 1. 處理商品名
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_drug_info(jp_trade, log_area, is_trade_name=True)
                    trade_src = "KEGG API"
                    if not en_trade:
                        en_trade = ms_translator(jp_trade)
                        trade_src = "Azure"
                    
                    # 2. 處理成分名
                    jp_ing = row['JP_Ingredient']
                    en_ing = get_kegg_drug_info(jp_ing, log_area, is_trade_name=False)
                    ing_src = "KEGG API"
                    if not en_ing:
                        en_ing = ms_translator(jp_ing)
                        ing_src = "Azure"
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "販賣名 (日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "商標來源": trade_src,
                        "成分名 (日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "成分來源": ing_src
                    })
                    
                    progress_bar.progress((idx + 1) / len(df))
                    time.sleep(0.2) # REST API 限制較少，速度可加快
                
                status.update(label=f"✅ {sheet_name} 處理完成！", state="complete", expanded=False)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                label=f"📥 下載 {sheet_name} 翻譯結果",
                data=csv,
                file_name=f"PMDA_{sheet_name}_Translated.csv",
                mime='text/csv',
                key=f"dl_{sheet_name}"
            )

if __name__ == "__main__":
    main()
