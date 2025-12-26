import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 設定頁面（必須放在最前面） ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯器")

# --- Azure API 配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# --- 1. KEGG 專用清洗函數 ---
def clean_for_kegg(text):
    """將複雜的藥名縮減為 KEGG 能識別的核心詞"""
    if not text or pd.isna(text): return ""
    # 移除括號內容 (包含公司名與編號)
    name = re.split(r'\(|（|［|\[', str(text))[0]
    # 移除劑型與單位干擾
    noise = ['錠', 'カプセル', '注', 'シリンジ', '配合', '散', '顆粒', '軟膏', '液', '點眼', '28', '21', '5mg', '10mg']
    for n in noise:
        name = name.replace(n, '')
    return name.strip()

# --- 2. 核心 KEGG REST API ---
def get_kegg_rest_translation(jp_name, log_container, is_ingredient=False):
    """依照 KEGG API 手冊，先 find 再 get"""
    search_term = clean_for_kegg(jp_name)
    if not search_term: return None

    try:
        # Step 1: 透過 find 取得 ID
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        log_container.write(f"🧬 KEGG 檢索: `{search_term}`")
        
        find_resp = requests.get(find_url, timeout=5)
        if find_resp.ok and find_resp.text.strip():
            # 取得第一筆匹配結果的 ID (格式如 dr:D00604)
            drug_id = find_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: 透過 get 取得詳細資料
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                # TH_NAME = 歐文商標名, EN_NAME = 英文一般名
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                th_val = th_match.group(1).strip() if th_match else None
                en_val = en_match.group(1).strip() if en_match else None
                
                # 商品名優先取 TH，成分名優先取 EN
                res = (en_val if en_val else th_val) if is_ingredient else (th_val if th_val else en_val)
                if res:
                    log_container.write(f"✅ KEGG 成功: `{res}`")
                    return res
    except:
        pass
    return None

# --- 3. Azure 備援翻譯 ---
def azure_fallback(text):
    if not text or pd.isna(text) or "YOUR" in AZURE_KEY: return text
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate", 
                          params=params, headers=headers, json=body, timeout=5)
        return r.json()[0]["translations"][0]["text"] if r.ok else text
    except:
        return text

# --- 4. 主執行介面 ---
st.title("🇯🇵 PMDA 日本新藥清單翻譯 (穩定版)")

uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        
        # 簡單判斷標題 (根據您的截圖邏輯)
        if not any('成分名' in str(c) for c in df.columns) and not any('販' in str(c) for c in df.columns):
            continue

        st.subheader(f"月份：{sheet_name}")
        
        # 使用 placeholder 避免刷新干擾渲染
        status_placeholder = st.empty()
        table_placeholder = st.empty()
        
        results = []
        with status_placeholder.status(f"處理中: {sheet_name}...", expanded=True) as status:
            log_box = st.empty()
            
            # 為加速測試僅示範前幾筆，您可以移除 [0:10]
            for idx, row in df.iterrows():
                # 這裡假設欄位名稱包含 '成分名' 或 '販賣名'
                # 請依實際 CSV/Excel 欄位名稱調整，此處簡化處理
                jp_trade = str(row.iloc[1]) # 假設第二欄是商品名
                jp_ing = str(row.iloc[4])   # 假設第五欄是成分名
                
                # 商品名翻譯
                en_t = get_kegg_rest_translation(jp_trade, log_box, False)
                t_src = "KEGG" if en_t else "Azure"
                if not en_t: en_t = azure_fallback(jp_trade)
                
                # 成分名翻譯
                en_i = get_kegg_rest_translation(jp_ing, log_box, True)
                i_src = "KEGG" if en_i else "Azure"
                if not en_i: en_i = azure_fallback(jp_ing)
                
                results.append({
                    "商品名(日)": jp_trade,
                    "Trade Name (EN)": en_t,
                    "成分名(日)": jp_ing,
                    "Ingredient (EN)": en_i,
                    "來源": f"{t_src}/{i_src}"
                })
            status.update(label="✅ 完成", state="complete")
        
        res_df = pd.DataFrame(results)
        table_placeholder.dataframe(res_df, use_container_width=True)
