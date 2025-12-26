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

# --- 核心查詢函數：KEGG 優先 ---

def extract_keyword(text, is_trade_name=True):
    """
    根據規則提取關鍵字：
    1. 商品名：第一個片假名詞（漢字前）
    2. 成分名：第一個片假名詞
    """
    if not text or pd.isna(text):
        return None
    
    # 清理掉括號與換行符號
    text = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(text))
    text = text.replace('\n', ' ').strip()

    if is_trade_name:
        # 尋找漢字之前的片假名詞組
        # [ァ-ヶー]+ 匹配連續的片假名
        match = re.search(r'^([ァ-ヶー]+)', text)
    else:
        # 尋找第一個出現的片假名詞組
        match = re.search(r'([ァ-ヶー]+)', text)
    
    return match.group(1) if match else text[:10] # 若無片假名則取前10碼兜底

def get_kegg_drug_info(jp_raw_text, log_container, is_trade_name=True):
    """
    使用 KEGG API 檢索。
    is_trade_name=True: 搜尋歐文商標名
    is_trade_name=False: 搜尋歐文一般名 (成分)
    """
    search_term = extract_keyword(jp_raw_text, is_trade_name)
    
    if not search_term:
        return None
    
    # 這裡使用 KEGG Medicus 的搜尋網址
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={search_term}"
    
    try:
        log_container.write(f"🔍 KEGG 檢索關鍵字: `{search_term}` ({'商品' if is_trade_name else '成分'})")
        resp = requests.get(search_url, timeout=10)
        if resp.ok:
            # 提取 JAPIC Code (進入詳細頁面)
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                drug_resp = requests.get(drug_url, timeout=10)
                
                if drug_resp.ok:
                    # 根據類型抓取不同欄位
                    if is_trade_name:
                        # 抓取 欧文商標名
                        match = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    else:
                        # 抓取 英文一般名 (用於成分名)
                        match = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    
                    if match:
                        result = match.group(1).strip()
                        # 去除可能的 HTML tag
                        result = re.sub(r'<.*?>', '', result)
                        log_container.write(f"✅ KEGG 命中: `{result}`")
                        return result
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {e}")
    
    return None

def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if "YOUR" in AZURE_KEY: return f"[未配置 API] {text}"
    
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
    st.title("🇯🇵 PMDA 日本新藥列表翻譯 (KEGG API 關鍵字強化版)")
    
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
                    # 1. 處理商品名 (專門找 Trade Name)
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_drug_info(jp_trade, log_area, is_trade_name=True)
                    trade_src = "KEGG"
                    if not en_trade:
                        en_trade = ms_translator(jp_trade)
                        trade_src = "Azure"
                    
                    # 2. 處理成分名 (專門找 Generic Name)
                    jp_ing = row['JP_Ingredient']
                    en_ing = get_kegg_drug_info(jp_ing, log_area, is_trade_name=False)
                    ing_src = "KEGG"
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
                    time.sleep(0.5) # 適度延遲避免請求過頻繁
                
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
