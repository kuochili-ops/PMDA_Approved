import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io

# 版本標記：2025-12-29 13:45

# --- 1. 片假名提取 (物理過濾雜質) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 移除所有括號內容、換行、以及非日文字元
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯 (針對 [查無結果] 的多重備援) ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()

    try:
        # Step 1: 搜尋
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        html = resp.text

        # 檢查是否需要從列表頁跳轉
        japic_match = re.search(r'japic_code=(\d+)', html)
        if not japic_match:
            list_match = re.search(r'href="/medicus-bin/japic_med\?japic_code=(\d+)"', html)
            japic_code = list_match.group(1) if list_match else None
        else:
            japic_code = japic_match.group(1)

        if not japic_code:
            # 備援：嘗試 API 直接獲取 D編號 名稱
            entry_match = re.search(r'/entry/(D\d+)', html)
            if entry_match:
                api_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}").text
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp)
                return name_match.group(1).strip() if name_match else None
            return None

        time.sleep(0.3)
        # Step 2: 進入詳情頁
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名進入子頁面
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                p_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                p_resp = session.get(p_url, headers=headers).text
                trade_match = re.search(r'class="md_td_en">([^<]*)</td>', p_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 3. 動態錨點資料清理 (修正截圖中的資料位移問題) ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(25, len(df))):
        row_str = "".join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in df.iloc[i] if pd.notnull(c)])
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(df.iloc[i]):
                c = re.sub(r'[\s\u3000\n]+', '', str(cell))
                if 'No' in c: cols['No'] = idx
                elif '販' in c: cols['Trade'] = idx
                elif '成' in c: cols['Ing'] = idx
            break
            
    if header_idx is None or 'Trade' not in cols: return None
    
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        # 修正：針對 5 月份檔案常見的合併儲存格位移進行動態校正
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
        
        # 根據座標精確提取，解決資料跑到別格的問題
        rows.append({
            "No.": val_no,
            "JP_Trade": str(row.iloc[cols['Trade']]).strip(),
            "JP_Ingredient": str(row.iloc[cols['Ing']]).strip()
        })
    return pd.DataFrame(rows)

# --- 4. Streamlit UI ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
st.title("💊 PMDA 藥品清單翻譯 (校正版：2025-12-29 13:45)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    xls = pd.ExcelFile(f)
    sheet = st.selectbox("選擇分頁", xls.sheet_names)
    if sheet:
        df = clean_dataframe(pd.read_excel(xls, sheet_name=sheet, header=None))
        if df is not None and not df.empty:
            st.success(f"✅ 辨識完成！偵測到 {len(df)} 筆有效藥品資料。")
            if st.button("🚀 執行深度檢索與翻譯"):
                results = []
                bar = st.progress(0)
                log = st.empty()
                for i, r in df.iterrows():
                    log.text(f"正在處理 ({i+1}/{len(df)}): {r['JP_Trade'][:15]}...")
                    en_t = get_kegg_advanced_info(r['JP_Trade'], log, True)
                    en_i = get_kegg_advanced_info(r['JP_Ingredient'], log, False)
                    results.append({
                        "No.": r['No.'], "商品名(日)": r['JP_Trade'],
                        "Trade Name (EN)": en_t or "[查無結果]",
                        "成分名(日)": r['JP_Ingredient'],
                        "Ingredient (EN)": en_i or "[查無結果]"
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(0.5)
                
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                # 新增下載按鈕
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Translation')
                st.download_button(label="📥 下載翻譯結果 Excel", data=output.getvalue(), file_name=f"PMDA_Translation_{sheet}.xlsx")
        else:
            st.error("⚠️ 無法定位標題列，請確保分頁內含有「販賣名」欄位。")
