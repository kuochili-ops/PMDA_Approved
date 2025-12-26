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

# --- 核心邏輯：KEGG 專用關鍵字提取 ---
def get_pure_katakana(text, is_trade=True):
    if not text or pd.isna(text): return None
    text = str(text).replace('\n', '').strip()
    # 移除劑型干擾詞
    text = re.sub(r'錠|散|カプセル|シロップ|液|注|配合|内容|容量|用', '', text)
    # 移除括號
    text = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', text)
    
    if is_trade:
        # 商品名：取第一個漢字前的片假名
        match = re.search(r'^([ァ-ヶー・]+)', text)
    else:
        # 成分名：取第一個片假名
        match = re.search(r'([ァ-ヶー・]+)', text)
    
    return match.group(1) if match else None

def get_kegg_info(jp_text, log_container, is_trade=True):
    kw = get_pure_katakana(jp_text, is_trade)
    if not kw: return None
    
    try:
        # 1. 使用 find 取得 ID
        find_url = f"https://rest.kegg.jp/find/drug/{kw}"
        resp = requests.get(find_url, timeout=5)
        if resp.ok and resp.text.strip():
            first_entry = resp.text.split('\n')[0]
            drug_id = first_entry.split('\t')[0]
            
            # 2. 使用 get 取得詳細 Entry
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            if get_resp.ok:
                content = get_resp.text
                # 從 NAME 行提取：通常格式為 "NAME 日文名; 英文名"
                # 我們找第一個分號之後的英文字母
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-\,\/]+)', content)
                if name_match:
                    res = name_match.group(1).strip()
                    log_container.write(f"✅ KEGG ({'商品' if is_trade else '成分'}): `{kw}` -> `{res}`")
                    return res
    except:
        pass
    return None

def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
    if "YOUR" in AZURE_KEY: return f"[未配置] {text}"
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

# --- 資料清理：恢復您原始的高精準邏輯 ---
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
    # 關鍵：必須包含這兩個欄位，且刪除空行，避免項目膨脹
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        # 過濾掉商品名或成分名為空的行，並確保 No. 是數字或有效內容
        valid_df = df.dropna(subset=['JP_Trade', 'JP_Ingredient'])
        return valid_df[valid_df['JP_Trade'].astype(str).str.strip() != ''].reset_index(drop=True)
    return None

# --- 主執行邏輯 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
    st.title("🇯🇵 PMDA 日本新藥列表翻譯 (精準還原版)")
    
    uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx', 'xls'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty:
                continue
                
            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"處理中...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    # 1. 商品名翻譯 (KEGG 優先)
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_info(jp_trade, log_area, is_trade=True)
                    t_src = "KEGG"
                    if not en_trade:
                        en_trade = ms_translator(jp_trade)
                        t_src = "Azure"
                    
                    # 2. 成分名翻譯 (KEGG 優先)
                    jp_ing = row['JP_Ingredient']
                    en_ing = get_kegg_info(jp_ing, log_area, is_trade=False)
                    i_src = "KEGG"
                    if not en_ing:
                        en_ing = ms_translator(jp_ing)
                        i_src = "Azure"
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "商品名 (日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "商標來源": t_src,
                        "成分名 (日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "成分來源": i_src
                    })
                    progress_bar.progress((idx + 1) / len(df))
                    time.sleep(0.1) 
                
                status.update(label=f"✅ {sheet_name} 完成", state="complete", expanded=False)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(label=f"📥 下載 {sheet_name}", data=csv, file_name=f"{sheet_name}.csv", key=sheet_name)

if __name__ == "__main__":
    main()
