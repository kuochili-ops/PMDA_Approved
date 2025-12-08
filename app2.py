import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure Translator Setup ---
# Assumes AZURE_KEY and AZURE_REGION are defined in Streamlit secrets.toml
AZURE_KEY = st.secrets["AZURE_KEY"]
AZURE_REGION = st.secrets["AZURE_REGION"]
endpoint = "https://api.cognitive.microsofttranslator.com/translate"
headers = {
    "Ocp-Apim-Subscription-Key": AZURE_KEY,
    "Ocp-Apim-Subscription-Region": AZURE_REGION,
    "Content-type": "application/json"
}

# --- KEGG Function ---
def get_kegg_trade_name_and_japic(jp_name):
    """
    Attempts to find the KEGG English Trade Name (欧文商標名) and JAPIC code 
    for a given Japanese drug name by scraping the KEGG search page.
    """
    url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={jp_name}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            # 1. Extract JAPIC Code (japic_code=XXXXX)
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            japic_code = japic_match.group(1) if japic_match else None
            
            # 2. Extract English Trade Name (欧文商標名)
            # Using a more flexible, non-greedy pattern (.*?)(?=<) to capture up to the next tag
            trade_match = re.search(r'欧文商標名</span>\s*:\s*(.*?)(?=<)', resp.text, re.DOTALL)
            trade_name = trade_match.group(1).strip() if trade_match else ""
            
            return japic_code, trade_name
    except Exception:
        pass
    return None, ""

