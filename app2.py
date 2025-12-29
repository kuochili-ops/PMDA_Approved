import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 片假名提取優化 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 移除括號內公司資訊與換行
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. KEGG 深度路徑檢索 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()
    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match: return None
        
        japic_code = japic_match.group(1)
        time.sleep(0.3)
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers).text
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 3. 核心清洗邏輯：解決「無法辨識」的最終手段 ---
def clean_pmda_v8_5(df):
    header_idx = None
    # 掃描前 10 行，尋找包含「販賣名」與「成分名」的行
    for i in range(min(10, len(df))):
        # 把這一行所有格子的內容串起來，並拔掉所有空格、換行
        row_content = "".join([str(c) for c in df.iloc[i] if pd.notnull(c)])
        row_content = re.sub(r'[\s\u3000\n]+', '', row_content)
        
        if '販賣名' in row_content and '成分名' in row_content:
            header_idx = i
            break
            
    if header_idx is None:
        return None
    
    # 提取標題行並清理
    raw_headers = df.iloc[header_idx]
    df.columns = raw_headers
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 自動定位欄位座標（使用模糊包含判定）
    col_map = {}
    for i, col_name in enumerate(temp_df.columns):
        c = re.sub(r'[\s\u3000\n]+', '', str(col_name))
        if 'No' in c: col_map['No'] = i
        if '販賣名' in c: col_map['Trade'] = i
        if '成分名' in c: col_map['Ing'] = i

    if 'Trade' not in col_map or 'Ing' not in col_map:
        return None

    # 🛑 藍框截斷邏輯
    rows = []
    for _, row in temp_df.iterrows():
        val_no = str(row.iloc[col_map.get('No', 0)]).strip().replace('.0','')
        val_trade = str(row.iloc[col_map['Trade']]).strip()
        val_ing = str(row.iloc[col_map['Ing']]).strip()
        
        # 只要 No 欄位不是純數字，立刻切斷 (解決 5, 6 月份千行空白問題)
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
            
        if val_trade == "" or val_trade.lower() == 'nan': break

        rows.append({"No": val_no, "JP_Trade": val_trade, "JP_Ing": val_ing})
        
    return pd.DataFrame(rows)

# --- 4. Streamlit UI ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯工具 v8.5")
st.title("💊 PMDA 藥品清單翻譯 (模糊標題偵測版)")

up = st.file_uploader("上傳 PMDA 檔案", type=['xlsx', 'csv'])

if up:
    xls = pd.ExcelFile(up)
    sheet = st.selectbox("選擇分頁", xls.sheet_names)
    
    if sheet:
        raw_df = pd.read_excel(xls, sheet_name=sheet, header=None)
        df_clean = clean_pmda_v8_5(raw_df)
        
        if df_clean is not None and not df_clean.empty:
            st.success(f"✅ 辨識成功！偵測到 {len(df_clean)} 筆有效紀錄（藍框區域）。")
            st.dataframe(df_clean, use_container_width=True)
            
            if st.button("🚀 開始深度翻譯"):
                results = []
                status = st.status("正在檢索 KEGG/JAPIC...", expanded=True)
                log = st.empty()
                for idx, r in df_clean.iterrows():
                    log.write(f"正在處理: {r['JP_Trade'][:20]}...")
                    en_t = get_kegg_advanced_info(r['JP_Trade'], log, is_trade=True)
                    en_i = get_kegg_advanced_info(r['JP_Ing'], log, is_trade=False)
                    results.append({
                        "No": r['No'],
                        "商品名(日)": r['JP_Trade'],
                        "Trade Name (EN)": en_t if en_t else "[查無結果]",
                        "成分名(日)": r['JP_Ing'],
                        "Ingredient (EN)": en_i if en_i else "[查無結果]"
                    })
                    time.sleep(0.3)
                status.update(label="✅ 處理完成", state="complete")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.error("⚠️ 仍無法辨識。請確認該分頁的標題列（No., 販賣名, 成分名）位於前 10 行內。")
