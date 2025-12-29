import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 片假名提取：過濾劑型與公司資訊 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 只取第一行，並移除括號、廠商名與特殊符號
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    text = re.sub(r'［.*?］|（.*?）', '', text)
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 核心檢索邏輯：您的深度 JAPIC 路徑比對 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=10)
        
        # 尋找 japic_code
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match: return None
        japic_code = japic_match.group(1)

        # Step 2: 進入 JAPIC 總覽頁
        time.sleep(0.5) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 成分名：解析 欧文一般名
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名：進入產品分頁抓取 md_td_en
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers).text
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 3. 資料清理邏輯：物理鎖定與邏輯截斷 ---
def clean_pmda_v8(df):
    header_idx = None
    # 搜尋標題行 (通常在第 3 行，Index 2)
    for i in range(min(10, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i] if pd.notnull(c)])
        # 去除所有空格後判定關鍵字
        row_str = re.sub(r'[\s\u3000\n]+', '', row_str)
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 標準化欄位名稱
    df.columns = df.iloc[header_idx]
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in temp_df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    temp_df = temp_df.rename(columns=rename_map)
    
    # 🛑 截斷機制：確保只讀取「藍框」內的資料
    valid_rows = []
    for _, row in temp_df.iterrows():
        val_no = str(row.get('No.', '')).strip().replace('.0','')
        val_trade = str(row.get('JP_Trade', '')).strip()
        
        # 如果 No. 不是數字（可能是空白或注1），且已經抓過資料，就代表出框了
        if not val_no.isdigit():
            if len(valid_rows) > 0: break 
            continue 
            
        if val_trade == "" or val_trade.lower() == 'nan': break
            
        valid_rows.append(row)
        
    return pd.DataFrame(valid_rows).reset_index(drop=True)

# --- 4. Streamlit UI ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯工具")
    st.title("💊 PMDA 藥品翻譯 (藍框守護 + JAPIC 深度檢索)")

    uploaded_file = st.file_uploader("上傳 PMDA Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 讓使用者選擇月份分頁
        sheet_name = st.selectbox("選擇要處理的分頁：", xls.sheet_names)
        
        if sheet_name:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_pmda_v8(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 辨識成功！分頁「{sheet_name}」共有 {len(df)} 筆有效紀錄。")
                st.table(df.head(5)) # 預覽前五筆
                
                if st.button("🚀 開始翻譯"):
                    results = []
                    log_area = st.empty()
                    pbar = st.progress(0)
                    
                    for idx, row in df.iterrows():
                        log_area.write(f"🔍 正在處理 No.{row['No.']}: {row['JP_Trade'][:15]}...")
                        # 執行檢索
                        en_trade = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_ing = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        
                        results.append({
                            "No.": row['No.'],
                            "日文商品名": row['JP_Trade'],
                            "Trade Name (EN)": en_trade if en_trade else "[手動確認]",
                            "日文成分名": row['JP_Ingredient'],
                            "Ingredient (EN)": en_ing if en_ing else "[手動確認]"
                        })
                        pbar.progress((idx + 1) / len(df))
                        time.sleep(0.3)
                        
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df, use_container_width=True)
                    st.download_button("📥 下載翻譯結果", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), f"PMDA_{sheet_name}.csv")
            else:
                st.error("⚠️ 無法辨識有效紀錄。請確認標題列位於檔案前 10 行內。")

if __name__ == "__main__":
    main()