# --- Translator Function ---
def ms_translator(text, from_lang="ja"):
    """
    Uses Azure Translator to translate Japanese text to English.
    """
    body = [{"text": text}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(endpoint, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            data = resp.json()
            return data[0]["translations"][0]["text"]
    except Exception:
        pass
    return ""

# --- Data Cleaning and Header Detection Functions ---
def find_header_row(df):
    """
    Attempts to find the header row in the PMDA Excel sheet based on key Japanese terms 
    ('名', '成', '販').
    """
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        row_str_clean = re.sub(r'[\s\u3000\r\n\t]+', '', row_str)
        
        # Heuristic 1: Look for two '名', one '成' (Ingredient), and one '販' (Sale/Trade)
        if row_str_clean.count('名') >= 2 and '成' in row_str_clean and '販' in row_str_clean:
            return i
        
        # Heuristic 2: Look for explicit column names
        if ('成分名' in row_str_clean or ('成' in row_str_clean and '分' in row_str_clean and '名' in row_str_clean)) \
           and ('販売名' in row_str_clean or '販賣名' in row_str_clean or ('販' in row_str_clean and '売' in row_str_clean and '名' in row_str_clean)):
            return i
    return None

def is_number(val):
    """
    Checks if a value can be converted to a number, handling Japanese full-width digits.
    """
    try:
        val_str = str(val).strip()
        # Convert full-width numbers to half-width
        val_str = val_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        float(val_str)
        return True
    except:
        return False

def clean_dataframe(df):
    """
    Renames columns, filters out invalid rows, and cleans the DataFrame.
    """
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    
    rename_map = {}
    for col in df.columns:
        col_str = str(col)
        col_clean = re.sub(r'[\s\u3000\r\n\t]+', '', col_str)
        col_clean = re.sub(r'（.*?）|\(.*?\)', '', col_clean) # Remove parentheses
        
        if '販' in col_clean and '名' in col_clean:
            rename_map[col] = '販賣名/公司 (日文)'
        elif '成' in col_clean and '名' in col_clean:
            rename_map[col] = '成分名 (日文)'
        elif 'No' in col_clean:
            rename_map[col] = 'No.'
            
    df = df.rename(columns=rename_map)
    
    # Filter rows based on the presence of key columns
    if {'No.', '販賣名/公司 (日文)', '成分名 (日文)'}.issubset(df.columns):
        df = df[
            df['No.'].apply(is_number) &
            df['販賣名/公司 (日文)'].astype(str).str.strip().ne('') &
            df['成分名 (日文)'].astype(str).str.strip().ne('')
        ]
    elif '成分名 (日文)' in df.columns:
        df = df[df['成分名 (日文)'].notnull() & (df['成分名 (日文)'].astype(str).str.strip() != '')]
    else:
        # If necessary columns are not found, return empty DataFrame
        df = pd.DataFrame()
        
    if not df.empty:
        # Final clean-up of empty rows/columns
        df = df.dropna(how='all')
        df = df[~(df.applymap(lambda x: str(x).strip() == '').all(axis=1))]
        df = df.reset_index(drop=True)
        
    return df

# --- Main Processing Functions ---
def save_sheets_to_csv_auto_header(uploaded_file):
    """
    Processes all sheets in the uploaded Excel file, detects headers automatically, 
    cleans the data, and saves valid sheets as temporary CSV files.
    """
    xls = pd.ExcelFile(uploaded_file)
    sheet_map = {} # Maps month name to (temp_csv_name, total_rows, processed_rows)
    
    for sheet_name in xls.sheet_names:
        # 1. Read raw data without header to detect the actual header row
        raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        header_row = find_header_row(raw_df)
        
        if header_row is None:
            continue
            
        # 2. Re-read data using the detected header row
        df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
        
        # 3. Clean and normalize the DataFrame
        df = clean_dataframe(df)
        
        if df is None or df.empty:
            continue
            
        # 4. Determine the file name (Month)
        month_match = re.search(r'(\d+)月', sheet_name)
        if not month_match:
            for col in df.columns:
                m = re.search(r'(\d+)月', str(col))
                if m:
                    month_match = m
                    break
        if month_match:
            month = month_match.group(1) + "月"
        else:
            month = sheet_name
            
        # 5. Save as a temporary CSV
        csv_name = f"{month}.csv"
        df.to_csv(csv_name, index=False, encoding="utf-8")
        sheet_map[month] = (csv_name, len(raw_df), len(df)) # Store (filename, raw_len, cleaned_len)
        
    return sheet_map

def translate_and_combine(df):
    """
    Iterates through the DataFrame, attempts KEGG lookup first, then falls back 
    to Microsoft Translator for English translation.
    """
    trade_name_en_list = []
    trade_name_source_list = []
    ingredient_en_list = []
    ingredient_source_list = []
    
    # Progress bar and status (optional, for Streamlit UI)
    status_text = st.empty()
    progress_bar = st.progress(0)
    total_rows = len(df)
    
    for idx, row in df.iterrows():
        progress = (idx + 1) / total_rows
        progress_bar.progress(progress)
        status_text.text(f"正在翻譯第 {idx + 1}/{total_rows} 筆資料...")
        
        # --- Trade Name Translation (KEGG Priority) ---
        jp_trade_name_raw = str(row.get('販賣名/公司 (日文)', ''))
        
        # 1. Try KEGG first
        japic_code, trade_name_en = get_kegg_trade_name_and_japic(jp_trade_name_raw)
        
        if trade_name_en:
            trade_name_source = "KEGG搜尋頁"
        else:
            # 2. Fallback to Azure Translator
            trade_name_en = ms_translator(jp_trade_name_raw)
            trade_name_source = "自動翻譯"
            
        # --- Ingredient Name Translation (Azure Translator) ---
        ingredient_en = ms_translator(str(row.get('成分名 (日文)', '')))
        ingredient_source = "自動翻譯"
        
        # Append results
        trade_name_en_list.append(trade_name_en)
        trade_name_source_list.append(trade_name_source)
        ingredient_en_list.append(ingredient_en)
        ingredient_source_list.append(ingredient_source)
        
        # Time delay to prevent hitting rate limits on KEGG/Azure (approx 3/second)
        time.sleep(0.34) 
        
    progress_bar.empty()
    status_text.empty()
    
    # Combine translated results back into the DataFrame
    df['Trade Name/Company (English)'] = trade_name_en_list
    df['Trade Name/Company (來源)'] = trade_name_source_list
    df['Ingredient Name (English)'] = ingredient_en_list
    df['Ingredient Name (來源)'] = ingredient_source_list
    
    # Optional: Add JAPIC code if it was successfully fetched (requires code modification 
    # to store the japic_code from get_kegg_trade_name_and_japic)
    
    return df

# --- Streamlit Main App ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器 (自動分頁轉 CSV + 翻譯)")
    
    # File Uploader
    uploaded_file = st.file_uploader("上傳 PMDA 公告 Excel 檔案", type=['xlsx', 'xls'])
    
    if uploaded_file:
        st.info(f"檔案名稱：**{uploaded_file.name}**，開始處理...")
        
        # 1. Process Excel sheets and save as temporary CSVs
        month_csv_map = save_sheets_to_csv_auto_header(uploaded_file)
        
        if not month_csv_map:
            st.warning("未偵測到任何有效分頁。請檢查 Excel 檔案格式是否符合 PMDA 公告表結構。")
            return
            
        st.success(f"成功識別 **{len(month_csv_map)}** 個有效分頁。開始進行翻譯...")

        # 2. Translate each temporary CSV and display/provide download
        for month, (csv_name, raw_len, clean_len) in month_csv_map.items():
            
            st.markdown(f"---")
            st.subheader(f"📄 分頁：**{month}** (原始資料 {raw_len} 筆, 有效資料 {clean_len} 筆)")
            
            try:
                df = pd.read_csv(csv_name, encoding="utf-8")
                
                if df.empty:
                    st.warning(f"分頁 **{month}** 清理後為空。")
                    continue
                    
                translated_df = translate_and_combine(df)
                
                # Display result
                st.dataframe(translated_df, use_container_width=True, hide_index=True)
                
                # Download button
                csv_export = translated_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 下載 {month} 翻譯結果 (CSV)",
                    data=csv_export,
                    file_name=f"{month}_Translated.csv",
                    mime='text/csv'
                )
            
            except Exception as e:
                st.error(f"處理分頁 **{month}** 時發生錯誤: {e}")
            
            finally:
                # 3. Clean up the temporary CSV file
                if os.path.exists(csv_name):
                    os.remove(csv_name)

if __name__ == "__main__":
    main()
