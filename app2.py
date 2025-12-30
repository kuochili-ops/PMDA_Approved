import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

st.set_page_config(layout="wide", page_title="PMDA Search Fixer")

st.title("💊 PMDA 深度搜尋解析器 (修復搜尋失敗問題)")
st.markdown("> **修正說明**：針對搜尋不到 ID 的問題，此版本強化了「藥名提取」邏輯，會自動剔除公司名、括號及法人編號。")

def search_japic_id(full_name):
    """深度搜尋 JapicID，具備多重回退機制"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 1. 基礎清洗：移除所有括號內容、換行、以及全型空白
    # 例如：'リブロファズ配合皮下注 (ヤンセン...)' -> 'リブロファズ配合皮下注'
    clean_keyword = re.split(r'[\(\n\s（]', str(full_name))[0].strip()
    
    # 2. 進階清洗：移除常見的劑型後綴以提高命中率
    # 例如：'ザズベイカプセル30 mg' -> 'ザズベイ'
    short_keyword = re.sub(r'(錠|カプセル|配合|点滴|静注|皮下注|注射|顆粒|内用液|分包|\d+).*$', '', clean_keyword)

    # 嘗試兩種關鍵字搜尋：先用短的（成功率高），再用乾淨的
    for kw in [short_keyword, clean_keyword]:
        if len(kw) < 2: continue
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        try:
            r = requests.get(search_url, headers=headers, timeout=10)
            match = re.search(r'japic_code=(\d+)', r.text + r.url)
            if match:
                return match.group(1).zfill(8)
        except:
            continue
    return None

def fetch_en_details(jid):
    """提取英文資訊邏輯 (保持您的精確提取邏輯)"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    try:
        # Trade Name
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        t_text = BeautifulSoup(rt.text, 'html.parser').get_text(separator=" ", strip=True)
        if "欧文商標名" in t_text:
            after = t_text.split("欧文商標名")[-1].strip()
            m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
            if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()
        
        # Ingredient
        i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}"
        ri = requests.get(i_url, headers=headers, timeout=10)
        ri.encoding = ri.apparent_encoding
        si = BeautifulSoup(ri.text, 'html.parser')
        th = si.find('th', string=re.compile(r'欧文一般名'))
        if th and th.find_next_sibling('td'):
            res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

# --- 介面邏輯 ---
f = st.file_uploader("上傳含有 [未檢出] 的 Excel", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    for s_name in xl.sheet_names:
        df = pd.read_excel(f, sheet_name=s_name)
        # 尋找「日文販賣名」這一欄
        target_col = next((c for c in df.columns if '販' in str(c) or '名' in str(c)), None)
        
        if target_col and st.button(f"開始修復分頁：{s_name}"):
            results = []
            bar = st.progress(0)
            rows = df.to_dict('records')
            
            for i, row in enumerate(rows):
                raw_name = str(row[target_col])
                jid = search_japic_id(raw_name)
                
                if jid:
                    info = fetch_en_details(jid)
                    row['JapicID'] = jid
                    row['Trade Name (EN)'] = info['trade_en']
                    row['Ingredient (EN)'] = info['ing_en']
                else:
                    row['JapicID'] = "[仍未找到]"
                
                results.append(row)
                bar.progress((i + 1) / len(rows))
                time.sleep(0.6)
            
            new_df = pd.DataFrame(results)
            st.dataframe(new_df)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                new_df.to_excel(writer, index=False)
            st.download_button("📥 下載修復後的 Excel", out.getvalue(), f"Fixed_{s_name}.xlsx")
