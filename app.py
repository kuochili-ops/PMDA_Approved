import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 安裝額外套件建議：pip install pykakasi (如果環境允許) ---
# 這裡先使用正則表達式做基礎處理

# --- Azure Translator Setup (保持不變) ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 擴充：成分名過濾器 ---
def clean_drug_name_for_search(name):
    """更精準地清理藥名以提高 KEGG 命中率"""
    if not name: return ""
    # 移除劑型、規格、日局等干擾文字
    name = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(name))
    name = re.sub(r'日局|水和物|エステル|塩酸塩|マレイン酸塩', '', name)
    return name.strip()

# --- 核心查詢函數：KEGG 優先 ---
def get_kegg_drug_info(jp_name, log_container, is_ingredient=False):
    if not jp_name or pd.isna(jp_name):
        return None
    
    search_term = clean_drug_name_for_search(jp_name)
    
    # 如果清理後太短，直接跳過
    if len(search_term) < 2: return None
    
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={search_term}"
    
    try:
        log_container.write(f"🔍 KEGG 檢索中: `{search_term}`")
        resp = requests.get(search_url, timeout=10)
        if resp.ok:
            # 優先找精確匹配的連結
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                drug_resp = requests.get(drug_url, timeout=10)
                
                if drug_resp.ok:
                    # 商品名優先抓「欧文商標名」
                    trade_match = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    # 成分名優先抓「英文一般名」
                    generic_match = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    
                    res_trade = trade_match.group(1).strip() if trade_match else None
                    res_generic = generic_match.group(1).strip() if generic_match else None
                    
                    # 邏輯分流：如果是查成分，優先給一般名
                    if is_ingredient:
                        result = res_generic if res_generic else res_trade
                    else:
                        result = res_trade if res_trade else res_generic
                        
                    if result:
                        log_container.write(f"✅ KEGG 命中: `{result}`")
                        return result
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {e}")
    
    return None

def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if "YOUR" in AZURE_KEY: return text
    
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            res = resp.json()[0]["translations"][0]["text"]
            # 修正常見翻譯錯誤（例如 Azure 有時會把藥名翻成奇怪的動詞）
            return res
    except:
        pass
    return text

# --- (find_header_row 與 clean_dataframe 保持您的版本) ---
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
    st.title("🇯🇵 PMDA 日本新藥列表翻譯 (精準改良版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx', 'xls'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            if df is None or df.empty: continue
                
            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name}")
            
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    # 1. 處理商品名 (Trade Name)
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_drug_info(jp_trade, log_area, is_ingredient=False)
                    trade_src = "KEGG"
                    if not en_trade:
                        en_trade = ms_translator(jp_trade)
                        trade_src = "Azure"
                    
                    # 2. 處理成分名 (Ingredient)
                    jp_ing = row['JP_Ingredient']
                    en_ing = get_kegg_drug_info(jp_ing, log_area, is_ingredient=True)
                    ing_src = "KEGG"
                    if not en_ing:
                        en_ing = ms_translator(jp_ing)
                        ing_src = "Azure"
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "販賣名 (日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "來源": trade_src,
                        "成分名 (日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "來源 ": ing_src
                    })
                    progress_bar.progress((idx + 1) / len(df))
                    time.sleep(0.1) # 縮短延遲提高效率
                
                status.update(label=f"✅ {sheet_name} 翻譯完成！", state="complete", expanded=False)
            
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
