import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 片假名提取 (保持您的邏輯，但增加對括號的處理) ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 移除括號內的公司資訊與換行
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯 (針對截圖中 [查無結果] 的修復) ---
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
            # 備援：嘗試 Entry ID
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade:
                api_resp = session.get(f"https://rest.kegg.jp/get/{entry_match.group(1)}", timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None

        japic_code = japic_match.group(1)
        time.sleep(0.3) 
        
        # Step 2: 進入 JAPIC 頁面
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 成分名解析 (歐文一般名)
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名解析 (關鍵修復：針對截圖中失效的路徑)
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                p_resp = session.get(prod_url, headers=headers).text
                # 強化標籤抓取邏輯
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', p_resp, re.S)
                if trade_match:
                    return trade_match.group(1).strip()
    except: pass
    return None

# --- 3. 資料清理邏輯 (採用截圖二中成功辨識的去噪比對) ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        # 去除所有全形空格與換行後的強力比對
        row_str = "".join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in row if pd.notnull(c)])
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 定位標題
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位重新映射
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    df = df.rename(columns=rename_map)
    
    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        # 藍框邊界守護：過濾掉非數字的 No.
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. Streamlit 主程式 ---
def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 藥品清單翻譯 (JAPIC 深度修正版)")

    up_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if up_file:
        xls = pd.ExcelFile(up_file)
        sheet_name = st.selectbox("選擇分頁", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None:
                st.success(f"✅ 辨識成功！分頁：{sheet_name} (有效數據: {len(df)} 筆)")
                if st.button("🚀 開始檢索翻譯"):
                    results = []
                    log_area = st.empty()
                    for _, row in df.iterrows():
                        en_t = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_i = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        results.append({
                            "No.": row.get('No.', ''),
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_t if en_t else "[查無結果]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_i if en_i else "[查無結果]"
                        })
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.error("⚠️ 無法辨識。請確認標題列位於前 10 行內。")

if __name__ == "__main__":
    main()
