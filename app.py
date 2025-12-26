import streamlit as st
import pandas as pd
import requests
import re
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")

# Azure Translator 設定
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# 初始化快取
if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# 設定連線重試機制 (防止網路波動導致卡住)
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

http_session = get_session()

# --- 2. 核心查詢函數 ---

def get_kegg_rest(jp_name, is_ingredient=False):
    """使用穩定的 REST API 獲取藥名"""
    if not jp_name or pd.isna(jp_name): return None
    
    # 清理名稱：移除劑型與括號內容
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21|分', '', term).strip()
    
    if term in st.session_state.trans_cache:
        return st.session_state.trans_cache[term]

    try:
        # Step 1: 透過名稱找 ID
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        f_resp = http_session.get(find_url, timeout=3)
        if f_resp.ok and f_resp.text.strip():
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: 獲取詳細資料
            g_resp = http_session.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=3)
            if g_resp.ok:
                content = g_resp.text
                th = re.search(r'TH_NAME\s+(.*?)\n', content)
                en = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                # 判定結果
                res = (en.group(1) if en else th.group(1)) if is_ingredient else (th.group(1) if th else en.group(1))
                if res:
                    final_res = res.strip()
                    st.session_state.trans_cache[term] = final_res
                    return final_res
    except:
        pass
    return None

def ms_translator(text):
    """Azure 翻譯作為備援"""
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        resp = http_session.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        if resp.ok:
            return resp.json()[0]["translations"][0]["text"]
    except:
        pass
    return str(text)

# --- 3. 表格解析邏輯 ---

def find_header_row(df):
    """偵測標題行位置"""
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if ('成分名' in row_str or '成' in row_str) and '販' in row_str:
            return i
    return None

# --- 4. 主執行介面 ---

def main():
    st.title("🇯🇵 PMDA 日本新藥列表翻譯 (穩定增強版)")
    uploaded_file = st.file_uploader("上傳 PMDA Excel 檔案", type=['xlsx', 'xls'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            h_idx = find_header_row(raw_df)
            
            if h_idx is None:
                continue

            # 重整表格
            df = raw_df.iloc[h_idx:].copy()
            df.columns = df.iloc[0]
            df = df[1:].reset_index(drop=True)
            
            # 定位關鍵欄位
            t_col = next((c for c in df.columns if '販' in str(c) and '名' in str(c)), None)
            i_col = next((c for c in df.columns if '成' in str(c) and '名' in str(c)), None)
            
            if not t_col or not i_col: continue

            st.markdown(f"---")
            st.subheader(f"📄 分頁：{sheet_name}")

            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                results = []
                progress_bar = st.progress(0)
                
                for idx, row in df.iterrows():
                    jp_trade = str(row[t_col])
                    jp_ing = str(row[i_col])
                    if jp_trade == "nan": continue

                    # 1. 處理商品名 (KEGG -> Azure)
                    en_trade = get_kegg_rest(jp_trade, False)
                    t_src = "KEGG" if en_trade else "Azure (備援)"
                    if not en_trade: en_trade = ms_translator(jp_trade)

                    # 2. 處理成分名 (KEGG -> Azure)
                    en_ing = get_kegg_rest(jp_ing, True)
                    i_src = "KEGG" if en_ing else "Azure (備援)"
                    if not en_ing: en_ing = ms_translator(jp_ing)

                    results.append({
                        "商品名(日)": jp_trade,
                        "Trade Name (EN)": en_trade,
                        "商品來源": t_src,
                        "成分名(日)": jp_ing,
                        "Ingredient (EN)": en_ing,
                        "成分來源": i_src
                    })
                    progress_bar.progress((idx + 1) / len(df))
                
                status.update(label=f"✅ {sheet_name} 處理完成", state="complete")

            # 顯示結果與下載
            res_df = pd.DataFrame(results)
            st.dataframe(res_df, use_container_width=True)
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(f"📥 下載 {sheet_name} 翻譯結果", csv, f"{sheet_name}.csv", "text/csv", key=f"dl_{sheet_name}")

if __name__ == "__main__":
    main()
