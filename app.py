import streamlit as st
import pandas as pd
import requests
import re
import time

def extreme_clean_for_kegg(text):
    """
    極限清理：只保留第一個括號前的片假名，並移除劑型
    範例：'スリンダ錠28(あすか製薬...)' -> 'スリンダ'
    """
    if not text or pd.isna(text): return ""
    # 1. 取第一個括號前的內容
    name = re.split(r'\(|（|［|\[', str(text))[0]
    # 2. 移除常見劑型與干擾詞
    noise = ['錠', 'カプセル', '注', 'シリンジ', '配合', '散', '顆粒', '軟膏', '液', '點眼', '28', '21']
    for n in noise:
        name = name.replace(n, '')
    # 3. 移除全角/半角空格
    return name.strip()

def get_kegg_rest_translation(jp_name, log_container, is_ingredient=False):
    """
    強制執行 KEGG REST API 流程：https://rest.kegg.jp/
    """
    search_term = extreme_clean_for_kegg(jp_name)
    if not search_term: return None

    try:
        # Step 1: /find/drug/關鍵字
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        log_container.write(f"🧬 KEGG 檢索: `{search_term}`")
        
        find_resp = requests.get(find_url, timeout=5)
        if find_resp.ok and find_resp.text.strip():
            # 取得最匹配的第一筆 ID
            drug_id = find_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: /get/ID
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                # TH_NAME = 歐文商標名, EN_NAME = 英文一般名
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                th_val = th_match.group(1).strip() if th_match else None
                en_val = en_match.group(1).strip() if en_match else None
                
                # 邏輯分流
                if is_ingredient:
                    res = en_val if en_val else th_val
                else:
                    res = th_val if th_val else en_val
                
                if res:
                    log_container.write(f"✅ KEGG 成功: `{res}`")
                    return res
    except Exception:
        pass
    return None
