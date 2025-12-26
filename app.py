import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure 備援設定 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# --- KEGG REST API 核心函數 ---

def get_kegg_rest_translation(jp_name, log_container, is_ingredient=False):
    """
    實作 KEGG API 手冊規範：先 find 再 get
    """
    if not jp_name or pd.isna(jp_name): return None
    
    # 預處理：移除劑型規格以增加 API 命中率
    search_term = re.sub(r'［.*?］|（.*?）|\(.*?\)|錠|カプセル|注|シリンジ', '', str(jp_name)).strip()
    if not search_term: return None

    try:
        # Step 1: find/drug/關鍵字
        # 參考手冊：https://rest.kegg.jp/find/drug/關鍵字
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        log_container.write(f"🧬 KEGG API Find: `{search_term}`")
        
        find_resp = requests.get(find_url, timeout=5)
        if find_resp.ok and find_resp.text.strip():
            # 取得第一個匹配的 ID (格式: dr:DXXXXX)
            drug_id = find_resp.text.split('\t')[0].replace('dr:', '')
            log_container.write(f"✅ 命中 ID: `{drug_id}`")
            
            # Step 2: get/ID
            # 參考手冊：https://rest.kegg.jp/get/DXXXXX
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                
                # Step 3: 解析純文字內容
                # TH_NAME = 歐文商標名 (常用於商品名)
                # EN_NAME = 英文一般名 (常用於成分名)
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                th_val = th_match.group(1).strip() if th_match else None
                en_val = en_match.group(1).strip() if en_match else None
                
                # 根據請求類型返回最合適的結果
                if is_ingredient:
                    # 成分名優先返回 EN_NAME
                    result = en_val if en_val else th_val
                else:
                    # 商品名優先返回 TH_NAME
                    result = th_val if th_val else en_val
                
                if result:
                    log_container.write(f"✨ 成功獲取英文: `{result}`")
                    return result

    except Exception as e:
        log_container.write(f"⚠️ API 異常: {e}")
    
    return None

def ms_translator_fallback(text):
    """當 KEGG API 找不到時才呼叫 Azure"""
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        resp = requests.post("https://api.cognitive.microsofttranslator.com/translate", 
                             params=params, headers=headers, json=body, timeout=5)
        return resp.json()[0]["translations"][0]["text"] if resp.ok else text
    except:
        return text

# --- (資料清理邏輯與 main 保持逐月產出架構，僅修改翻譯呼叫) ---

def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯助手")
    st.title("💊 PMDA 翻譯列表生成器 (KEGG REST API 優先版)")

    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            # 此處調用先前的 clean_pmda_dataframe...
            # 進入處理迴圈
            # ...
            
            # --- 翻譯呼叫重點 ---
            # 1. 商品名翻譯
            en_trade = get_kegg_rest_translation(raw_trade, log_box, is_ingredient=False)
            trade_src = "KEGG REST API" if en_trade else "Azure (備援)"
            if not en_trade: en_trade = ms_translator_fallback(raw_trade)
            
            # 2. 成分名翻譯 (例如: ドロスピレノン)
            en_ing = get_kegg_rest_translation(raw_ing, log_box, is_ingredient=True)
            ing_src = "KEGG REST API" if en_ing else "Azure (備援)"
            if not en_ing: en_ing = ms_translator_fallback(raw_ing)
            # ------------------

if __name__ == "__main__":
    main()
