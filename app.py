import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 依照您的原則：精確提取開頭連續片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯：真人模擬深度爬取 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    # 關鍵：模擬真人瀏覽器的 Headers，防止被 KEGG 封鎖
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }

    session = requests.Session() # 使用 Session 維持連線狀態

    try:
        # Step 1: 搜尋頁面
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        
        # 尋找 japic_code
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match:
            # 嘗試另一種可能的 ID 格式 (Entry ID)
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade: # 如果是找成分名，D編號很有用
                api_url = f"https://rest.kegg.jp/get/{entry_match.group(1)}"
                api_resp = session.get(api_url, timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None

        japic_code = japic_match.group(1)
        log_container.write(f"🔎 `{kw}` -> JAPIC: {japic_code}")

        # Step 2: 進入 JAPIC 總表頁 (增加延遲避免被鎖)
        time.sleep(1) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_resp = session.get(med_url, headers=headers, timeout=15)
        med_html = med_resp.text

        if not is_trade:
            # 成分名解析
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            if ing_match:
                return ing_match.group(1).strip()
        else:
            # 商品名解析：尋找產品分頁 ID
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                time.sleep(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers, timeout=15)
                # 抓取 md_td_en 標籤
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp.text, re.S)
                if trade_match:
                    res = trade_match.group(1).strip()
                    log_container.write(f"✅ 命中: {res}")
                    return res

    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 請求失敗")
    return None

# --- 3. 精確資料清理 ---
def clean_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(c) for c in row if pd.notnull(c)])
        if '販' in row_str and '名' in row_str:
            header_idx = i
            break
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯終極版")
    st.title("💊 PMDA 藥品清單翻譯 (JAPIC 深度路徑修正版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            if df is None or df.empty: continue
                
            st.write(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            with st.status(f"執行中...", expanded=True) as status:
                log_area = st.empty()
                results = []
                for _, row in df.iterrows():
                    # 執行檢索
                    en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                    en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                    
                    results.append({
                        "No.": row.get('No.', ''),
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_trade if en_trade else "[查無結果]",
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_ing if en_ing else "[查無結果]"
                    })
                    time.sleep(0.5) # 每筆之間微小停頓
                status.update(label="檢索完成", state="complete")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
