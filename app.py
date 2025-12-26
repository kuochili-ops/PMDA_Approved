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

# --- 核心邏輯：依照您的規則提取片假名關鍵字 ---
def get_katakana_prefix(text):
    """
    從字串一開始辨識片假名，直到遇到第一個非片假名（漢字、數字、符號）停止。
    用於精確對應 KEGG 的歐文商標名或一般名。
    """
    if not text or pd.isna(text):
        return None
    
    text = str(text).strip()
    # 正則表達式：從開頭(^)開始匹配連續的片假名、長音符、中點
    # [ァ-ヶー・] 分別代表片假名、長音符、中點
    match = re.search(r'^([ァ-ヶー・]+)', text)
    
    if match:
        return match.group(1)
    return None

def get_kegg_info(jp_text, log_container, is_trade=True):
    # 使用您的原則：抓取開頭的純片假名作為關鍵字
    kw = get_katakana_prefix(jp_text)
    if not kw:
        return None
    
    try:
        # Step 1: 搜尋 Drug ID
        # 例如: https://rest.kegg.jp/find/drug/タミフル
        find_url = f"https://rest.kegg.jp/find/drug/{kw}"
        resp = requests.get(find_url, timeout=5)
        
        if resp.ok and resp.text.strip():
            # 取搜尋結果第一筆
            first_entry = resp.text.split('\n')[0]
            drug_id = first_entry.split('\t')[0]
            
            # Step 2: 獲取詳細 Entry 資料
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                
                # 針對商品名搜尋 PRODUCTS 欄位
                if is_trade:
                    prod_match = re.search(r'PRODUCTS\s+([A-Za-z0-9\s\-\/]+)', content)
                    if prod_match:
                        log_container.write(f"✅ KEGG 商品名命中: `{kw}`")
                        return prod_match.group(1).strip()
                
                # 針對成分名或備案，搜尋 NAME 欄位中的英文（第一個分號後）
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-\,\/]+)', content)
                if name_match:
                    log_container.write(f"✅ KEGG 成分名命中: `{kw}`")
                    return name_match.group(1).strip()
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

# --- 精確資料清理：防止 10 筆變 1000 筆 ---
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
    
    # 欄位重新命名
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)

    # 嚴格過濾邏輯：1. 商品名不為空 2. No. 必須是有效數字
    if 'JP_Trade' in df.columns:
        # 去除全空白列
        df = df.dropna(subset=['JP_Trade', 'JP_Ingredient'], how='all')
        # 確保 No 欄位是數字，這能濾掉表格底部的備註文字
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("💊 PMDA 日本新藥列表翻譯 (KEGG 片假名精確版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty:
                continue
                
            st.markdown(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"處理中...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    jp_trade = row['JP_Trade']
                    jp_ing = row.get('JP_Ingredient', '')

                    # 依照您的原則搜尋 KEGG
                    en_trade = get_kegg_info(jp_trade, log_area, is_trade=True)
                    en_ing = get_kegg_info(jp_ing, log_area, is_trade=False)
                    
                    # 來源標記
                    t_src = "KEGG" if en_trade else "Azure"
                    i_src = "KEGG" if en_ing else "Azure"
                    
                    # Azure 保底
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
                
                status.update(label="✅ 該分頁處理完成", state="complete", expanded=False)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(label=f"📥 下載 {sheet_name}", data=csv, file_name=f"{sheet_name}.csv", key=sheet_name)

if __name__ == "__main__":
    main()
