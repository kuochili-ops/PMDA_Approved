import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure 翻譯設定 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 核心邏輯 1：KEGG API 優先查詢 ---
def get_kegg_drug_info(jp_name, log_container):
    """
    優先從 KEGG 獲取專業英文藥名
    """
    if not jp_name or pd.isna(jp_name) or str(jp_name).strip() == "":
        return None
    
    # 清理日文括號與公司名，提升搜尋精準度
    search_term = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(jp_name))
    search_term = re.sub(r'\n.*', '', search_term).strip() # 移除換行後的公司名
    
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={search_term}"
    
    try:
        log_container.write(f"🔍 KEGG 檢索: `{search_term}`")
        resp = requests.get(search_url, timeout=10)
        if resp.ok:
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                drug_resp = requests.get(drug_url, timeout=10)
                
                if drug_resp.ok:
                    # 優先序：歐文商標名 > 英文一般名
                    trade_match = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    generic_match = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    
                    res_trade = trade_match.group(1).strip() if trade_match else None
                    res_generic = generic_match.group(1).strip() if generic_match else None
                    
                    result = res_trade if res_trade else res_generic
                    if result:
                        log_container.write(f"✅ KEGG 命中: `{result}`")
                        return result
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {e}")
    return None

# --- 核心邏輯 2：Azure 翻譯備援 ---
def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text) or str(text).strip() == "": return ""
    if "YOUR" in AZURE_KEY: return f"[未配置 API] {text}"
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    # 移除日文換行符號避免翻譯出錯
    clean_text = str(text).replace('\n', ' ')
    body = [{"text": clean_text}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            return resp.json()[0]["translations"][0]["text"]
    except:
        pass
    return text

# --- 資料清理：徹底解決空行問題 ---
def clean_dataframe(df):
    # 尋找標題行
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if '成分名' in row_str and '販' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 重新命名核心欄位
    rename_map = {}
    for col in df.columns:
        c_clean = str(col).replace('\n', '').strip()
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
        
    df = df.rename(columns=rename_map)
    
    if 'JP_Trade' in df.columns and 'JP_Ingredient' in df.columns:
        # 💡 關鍵：強制移除所有 JP_Trade 為空白的列，徹底解決 5 月份多餘空行的問題
        df['JP_Trade'] = df['JP_Trade'].apply(lambda x: str(x).strip() if pd.notnull(x) else "")
        df = df[df['JP_Trade'] != ""].reset_index(drop=True)
        return df
    return None

# --- UI 介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA KEGG Translator")
    st.title("🇯🇵 PMDA 日本新藥翻譯 (KEGG API 優先)")

    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx', 'xls'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 使用 selectbox 避免一次跑太多 Sheet
        sheet_name = st.selectbox("選擇要處理的分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"找到 {len(df)} 筆有效紀錄（已排除空白行）。")
                
                if st.button(f"開始翻譯 {sheet_name} 紀錄"):
                    results = []
                    with st.status(f"處理中...", expanded=True) as status:
                        log_area = st.empty()
                        progress_bar = st.progress(0)
                        
                        for idx, row in df.iterrows():
                            # 1. 處理販賣名
                            en_trade = get_kegg_drug_info(row['JP_Trade'], log_area)
                            trade_src = "KEGG"
                            if not en_trade:
                                en_trade = ms_translator(row['JP_Trade'])
                                trade_src = "Azure"
                            
                            # 2. 處理成分名
                            en_ing = get_kegg_drug_info(row['JP_Ingredient'], log_area)
                            ing_src = "KEGG"
                            if not en_ing:
                                en_ing = ms_translator(row['JP_Ingredient'])
                                ing_src = "Azure"
                            
                            results.append({
                                "No.": row.get('No.', idx+1),
                                "販賣名 (日)": row['JP_Trade'],
                                "Trade Name (EN)": en_trade,
                                "來源": trade_src,
                                "成分名 (日)": row['JP_Ingredient'],
                                "Ingredient (EN)": en_ing,
                                "來源2": ing_src
                            })
                            progress_bar.progress((idx + 1) / len(df))
                            time.sleep(0.1)
                        
                        status.update(label="✅ 翻譯完成！", state="complete")
                    
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button("📥 下載結果", data=csv, file_name=f"PMDA_{sheet_name}.csv", mime='text/csv')
            else:
                st.warning("此分頁沒有符合格式的資料。")

if __name__ == "__main__":
    main()
