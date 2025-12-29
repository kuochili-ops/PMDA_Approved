import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# 版本標記：2025-12-29 13:15

# --- 1. 片假名提取 (強化版) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 移除換行、括號內容及所有非片假名字元
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 深度檢索邏輯 (針對列表頁跳轉進行強化) ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        # Step 1: 搜尋關鍵字
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        html = resp.text

        # 檢查是否在列表頁而非詳情頁
        japic_match = re.search(r'japic_code=(\d+)', html)
        if not japic_match:
            # 嘗試找尋結果列表中的第一個連結
            list_match = re.search(r'href="/medicus-bin/japic_med\?japic_code=(\d+)"', html)
            if list_match:
                japic_code = list_match.group(1)
            else:
                return None
        else:
            japic_code = japic_match.group(1)

        time.sleep(0.3)
        
        # Step 2: 進入詳情頁面
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 抓取成分名 (歐文一般名)
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 抓取商品名 (進入子頁面)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                p_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                p_resp = session.get(p_url, headers=headers).text
                # 修正後的正則表達式，針對截圖中消失的 Trade Name
                trade_match = re.search(r'class="md_td_en">([^<]*)</td>', p_resp, re.S)
                if trade_match:
                    return trade_match.group(1).strip()
    except Exception as e:
        pass
    return None

# --- 3. 穩定版資料清理 ---
def clean_dataframe(df):
    header_idx = None
    target_cols = {}
    for i in range(min(20, len(df))):
        row_str = "".join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in df.iloc[i] if pd.notnull(c)])
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
                c = re.sub(r'[\s\u3000\n]+', '', str(cell))
                if 'No' in c: target_cols['No'] = idx
                if '販' in c: target_cols['Trade'] = idx
                if '成' in c: target_cols['Ing'] = idx
            break
            
    if header_idx is None or 'Trade' not in target_cols: return None
    
    df_rows = df.iloc[header_idx + 1:].reset_index(drop=True)
    results = []
    for _, row in df_rows.iterrows():
        val_no = str(row.iloc[target_cols.get('No', 0)]).strip().replace('.0','')
        val_trade = str(row.iloc[target_cols['Trade']]).strip()
        val_ing = str(row.iloc[target_cols['Ing']]).strip()
        if not val_no.isdigit():
            if len(results) > 0: break
            continue
        if val_trade == "" or val_trade.lower() == 'nan': break
        results.append({"No.": val_no, "JP_Trade": val_trade, "JP_Ingredient": val_ing})
    return pd.DataFrame(results)

# --- 4. UI ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 藥品翻譯 (最終修正版：2025-12-29 13:15)")

up = st.file_uploader("上傳 Excel", type=['xlsx'])
if up:
    xls = pd.ExcelFile(up)
    sheet = st.selectbox("選擇分頁", xls.sheet_names)
    if sheet:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        df = clean_dataframe(raw)
        if df is not None and not df.empty:
            st.success(f"✅ 辨識成功！數據：{len(df)} 筆")
            if st.button("🚀 開始深度翻譯"):
                status = st.status("正在檢索資料...", expanded=True)
                log = st.empty()
                final = []
                for _, r in df.iterrows():
                    log.write(f"正在搜尋 No.{r['No.']}: {r['JP_Trade'][:15]}...")
                    en_t = get_kegg_advanced_info(r['JP_Trade'], log, True)
                    en_i = get_kegg_advanced_info(r['JP_Ingredient'], log, False)
                    final.append({
                        "No.": r['No.'],
                        "商品名(日)": r['JP_Trade'],
                        "Trade Name (EN)": en_t if en_t else "[查無結果]",
                        "成分名(日)": r['JP_Ingredient'],
                        "Ingredient (EN)": en_i if en_i else "[查無結果]"
                    })
                    time.sleep(0.5)
                status.update(label="✅ 完成", state="complete")
                st.dataframe(pd.DataFrame(final), use_container_width=True)
