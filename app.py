import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 1. 環境設定與快取 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# 初始化快取，避免重複查同樣的藥
if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 強化版 KEGG REST API 函數 (取代爬蟲模式) ---
def get_kegg_rest_enhanced(jp_name, log_container, is_ingredient=False):
    if not jp_name or pd.isna(jp_name): return None
    
    # 【關鍵清洗】移除劑型、商號、括號與數字
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21|分|末|％|%', '', term).strip()
    
    if not term or len(term) < 2: return None
    if term in st.session_state.trans_cache:
        return st.session_state.trans_cache[term]

    try:
        log_container.write(f"🔍 KEGG REST 檢索中: `{term}`")
        # Step 1: Find ID (REST API 較快且不卡)
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        f_resp = requests.get(find_url, timeout=5)
        
        if f_resp.ok and f_resp.text.strip():
            # 取得第一筆 ID
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: Get Info
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                
                # 判定返回結果 (成分優先取 EN_NAME，商品優先取 TH_NAME)
                res = None
                if is_ingredient:
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0]
                    log_container.write(f"✅ KEGG 命中: `{final_res}`")
                    st.session_state.trans_cache[term] = final_res
                    return final_res
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {e}")
    
    return None

# --- 3. Azure 備援翻譯 ---
def ms_translator(text, from_lang="ja"):
    if not text or pd.isna(text): return ""
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

# --- 4. 資料清理邏輯 (您的原邏輯) ---
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

# --- 5. 主程式介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("🇯🇵 PMDA 翻譯校正 (穩定 + KEGG 高命中版)")
    
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx', 'xls'])
    
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                progress_bar = st.progress(0)
                results = []
                
                for idx, row in df.iterrows():
                    # 1. 商品名翻譯
                    jp_trade = row['JP_Trade']
                    en_trade = get_kegg_rest_enhanced(jp_trade, log_area, is_ingredient=False)
                    trade_src = "KEGG" if en_trade else "Azure (備援)"
                    if not en_trade: en_trade = ms_translator(jp_trade)
                    
                    # 2. 成分名翻譯
                    jp_ing = row['JP_Ingredient']
                    en_ing = get_kegg_rest_enhanced(jp_ing, log_area, is_ingredient=True)
                    ing_src = "KEGG" if en_ing else "Azure (備援)"
                    if not en_ing: en_ing = ms_translator(jp_ing)
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "商品名 (日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "商品來源": trade_src,
                        "成分名 (日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "成分來源": ing_src
                    })
                    
                    progress_bar.progress((idx + 1) / len(df))
                    time.sleep(0.1) # 略微等待，提高 UI 穩定性
                
                status.update(label=f"✅ {sheet_name} 處理完成！", state="complete", expanded=False)
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(label=f"📥 下載 {sheet_name} 翻譯結果", data=csv, 
                               file_name=f"PMDA_{sheet_name}.csv", mime='text/csv', key=f"dl_{sheet_name}")

if __name__ == "__main__":
    main()
