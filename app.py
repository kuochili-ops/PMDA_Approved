import streamlit as st
import pandas as pd
import requests
import re
import time
import os
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- 初始化快取 (避免重複查同樣的藥) ---
if 'trans_cache' not in st.session_state:
    st.session_state.trans_cache = {}

# --- 設定連線重試機制，防止網路波動導致卡死 ---
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

session = get_session()

# --- 1. 強化型 KEGG REST API ---
def get_kegg_rest_stable(jp_name, is_ingredient=False):
    if not jp_name or pd.isna(jp_name): return None
    
    # 清理名稱：移除劑型與無關符號
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21|分', '', term).strip()
    
    if term in st.session_state.trans_cache:
        return st.session_state.trans_cache[term]

    try:
        # Step 1: Find ID (縮短 timeout)
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        f_resp = session.get(find_url, timeout=3)
        if f_resp.ok and f_resp.text.strip():
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: Get Info
            g_resp = session.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=3)
            if g_resp.ok:
                content = g_resp.text
                th = re.search(r'TH_NAME\s+(.*?)\n', content)
                en = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                res = (en.group(1) if en else th.group(1)) if is_ingredient else (th.group(1) if th else en.group(1))
                if res:
                    final_res = res.strip()
                    st.session_state.trans_cache[term] = final_res
                    return final_res
    except Exception:
        pass # 失敗則跳過，讓 Azure 補位
    return None

# --- 2. 核心主流程優化 ---
# (此處保留您的 find_header_row 與 Azure 翻譯設定)

# 處理每一列時的穩定性控制
for idx, row in df.iterrows():
    jp_t, jp_i = str(row[t_col]), str(row[i_col])
    if jp_t == "nan": continue

    # 加入小延遲，防止被 API 端點視為攻擊
    time.sleep(0.1) 

    # 先嘗試 KEGG
    en_t = get_kegg_rest_stable(jp_t, is_ingredient=False)
    t_src = "KEGG" if en_t else "Azure (備援)"
    
    # 若 KEGG 失敗，才呼叫 Azure (避免浪費額度與連線數)
    if not en_t:
        en_t = ms_translator(jp_t)
    
    # 成分同理
    en_i = get_kegg_rest_stable(jp_i, is_ingredient=True)
    i_src = "KEGG" if en_i else "Azure (備援)"
    if not en_i:
        en_i = ms_translator(jp_i)
