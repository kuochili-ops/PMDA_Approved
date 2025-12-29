import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 保留您的：片假名提取 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 保留您的：核心深度檢索邏輯 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match:
            entry_match = re.search(r'/entry/(D\d+)', resp.text)
            if entry_match and not is_trade:
                api_url = f"https://rest.kegg.jp/get/{entry_match.group(1)}"
                api_resp = session.get(api_url, timeout=10)
                name_match = re.search(r'NAME\s+[^;]+;\s*([A-Za-z0-9\s\-]+)', api_resp.text)
                return name_match.group(1).strip() if name_match else None
            return None

        japic_code = japic_match.group(1)
        # log_container.write(f"🔎 `{kw}` -> JAPIC: {japic_code}") # 保持您的 log

        time.sleep(1) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_resp = session.get(med_url, headers=headers, timeout=15)
        med_html = med_resp.text

        if not is_trade:
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            if ing_match: return ing_match.group(1).strip()
        else:
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                time.sleep(1)
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers, timeout=15)
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp.text, re.S)
                if trade_match: return trade_match.group(1).strip()

    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 請求失敗")
    return None

# --- 3. 修正後的資料清理：專門解決您的 5 月份「無法辨識」報錯 ---
def clean_dataframe(df):
    header_idx = None
    # 遍歷前 10 行尋找標題
    for i, row in df.iterrows():
        if i > 10: break
        # 【關鍵優化】：移除該行所有格子的「所有空白、換行、全形空格」
        row_str = ''.join([re.sub(r'[\s\u3000\n]+', '', str(c)) for c in row if pd.notnull(c)])
        
        # 使用更嚴格但去噪後的關鍵字判斷
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 設定標題行
    df.columns = df.iloc[header_idx]
    # 截取標題下方資料
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位重新映射（同樣採用去噪比對）
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        # 排除空行
        df = df.dropna(subset=['JP_Trade'])
        # 【關鍵優化】：確保 No. 欄位是數字，這能自動排除 5 月份結尾的「注1...」等雜訊
        if 'No.' in df.columns:
            def is_digit_filter(x):
                s = str(x).strip().replace('.0','')
                return s.isdigit()
            df = df[df['No.'].apply(is_digit_filter)]
            
        return df.reset_index(drop=True)
    return None

# --- 4. 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
    st.title("💊 PMDA 藥品清單翻譯 (JAPIC 深度路徑版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 讓使用者選分頁，解決多月份檔案問題
        sheet_name = st.selectbox("選擇分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is not None and not df.empty:
                st.write(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
                with st.status(f"執行中...", expanded=True) as status:
                    log_area = st.empty()
                    results = []
                    for _, row in df.iterrows():
                        # 呼叫您的檢索邏輯
                        en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        
                        results.append({
                            "No.": row.get('No.', ''),
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_trade if en_trade else "[查無結果]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_ing if en_ing else "[查無結果]"
                        })
                        time.sleep(0.5) 
                    status.update(label="檢索完成", state="complete")
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            else:
                st.error("⚠️ 仍無法辨識。請確認分頁標題列（No., 販賣名, 成分名）位於前 10 行內。")

if __name__ == "__main__":
    main()
