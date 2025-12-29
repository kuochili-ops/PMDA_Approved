import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# 版本標記：2025-12-29 12:15

# --- 1. 片假名提取 (強化版) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 移除換行、括號及其內容
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 深度檢索邏輯 (修復查無結果的問題) ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        # Step 1: 搜尋 JAPIC 編號
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        
        if not japic_match:
            # 備援：Entry ID (D編號)
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade:
                api_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}", timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None

        japic_code = japic_match.group(1)
        time.sleep(0.5) 
        
        # Step 2: 進入 JAPIC 頁面
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 成分名 (歐文一般名)
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名 (抓取 md_td_en)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                p_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                p_resp = session.get(p_url, headers=headers).text
                # 修正：更寬鬆的匹配以應對網頁結構微調
                trade_match = re.search(r'class="md_td_en">([^<]+)</td>', p_resp)
                if trade_match:
                    return trade_match.group(1).strip()
    except: pass
    return None

# --- 3. 寬鬆標題辨識邏輯 (解決「仍無法辨識」) ---
def clean_dataframe(df):
    header_idx = None
    target_cols = {}

    for i, row in df.iterrows():
        if i > 15: break # 增加掃描深度
        row_str = "".join([str(c) for c in row if pd.notnull(c)])
        
        # 只要這行同時出現「販」和「成」字，就判定為標題行
        if '販' in row_str and '成' in row_str:
            header_idx = i
            # 定位具體欄位 index
            for idx, cell in enumerate(row):
                c = str(cell)
                if 'No' in c: target_cols['No'] = idx
                if '販' in c: target_cols['Trade'] = idx
                if '成' in c: target_cols['Ing'] = idx
            break
            
    if header_idx is None or 'Trade' not in target_cols: return None
    
    # 提取資料
    df_data = df.iloc[header_idx + 1:].reset_index(drop=True)
    valid_rows = []
    
    for _, row in df_data.iterrows():
        val_no = str(row.iloc[target_cols.get('No', 0)]).strip().replace('.0','')
        val_trade = str(row.iloc[target_cols['Trade']]).strip()
        val_ing = str(row.iloc[target_cols['Ing']]).strip()

        # 藍框保護：若 No 不是數字則停止 (解決 5 月份尾端空白)
        if not val_no.isdigit():
            if len(valid_rows) > 0: break
            continue
            
        if val_trade == "" or val_trade.lower() == 'nan': break
        
        valid_rows.append({
            "No.": val_no,
            "JP_Trade": val_trade,
            "JP_Ingredient": val_ing
        })
        
    return pd.DataFrame(valid_rows)

# --- 4. UI 介面 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 藥品翻譯 (更新：2025-12-29 12:15)")

up_file = st.file_uploader("上傳 PMDA 檔案", type=['xlsx'])
if up_file:
    xls = pd.ExcelFile(up_file)
    sheet = st.selectbox("選擇分頁：", xls.sheet_names)
    if sheet:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        df = clean_dataframe(raw)
        
        if df is not None and not df.empty:
            st.success(f"✅ 辨識成功！分頁：{sheet} (數據：{len(df)} 筆)")
            if st.button("🚀 開始深度翻譯"):
                log = st.empty()
                results = []
                for idx, row in df.iterrows():
                    log.write(f"正在檢索 No.{row['No.']}: {row['JP_Trade'][:15]}...")
                    en_t = get_kegg_advanced_info(row['JP_Trade'], log, True)
                    en_i = get_kegg_advanced_info(row['JP_Ingredient'], log, False)
                    results.append({
                        "No.": row['No.'],
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_t if en_t else "[查無結果]",
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_i if en_i else "[查無結果]"
                    })
                    time.sleep(0.3)
                st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.error("⚠️ 仍無法辨識。請確認分頁中包含「販賣名」欄位。")
