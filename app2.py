import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 1. 片假名提取：精確過濾劑型與公司名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    # 只取第一行，並移除括號內的公司資訊
    text = str(text).split('\n')[0].split('（')[0].split('(')[0].strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 2. 深度檢索邏輯：自動導航至 JAPIC 產品頁 ---
def get_kegg_advanced_info(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.kegg.jp/medicus-bin/search_drug"
    }
    session = requests.Session()

    try:
        # Step 1: 搜尋
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        resp = session.get(search_url, headers=headers, timeout=15)
        
        # 尋找 JAPIC 編號
        japic_match = re.search(r'japic_code=(\d+)', resp.text)
        if not japic_match: return None
        japic_code = japic_match.group(1)

        # Step 2: 進入 JAPIC 總覽頁
        time.sleep(0.5) 
        med_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        med_html = session.get(med_url, headers=headers).text

        if not is_trade:
            # 成分名：找「欧文一般名」
            ing_match = re.search(r'<th>欧文一般名</th>\s*<td>(.*?)</td>', med_html, re.S)
            return re.sub(r'<.*?>', '', ing_match.group(1)).strip() if ing_match else None
        else:
            # 商品名：需點進「產品分頁」
            prod_id_match = re.search(r'japic_med_product\?id=([\d-]+)', med_html)
            if prod_id_match:
                prod_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={prod_id_match.group(1)}"
                prod_resp = session.get(prod_url, headers=headers).text
                # 抓取 md_td_en 標籤（通常包含英文商品名）
                trade_match = re.search(r'<td class="md_td_en">(.*?)</td>', prod_resp, re.S)
                return trade_match.group(1).strip() if trade_match else None
    except: pass
    return None

# --- 3. 藍框判定清理邏輯：排除 5、6 月份的千行空數據 ---
def clean_dataframe_v7(df):
    header_idx = None
    # PMDA 標題通常在 1~4 行之間
    for i in range(min(10, len(df))):
        row_str = "".join([str(c) for c in df.iloc[i] if pd.notnull(c)])
        # 移除所有空白符號後比對
        row_str = re.sub(r'[\s\u3000\n]+', '', row_str)
        if '販賣名' in row_str and '成分名' in row_str:
            header_idx = i
            break
            
    if header_idx is None: return None
    
    # 重新設定欄位名
    df.columns = df.iloc[header_idx]
    temp_df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 欄位映射
    rename_map = {}
    for col in temp_df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販賣名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成分名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    
    temp_df = temp_df.rename(columns=rename_map)
    
    # --- 🛑 核心：模擬 Excel 藍框邊界守護 ---
    valid_rows = []
    for _, row in temp_df.iterrows():
        # 讀取 No. 欄位並轉為字串
        val_no = str(row.get('No.', '')).strip().replace('.0','')
        val_trade = str(row.get('JP_Trade', '')).strip()
        
        # 截斷判斷：
        # 1. 如果 No. 欄位不是純數字 (如空白、文字、或 CSV 的末端符號)
        # 2. 如果商品名完全為空
        if not val_no.isdigit():
            if len(valid_rows) > 0: break # 如果已經開始抓資料了，遇到非數字代表「出框」了
            continue # 如果還沒抓到第一筆，可能是標題下方的空行，跳過
            
        if val_trade == "" or val_trade.lower() == 'nan': break
            
        valid_rows.append(row)
        
    return pd.DataFrame(valid_rows).reset_index(drop=True)

# --- 4. Streamlit 主程式 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯版 v7")
    st.title("💊 PMDA 藥品清單翻譯 (藍框鎖定 + KEGG 深度路徑)")
    
    up = st.file_uploader("上傳 PMDA Excel (例如: 承認品目5月分)", type=['xlsx'])
    
    if up:
        xls = pd.ExcelFile(up)
        # 讓使用者選擇分頁
        sheet = st.selectbox("請選擇月份分頁：", xls.sheet_names)
        
        if sheet:
            raw_df = pd.read_excel(xls, sheet_name=sheet, header=None)
            df = clean_dataframe_v7(raw_df)
            
            if df is not None and not df.empty:
                st.success(f"✅ 辨識成功！藍框內有效數據：{len(df)} 筆")
                st.dataframe(df.head(5), use_container_width=True)
                
                if st.button("🚀 開始深度翻譯檢索"):
                    results = []
                    log_area = st.empty()
                    pbar = st.progress(0)
                    
                    for idx, row in df.iterrows():
                        # 顯示進度
                        log_area.markdown(f"正在處理 No.{row['No.']} : `{row['JP_Trade'][:15]}...`")
                        
                        # 執行檢索
                        en_t = get_kegg_advanced_info(row['JP_Trade'], log_area, is_trade=True)
                        en_i = get_kegg_advanced_info(row['JP_Ingredient'], log_area, is_trade=False)
                        
                        results.append({
                            "No.": row['No.'],
                            "商品名(日)": row['JP_Trade'],
                            "Trade Name (EN)": en_t if en_t else "[查無結果/手動核對]",
                            "成分名(日)": row['JP_Ingredient'],
                            "Ingredient (EN)": en_i if en_i else "[查無結果/手動核對]"
                        })
                        pbar.progress((idx + 1) / len(df))
                        time.sleep(0.3)
                        
                    res_df = pd.DataFrame(results)
                    st.divider()
                    st.subheader("📊 翻譯結果")
                    st.dataframe(res_df, use_container_width=True)
                    st.download_button("📥 下載翻譯 CSV", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), f"PMDA_{sheet}_Result.csv")
            else:
                st.error("⚠️ 無法定位標題列。請確認 Excel 第三行左右包含「販賣名」。")

if __name__ == "__main__":
    main()
