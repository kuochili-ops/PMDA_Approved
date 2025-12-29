import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io

# 版本標記：2025-12-29 16:00

# --- 1. 片假名提取 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 2. 核心檢索邏輯 (嚴格物理路徑) ---
def get_kegg_perfect_info(kw_trade, kw_ing):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    res = {"trade_en": "[查無結果]", "ing_en": "[查無結果]"}

    try:
        # --- A. 處理成分名 (搜尋成分關鍵字，抓取搜尋結果頁的一般名) ---
        search_ing_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_ing)}"
        resp_ing = session.get(search_ing_url, headers=headers, timeout=10).text
        
        # 修正：精確鎖定包含關鍵字的「一般名」TD 標籤
        # 邏輯：找 <td>...一般名片假名 (英文)...</td>
        ing_pattern = rf'<td>\s*{kw_ing}\s*\(([^)]+)\)'
        ing_match = re.search(ing_pattern, resp_ing)
        if ing_match:
            res["ing_en"] = ing_match.group(1).strip()

        # --- B. 處理商品名 (搜尋商品關鍵字，進入 JAPIC 頁面抓取欧文商標名) ---
        search_trade_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
        resp_trade = session.get(search_trade_url, headers=headers, timeout=10).text
        
        japic_match = re.search(r'japic_code=(\d+)', resp_trade)
        if not japic_match:
            list_match = re.search(r'href="/medicus-bin/japic_med\?japic_code=(\d+)"', resp_trade)
            japic_code = list_match.group(1) if list_match else None
        else:
            japic_code = japic_match.group(1)

        if japic_code:
            time.sleep(0.5) # 稍微延長延遲確保穩定
            med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
            med_html = session.get(med_url, headers=headers).text
            
            # 修正：嚴格匹配「欧文商標名」標題後的內容
            # 避免抓到「欧文一般名」或其他鄰近欄位
            trade_pattern = r'<th>欧文商標名</th>\s*<td>\s*(.*?)\s*</td>'
            trade_match = re.search(trade_pattern, med_html, re.S)
            if trade_match:
                # 移除可能存在的 HTML 標籤
                trade_clean = re.sub(r'<.*?>', '', trade_match.group(1)).strip()
                res["trade_en"] = trade_clean

    except Exception as e:
        pass
    return res

# --- 3. 資料清理與 UI ---
def clean_dataframe(df):
    header_idx = None
    cols = {}
    for i in range(min(20, len(df))):
        row = [str(c) for c in df.iloc[i]]
        row_str = "".join(row)
        if '販' in row_str and '成' in row_str:
            header_idx = i
            for idx, cell in enumerate(row):
                c = str(cell)
                if 'No' in c: cols['No'] = idx
                if '販' in c: cols['Trade'] = idx
                if '成' in c: cols['Ing'] = idx
            break
            
    if header_idx is None: return None
    
    rows = []
    for _, row in df.iloc[header_idx + 1:].iterrows():
        val_no = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
        if not val_no.isdigit():
            if len(rows) > 0: break
            continue
        
        t_full = str(row.iloc[cols['Trade']]).strip()
        i_full = str(row.iloc[cols['Ing']]).strip()
        rows.append({
            "No.": val_no,
            "商品名(日)": t_full,
            "商品名(關鍵字)": get_katakana_prefix(t_full),
            "成分名(日)": i_full,
            "成分名(關鍵字)": get_katakana_prefix(i_full)
        })
    return pd.DataFrame(rows)

st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯 (物理隔離修正版：2025-12-29 16:00)")

f = st.file_uploader("上傳 Excel", type=['xlsx'])
if f:
    raw_df = pd.read_excel(f, header=None)
    df = clean_dataframe(raw_df)
    if df is not None:
        st.success("✅ 辨識成功！")
        st.dataframe(df, use_container_width=True)
        
        if st.button("🚀 開始執行 (嚴格區分商標名/一般名)"):
            final_results = []
            bar = st.progress(0)
            log = st.empty()
            
            for i, r in df.iterrows():
                log.text(f"處理中 No.{r['No.']}: {r['商品名(關鍵字)']} / {r['成分名(關鍵字)']}...")
                info = get_kegg_perfect_info(r['商品名(關鍵字)'], r['成分名(關鍵字)'])
                
                final_results.append({
                    "No.": r['No.'],
                    "商品名(日)": r['商品名(日)'],
                    "Trade Name (EN)": info["trade_en"],
                    "成分名(日)": r['成分名(日)'],
                    "Ingredient (EN)": info["ing_en"]
                })
                bar.progress((i + 1) / len(df))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(final_results)
            st.subheader("📊 翻譯結果")
            st.dataframe(res_df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel 結果", output.getvalue(), "PMDA_Final_EN.xlsx")
