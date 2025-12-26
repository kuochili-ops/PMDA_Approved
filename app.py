import streamlit as st
import pandas as pd
import requests
import re
import time

def extreme_clean_for_kegg(text):
    """
    極限清理：移除劑型、公司名與規格，只保留核心藥名片假名。
    範例：'スリンダ錠28(あすか製薬...)' -> 'スリンダ'
    """
    if not text or pd.isna(text): return ""
    # 1. 移除括號及其後的所有內容 (處理公司名與代碼)
    name = re.split(r'\(|（|［|\[', str(text))[0]
    # 2. 移除常見劑型、數字規格與干擾詞
    noise = ['錠', 'カプセル', '注', 'シリンジ', '配合', '散', '顆粒', '軟膏', '液', '點眼', '28', '21', '0.5', '1', '2', '5']
    for n in noise:
        name = name.replace(n, '')
    # 3. 確保移除全角與半角空格
    return name.strip()

def get_kegg_rest_translation(jp_name, log_container, is_ingredient=False):
    """
    實作 KEGG REST API 優先流程：https://rest.kegg.jp/
    """
    # 步驟 1: 取得純淨的搜尋關鍵字
    search_term = extreme_clean_for_kegg(jp_name)
    if not search_term: return None

    try:
        # 步驟 2: 呼叫 /find/drug API 獲取 KEGG ID
        find_url = f"https://rest.kegg.jp/find/drug/{search_term}"
        log_container.write(f"🧬 KEGG REST 檢索中: `{search_term}`")
        
        find_resp = requests.get(find_url, timeout=5)
        if find_resp.ok and find_resp.text.strip():
            # 取得最匹配的第一筆 ID (例如 dr:D00604)
            drug_id = find_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            log_container.write(f"✅ 找到 KEGG ID: `{drug_id}`")
            
            # 步驟 3: 呼叫 /get/ID 獲取詳細結構化數據
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = requests.get(get_url, timeout=5)
            
            if get_resp.ok:
                content = get_resp.text
                # TH_NAME = 歐文商標名, EN_NAME = 英文一般名
                th_match = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_match = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                th_val = th_match.group(1).strip() if th_match else None
                en_val = en_match.group(1).strip() if en_match else None
                
                # 步驟 4: 根據欄位屬性回傳最權威的名稱
                if is_ingredient:
                    # 成分名優先返回 EN_NAME (一般名)
                    res = en_val if en_val else th_val
                else:
                    # 商品名優先返回 TH_NAME (商標名)
                    res = th_val if th_val else en_val
                
                if res:
                    log_container.write(f"✨ KEGG 成功匹配: `{res}`")
                    return res
    except Exception as e:
        log_container.write(f"⚠️ KEGG API 連線失敗: {e}")
    
    return None
