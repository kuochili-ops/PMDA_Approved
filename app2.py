import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 雙英文字串精確分離版

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

def fetch_by_japic_logic(japic_id, kw_trade):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    session = requests.Session()
    res = {
        "trade_en": "[查無結果]", 
        "ing_en": "[查無結果]", 
        "target_id": "None", 
        "source_url": "N/A"
    }

    try:
        # 1. 處理 JapicID (優先從 Excel 讀取，補足 8 位數)
        final_id = str(japic_id).strip().split('.')[0].zfill(8) if japic_id and str(japic_id).lower() != 'none' else None
        
        # 若 ID 無效則啟動搜尋
        if not final_id or final_id == "0000None":
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            resp_search = session.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', resp_search.text + resp_search.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id and final_id != "0000None":
            res["target_id"] = final_id
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["source_url"] = target_url
            
            resp_med = session.get(target_url, headers=headers, timeout=15)
            resp_med.encoding = resp_med.apparent_encoding
            soup = BeautifulSoup(resp_med.text, 'html.parser')

            # --- 抓取字串 1：成分名 (來自「欧文一般名」) ---
            # 這是網頁上第一個明確的英文字串位置
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- 抓取字串 2：商品名 (來自「規制区分」) ---
            # 這是網頁上第二個目標位置，通常含有商品英名
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    # 邏輯：從該格提取所有英文字串，並取「最後一個」
                    # 因為格式通常是：[日文] (成分名英) 英文商品名
                    en_matches = re.findall(r'\b[A-Z][A-Z0-9\s\-\.]{3,}\b', raw_text)
                    if en_matches:
                        res["trade_en"] = en_matches[-1].strip()

    except Exception as e:
        res["trade_en"] = f"[解析錯誤]"
    
    return res

# --- UI 與 檔案解析 (略，維持穩定辨識邏輯) ---
