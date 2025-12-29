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

# --- KEGG 優先查詢 ---
def get_kegg_drug_info(jp_name, log_container):
    if not jp_name or pd.isna(jp_name) or str(jp_name).strip() == "":
        return None
    
    # 移除日文括號與換行後的公司名
    search_term = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(jp_name))
    search_term = search_term.split('\n')[0].strip() # 只取第一行，過濾公司名
    search_term = re.sub(r'[\s\u3000]+', '', search_term)
    
    if len(search_term) < 2: return None

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
                    trade_match = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    generic_match = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    res = trade_match.group(1).strip() if trade_match else (generic_match.group(1).strip() if generic_match else None)
                    if res: return res
    except:
        pass
    return None

def ms_translator(text):
    if not text or pd.isna(text) or str(text).strip() == "": return ""
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY, "Ocp-Apim-Subscription-Region": AZURE_REGION, "Content-type": "application/json"}
    body = [{"text": str(text).replace('\n', ' ')}]
    try:
        resp = requests.post(ENDPOINT, params={"api-version": "3.0", "from": "ja", "to": ["en"]}, headers=headers, json=body, timeout=10)
        return resp.json()[0]["translations"][0]["text"] if resp.ok else text
    except:
        return text

# --- 嚴格資料清理：解決一千項錯誤問題 ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        combined = re.sub(r'[\s\u3000\r\n\t]+', '', ''.join([str(c) for c in row if pd.notnull(c)]))
        if '成分名' in combined and '販賣名' in combined:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    # 重新定義 DataFrame 起點
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位映射
    new_cols = {}
    for c in df.columns:
        c_norm = re.sub(r'[\s\u3000]+', '', str(c))
        if '販賣名' in c_norm: new_cols[c] = 'JP_Trade'
        elif '成分名' in c_norm: new_cols[c] = 'JP_Ingredient'
        elif 'No' in c_norm: new_cols[c] = 'No.'
    
    df = df.rename(columns=new_cols)
    
    # --- 💡 核心過濾邏輯 ---
    valid_rows = []
    for idx, row in df.iterrows():
        trade_name = str(row.get('JP_Trade', '')).strip()
        # 1. 檢查是否為空字串或 NaN
        if not trade_name or trade_name.lower() == 'nan':
            continue
        # 2. 檢查是否為備註行（例如以「注」開頭，或包含官網字樣）
        if trade_name.startswith('注') or '承認品目' in trade_name:
            continue
        # 3. 確保 No. 欄位是數字，或是販賣名長度大於 2 (過濾掉單個逗號雜訊)
        if len(trade_name) < 2:
            continue
            
        valid_rows.append(row)
    
    # 重組 DataFrame
    clean_df = pd.DataFrame(valid_rows).reset_index(drop=True)
    return clean_df

def main():
    st.set_page_config(layout="wide", page_title="PMDA Translator")
    
    with st.sidebar:
        st.header("相關連結")
        st.markdown("[🔗 PMDA 新医薬品承認品目一覧](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0010.html)")
        st.divider()
        st.info("💡 如果『有效紀錄』數量不對，請檢查 Excel 是否有過多空白分頁。")

    st.title("🇯🇵 PMDA 日本新藥列表翻譯工具")
    
    uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=['xlsx', 'xls'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        sheet_name = st.selectbox("請選擇處理分頁：", xls.sheet_names)
        
        if sheet_name:
            df = clean_dataframe(pd.read_excel(xls, sheet_name=sheet_name, header=None))
            
            if df is not None and not df.empty:
                # 這裡會顯示過濾後的正確筆數
                st.success(f"✅ 成功辨識 {len(df)} 筆紀錄（已排除無效空行）")
                
                if st.button(f"🚀 開始翻譯 {sheet_name}"):
                    results = []
                    with st.status("正在處理...", expanded=True) as status:
                        log_area = st.empty()
                        pbar = st.progress(0)
                        for idx, row in df.iterrows():
                            # KEGG 優先邏輯
                            en_trade = get_kegg_drug_info(row['JP_Trade'], log_area)
                            trade_src = "KEGG"
                            if not en_trade:
                                en_trade = ms_translator(row['JP_Trade'])
                                trade_src = "Azure"
                            
                            en_ing = get_kegg_drug_info(row['JP_Ingredient'], log_area)
                            ing_src = "KEGG"
                            if not en_ing:
                                en_ing = ms_translator(row['JP_Ingredient'])
                                ing_src = "Azure"
                                
                            results.append({
                                "No.": row.get('No.', idx+1),
                                "日文販賣名": row['JP_Trade'],
                                "English Trade Name": en_trade,
                                "來源": trade_src,
                                "日文成分名": row['JP_Ingredient'],
                                "English Ingredient": en_ing,
                                "來源2": ing_src
                            })
                            pbar.progress((idx + 1) / len(df))
                        status.update(label="✅ 完成", state="complete")
                    
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.error("⚠️ 無法辨識有效紀錄。")

if __name__ == "__main__":
    main()
