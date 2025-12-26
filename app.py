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
def get_kegg_drug_info(jp_name, log_container):
    if not jp_name or pd.isna(jp_name):
        return None
    
    # 清理日文括號干擾
    search_term = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(jp_name)).strip()
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={search_term}"
    
    try:
        log_container.write(f"🔍 KEGG 檢索中: `{search_term}`")
        resp = requests.get(search_url, timeout=10)
        if resp.ok:
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                drug_resp = requests.get(drug_url, timeout=10)
                
                if drug_resp.ok:
                    # 優先抓取 歐文商標名，其次 英文一般名
                    trade_match = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    generic_match = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    
                    res_trade = trade_match.group(1).strip() if trade_match else None
                    res_generic = generic_match.group(1).strip() if generic_match else None
                    
                    result = res_trade if res_trade else res_generic
                    if result:
                        log_container.write(f"✅ KEGG 命中: `{result}`")
                        return result
    except Exception as e:
        log_container.write(f"⚠️ KEGG 連線異常: {e}")
    
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

# --- 資料清理 ---
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
        # 清除完全空白的行
        return df.dropna(subset=['JP_Trade', 'JP_Ingredient'], how='all').reset_index(drop=True)
    return None

# --- 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA KEGG Translator")
    st.title("🇯🇵 PMDA 日本新藥翻譯 (KEGG API 優先)")

    uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx', 'xls'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        
        # 💡 關鍵修改 1：手動選擇分頁，避免一次性渲染所有月份導致白屏
        sheet_name = st.selectbox("請選擇要處理的月份分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.info(f"偵測到 {len(df)} 筆有效資料。")
                
                # 💡 關鍵修改 2：使用 Button 觸發，防止 Streamlit 重複執行自動查詢
                if st.button(f"開始執行 {sheet_name} 翻譯"):
                    results = []
                    with st.status(f"正在翻譯 {sheet_name}...", expanded=True) as status:
                        log_area = st.empty()
                        progress_bar = st.progress(0)
                        
                        for idx, row in df.iterrows():
                            # 1. 商品名 (KEGG -> Azure)
                            jp_trade = row['JP_Trade']
                            en_trade = get_kegg_drug_info(jp_trade, log_area)
                            trade_src = "KEGG"
                            if not en_trade:
                                en_trade = ms_translator(jp_trade)
                                trade_src = "Azure"
                            
                            # 2. 成分名 (KEGG -> Azure)
                            jp_ing = row['JP_Ingredient']
                            en_ing = get_kegg_drug_info(jp_ing, log_area)
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
                            time.sleep(0.1) # 稍微緩衝防止請求過快
                        
                        status.update(label="✅ 處理完成！", state="complete")
                    
                    # 顯示結果
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    
                    # 下載按鈕
                    csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button(
                        label="📥 下載翻譯結果 (CSV)",
                        data=csv,
                        file_name=f"PMDA_{sheet_name}_KEGG.csv",
                        mime='text/csv'
                    )
            else:
                st.warning("無法解析該分頁的欄位，請檢查格式是否包含「販賣名」與「成分名」。")

if __name__ == "__main__":
    main()
