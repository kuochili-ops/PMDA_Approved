import streamlit as st
import pandas as pd
import requests
import re
from urllib.parse import quote

# 依照您的原則：提取開頭連續片假名
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    match = re.search(r'^([ァ-ヶー・]+)', str(text).strip())
    return match.group(1) if match else None

def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        # Step 1: 搜尋並獲取 JAPIC Code (例如 00071731)
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = requests.get(search_url, headers=headers, timeout=10)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        
        if not japic_match: return None
        japic_code = japic_match.group(1)

        # Step 2: 進入 JAPIC 詳情頁 (japic_med)
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_resp = requests.get(med_url, headers=headers, timeout=10)
        med_html = med_resp.text

        if not is_trade:
            # 成分名：直接在詳情頁找 "欧文一般名"
            ing_match = re.search(r'<th>欧文一般名</th><td>(.*?)</td>', med_html)
            if ing_match:
                res = ing_match.group(1).strip()
                log_container.write(f"✅ 成分名命中: {res}")
                return res
        else:
            # 商品名：這需要進入 "japic_med_product" 頁面
            # 先從詳情頁找出具體的 product id (例如 00071731-001)
            prod_id_match = re.search(r'japic_med_product\?id=(\d+-\d+)', med_html)
            if prod_id_match:
                prod_id = prod_id_match.group(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id}"
                prod_resp = requests.get(prod_url, headers=headers, timeout=10)
                prod_html = prod_resp.text
                
                # 在產品頁面中找歐文商品名 (通常在頁面標題或特定表格位置)
                # 這裡使用最通用的匹配方式：找連結文字旁邊的 <td>
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_html) or \
                              re.search(r'<td>([A-Za-z\s]{3,}(?:Nasal|Tablet|Capsule|Spray).*?)</td>', prod_html)
                
                if trade_match:
                    res = trade_match.group(1).strip()
                    log_container.write(f"✅ 商品名命中: {res}")
                    return res
                
                # 備案：回到 med_html 搜尋常見的表格排列格式
                backup_match = re.search(r'<td>([A-Za-z\s]{5,})</td>', med_html)
                if backup_match: return backup_match.group(1).strip()

    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 檢索異常")
    return None

# --- 主程式與清理邏輯保持不變 ---
