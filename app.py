import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 1. 配置與快取 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 2. 強化版 KEGG REST API 函數 ---
def get_kegg_rest_enhanced(jp_name, is_ingredient=False):
    if not jp_name or pd.isna(jp_name): return None
    
    # 【清洗關鍵】: 針對截圖中的 "スリンダ錠28" 或 "ドロスピレノン" 進行處理
    # 移除括號、公司名、劑型、數字
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21|分|末|％|%', '', term).strip()
    
    if not term or len(term) < 2: return None
    if term in st.session_state.trans_cache:
        return st.session_state.trans_cache[term]

    try:
        # Step 1: Find ID
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        f_resp = requests.get(find_url, timeout=5)
        if f_resp.ok and f_resp.text.strip():
            # 取得第一筆 ID (例如 D00123)
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: Get Details
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                # 抓取成分名優先找 EN_NAME，商品名找 TH_NAME (通常是歐文商標名)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                
                res = None
                if is_ingredient:
                    res = en_match.group(1) if en_match else (th_match.group(1) if th_match else None)
                else:
                    res = th_match.group(1) if th_match else (en_match.group(1) if en_match else None)
                
                if res:
                    final_res = res.strip().split(';')[0] # 拿第一個別名
                    st.session_state.trans_cache[term] = final_res
                    return final_res
    except:
        pass
    return None

# --- 3. Azure 備援翻譯 ---
def ms_translator(text):
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate", params=params, headers=headers, json=body, timeout=5)
        return r.json()[0]["translations"][0]["text"]
    except:
        return text

# --- 4. 主流程 ---
def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 翻譯校正 (KEGG REST 強化版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            
            # 定位標題 (找 販賣名)
            header_idx = None
            for i, row in df_raw.iterrows():
                if '販' in "".join(row.astype(str)):
                    header_idx = i
                    break
            
            if header_idx is None: continue
            
            df = df_raw.iloc[header_idx:].copy()
            df.columns = df.iloc[0]
            df = df[1:].reset_index(drop=True)
            
            # 欄位映射
            t_col = next(c for c in df.columns if '販' in str(c))
            i_col = next(c for c in df.columns if '成' in str(c))

            st.subheader(f"📊 分頁：{sheet_name}")
            results = []
            status = st.status(f"正在分析 {sheet_name}...")
            
            for idx, row in df.iterrows():
                jp_t = str(row[t_col])
                jp_i = str(row[i_col])
                if "nan" in jp_t.lower(): continue

                # 執行搜尋邏輯
                en_t = get_kegg_rest_enhanced(jp_t, is_ingredient=False)
                t_src = "KEGG" if en_t else "Azure (備援)"
                if not en_t: en_t = ms_translator(jp_t)

                en_i = get_kegg_rest_enhanced(jp_i, is_ingredient=True)
                i_src = "KEGG" if en_i else "Azure (備援)"
                if not en_i: en_i = ms_translator(jp_i)

                results.append({
                    "商品名(日)": jp_t, "Trade Name (EN)": en_trade, "來源(T)": t_src,
                    "成分名(日)": jp_i, "Ingredient (EN)": en_ing, "來源(I)": i_src
                })
                status.write(f"已處理: {jp_t}")
            
            status.update(label="處理完成", state="complete")
            st.dataframe(pd.DataFrame(results), use_container_width=True)

if __name__ == "__main__":
    main()
