import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote

# --- 核心邏輯：依照您的原則精確提取 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    # 規則：只取開頭連續的片假名（含長音、中點），遇到任何非片假名（如「錠」、數字、括號）立即停止
    match = re.search(r'^([ァ-ヶー・]+)', text)
    if match:
        return match.group(1)
    return None

# --- 核心邏輯：KEGG 網頁搜尋 ID + API 獲取內容 ---
def get_kegg_info_hybrid(jp_text, log_container, is_trade=True):
    # 提取純片假名關鍵字 (例如: スリンダ)
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    try:
        # Step 1: Medicus 網頁檢索換取 Entry ID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(search_url, headers=headers, timeout=10)
        
        # 尋找內容中的 /entry/DXXXXX
        drug_id_match = re.search(r'/entry/(D\d+)', resp.text)
        if not drug_id_match:
            log_container.write(f"❌ `{kw}` 在 KEGG 網頁找不到 Entry ID")
            return None
        
        drug_id = drug_id_match.group(1)
        
        # Step 2: 使用 REST API 獲取該 ID 的詳細文字
        api_url = f"https://rest.kegg.jp/get/{drug_id}"
        api_resp = requests.get(api_url, timeout=10)
        
        if api_resp.ok:
            content = api_resp.text
            # 找到 NAME 行並解析
            for line in content.split('\n'):
                if line.startswith('NAME'):
                    # 移除 NAME 標籤並拆分分號
                    raw_names = line.replace('NAME', '').strip()
                    parts = [p.strip() for p in raw_names.split(';')]
                    
                    if is_trade:
                        # 商品名：尋找帶有 (TN) 的項目
                        tn_parts = [p.replace('(TN)', '').strip() for p in parts if '(TN)' in p]
                        if tn_parts:
                            log_container.write(f"✅ `{kw}` 命中商品名: `{tn_parts[0]}`")
                            return tn_parts[0]
                        # 備案：如果沒有 TN，取最後一個非日文項目
                        return re.sub(r'\(.*?\)', '', parts[-1]).strip()
                    else:
                        # 成分名：通常是第一個項目 (JAN/INN)
                        res = re.sub(r'\(.*?\)', '', parts[0]).strip()
                        log_container.write(f"✅ `{kw}` 命中成分名: `{res}`")
                        return res
    except Exception as e:
        log_container.write(f"⚠️ `{kw}` 檢索異常: {str(e)}")
    return None

# --- 資料清理：精確控制 10 筆項目 ---
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
    
    # 統一欄位名稱
    rename_map = {}
    for col in df.columns:
        c_clean = re.sub(r'[\s\u3000\n]+', '', str(col))
        if '販' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Trade'
        elif '成' in c_clean and '名' in c_clean: rename_map[col] = 'JP_Ingredient'
        elif 'No' in c_clean: rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)

    if 'JP_Trade' in df.columns:
        df = df.dropna(subset=['JP_Trade'])
        # 關鍵：根據您截圖中的 No. (1, 2, 3...) 進行篩選，避免抓到千行空白
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- Streamlit UI ---
def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 藥品清單檢索修正版")
    
    uploaded_file = st.file_uploader("請上傳您的 Excel 檔案", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            
            if df is None or df.empty: continue
                
            st.markdown(f"### 📄 分頁：{sheet_name} (有效數據: {len(df)} 筆)")
            
            with st.status(f"正在執行混合檢索...", expanded=True) as status:
                log_area = st.empty()
                results = []
                for _, row in df.iterrows():
                    # 執行商品名檢索 (KEGG 優先)
                    en_trade = get_kegg_info_hybrid(row['JP_Trade'], log_area, is_trade=True)
                    # 執行成分名檢索 (KEGG 優先)
                    en_ing = get_kegg_info_hybrid(row['JP_Ingredient'], log_area, is_trade=False)
                    
                    results.append({
                        "No.": row.get('No.', ''),
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_trade if en_trade else "[未命中] " + str(row['JP_Trade']),
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_ing if en_ing else "[未命中] " + str(row['JP_Ingredient'])
                    })
                status.update(label="檢索完成", state="complete")
            
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
