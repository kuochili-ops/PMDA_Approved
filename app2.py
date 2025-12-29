import streamlit as st
import pandas as pd
import requests
import re
import time

# --- 1. 設定與環境 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = "YOUR_KEY"
    AZURE_REGION = "YOUR_REGION"

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 2. KEGG 優先查詢函數 ---
def get_kegg_drug_info(jp_name, log_container):
    if not jp_name or pd.isna(jp_name) or str(jp_name).strip() == "":
        return None
    
    # 清理日文雜質，只保留核心藥名
    clean_name = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(jp_name))
    clean_name = clean_name.split('\n')[0].split('（')[0].strip()
    clean_name = re.sub(r'[\s\u3000]+', '', clean_name) # 拔掉所有空格
    
    if len(clean_name) < 2: return None

    url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={clean_name}"
    try:
        log_container.write(f"🔍 KEGG 檢索: `{clean_name}`")
        resp = requests.get(url, timeout=10)
        if resp.ok:
            japic = re.search(r'japic_code=(\d+)', resp.text)
            if japic:
                drug_resp = requests.get(f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic.group(1)}", timeout=10)
                if drug_resp.ok:
                    trade = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    generic = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    res = trade.group(1).strip() if trade else (generic.group(1).strip() if generic else None)
                    if res: return res
    except: pass
    return None

def ms_translator(text):
    if not text or pd.isna(text) or str(text).strip() == "": return ""
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY, "Ocp-Apim-Subscription-Region": AZURE_REGION, "Content-type": "application/json"}
    body = [{"text": str(text).replace('\n', ' ')}]
    try:
        resp = requests.post(ENDPOINT, params={"api-version": "3.0", "from": "ja", "to": ["en"]}, headers=headers, json=body, timeout=10)
        return resp.json()[0]["translations"][0]["text"] if resp.ok else text
    except: return text

# --- 3. 核心過濾邏輯：解決辨識失敗與破千行問題 ---
def clean_pmda_dataframe(df):
    # A. 尋找標題行 (精準度提高：移除所有空格後比對)
    header_idx = None
    for i in range(len(df)):
        row_str = "".join([str(x) for x in df.iloc[i] if pd.notnull(x)])
        row_str = re.sub(r'[\s\u3000\n]+', '', row_str) # 徹底拔掉空格換行
        if '成分名' in row_str and '販賣名' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    # B. 建立清洗後的資料
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # C. 定位「販賣名」與「成分名」所在的欄位 index
    trade_col_idx = None
    ing_col_idx = None
    no_col_idx = None
    
    header_row = df.iloc[header_idx]
    for idx, col_val in enumerate(header_row):
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col_val))
        if '販賣名' in c_clean: trade_col_idx = idx
        elif '成分名' in c_clean: ing_col_idx = idx
        elif 'No' in c_clean: no_col_idx = idx

    if trade_col_idx is None or ing_col_idx is None: return None

    # D. 逐行掃描並「強制截斷」
    valid_rows = []
    for _, row in temp_df.iterrows():
        val_trade = str(row.iloc[trade_col_idx]).strip()
        val_no = str(row.iloc[no_col_idx]).strip() if no_col_idx is not None else ""
        
        # 截斷機制：如果 No 是空的，或是遇到「注」或「承認條件」，立刻停止
        if val_trade == "" or val_trade.lower() == 'nan' or '注' in val_trade or '承認品目' in val_trade:
            if len(valid_rows) > 0: break # 如果已經抓過資料了，遇到空行就停止，防止破千行
            continue
            
        valid_rows.append({
            "No.": val_no,
            "JP_Trade": val_trade,
            "JP_Ingredient": str(row.iloc[ing_col_idx]).strip()
        })
        
    return pd.DataFrame(valid_rows)

# --- 4. Streamlit UI ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯 v3.0")
    
    with st.sidebar:
        st.markdown("### 🔗 外部連結")
        st.markdown("[PMDA 新医薬品承認品目一覧](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0010.html)")
        st.divider()
        st.caption("版本：v3.0 座標定位穩定版")

    st.title("🇯🇵 PMDA 專業翻譯工具 (KEGG 優先版)")

    uploaded_file = st.file_uploader("上傳 PMDA 檔案", type=['xlsx', 'xls', 'csv'])

    if uploaded_file:
        # 根據副檔名讀取
        if uploaded_file.name.endswith('.csv'):
            raw_df = pd.read_csv(uploaded_file, header=None)
            sheet_names = ["CSV File"]
        else:
            xls = pd.ExcelFile(uploaded_file)
            sheet_names = xls.sheet_names
            
        sheet_name = st.selectbox("請選擇分頁：", sheet_names)
        
        if sheet_name:
            if not uploaded_file.name.endswith('.csv'):
                raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            
            df = clean_pmda_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 成功辨識 {len(df)} 筆紀錄 (已過濾末端空行)")
                st.dataframe(df, use_container_width=True) # 先預覽辨識結果
                
                if st.button("🚀 開始翻譯"):
                    results = []
                    with st.status("執行中...", expanded=True) as status:
                        log_area = st.empty()
                        pbar = st.progress(0)
                        for idx, row in df.iterrows():
                            # KEGG 優先
                            en_trade = get_kegg_drug_info(row['JP_Trade'], log_area)
                            t_src = "KEGG"
                            if not en_trade:
                                en_trade = ms_translator(row['JP_Trade'])
                                t_src = "Azure"
                            
                            en_ing = get_kegg_drug_info(row['JP_Ingredient'], log_area)
                            i_src = "KEGG"
                            if not en_ing:
                                en_ing = ms_translator(row['JP_Ingredient'])
                                i_src = "Azure"
                            
                            results.append({
                                "No.": row['No.'],
                                "日文販賣名": row['JP_Trade'],
                                "English Trade Name": en_trade,
                                "來源": t_src,
                                "日文成分名": row['JP_Ingredient'],
                                "English Ingredient": en_ing,
                                "來源2": i_src
                            })
                            pbar.progress((idx + 1) / len(df))
                        status.update(label="✅ 翻譯完成", state="complete")
                    
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    st.download_button("📥 下載 CSV", data=res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), file_name=f"PMDA_{sheet_name}.csv")
            else:
                st.error("⚠️ 仍無法辨識。請確認 Excel 分頁中是否包含『販賣名』與『成分名』這幾個字。")

if __name__ == "__main__":
    main()
