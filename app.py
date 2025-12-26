import streamlit as st
import pandas as pd
import requests
import re
import time
import os
from urllib.parse import quote

# --- 核心邏輯：依照您的規則提取開頭片假名 ---
def get_katakana_prefix(text):
    if not text or pd.isna(text): return None
    text = str(text).strip()
    match = re.search(r'^([ァ-ヶー・]+)', text)
    return match.group(1) if match else None

# --- 核心邏輯：先網頁搜尋編號，再 API 獲取詳細資料 ---
def get_kegg_info_hybrid(jp_text, log_container, is_trade=True):
    kw = get_katakana_prefix(jp_text)
    if not kw: return None
    
    try:
        # Step 1: 從 Medicus 網頁搜尋獲取 D編號 (例如 D03917)
        # 這裡模擬瀏覽器請求
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(search_url, headers=headers, timeout=10)
        
        # 使用正則尋找 /entry/DXXXXX
        drug_id_match = re.search(r'/entry/(D\d+)', resp.text)
        if not drug_id_match:
            return None
        
        drug_id = drug_id_match.group(1)
        log_container.write(f"🔍 `{kw}` 找到編號: `{drug_id}`")

        # Step 2: 代入 rest.kegg.jp 獲取詳細資訊
        # 注意：rest API 的 find 如果給 ID，會回傳 ID 所在的條目
        api_url = f"https://rest.kegg.jp/get/{drug_id}"
        api_resp = requests.get(api_url, timeout=10)
        
        if api_resp.ok:
            content = api_resp.text
            # 找到 NAME 行進行解析
            # 格式範例: NAME    Drospirenone (JAN/USP/INN); Slynd (TN); Slinda (TN)
            for line in content.split('\n'):
                if line.startswith('NAME'):
                    # 移除 NAME 標籤
                    parts_str = line.replace('NAME', '').strip()
                    # 以分號拆分
                    parts = [p.strip() for p in parts_str.split(';')]
                    
                    if is_trade:
                        # 找商品名：帶有 (TN) 的部分
                        for p in parts:
                            if '(TN)' in p:
                                log_container.write(f"✅ 命中商品名: `{p.replace('(TN)', '').strip()}`")
                                return p.replace('(TN)', '').strip()
                        # 若沒標註 TN，取最後一個部分嘗試
                        return re.sub(r'\(.*?\)', '', parts[-1]).strip()
                    else:
                        # 找成分名：通常是第一個部分
                        res = re.sub(r'\(.*?\)', '', parts[0]).strip()
                        log_container.write(f"✅ 命中成分名: `{res}`")
                        return res
                        
    except Exception as e:
        log_container.write(f"⚠️ 檢索異常: {str(e)}")
    return None

# --- 資料清理邏輯 (保持 10 筆不膨脹) ---
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
        # 過濾空行，且確保 No. 是數字
        df = df.dropna(subset=['JP_Trade'])
        if 'No.' in df.columns:
            df = df[df['No.'].apply(lambda x: str(x).strip().replace('.0','').isdigit())]
        return df.reset_index(drop=True)
    return None

# --- 主程式 ---
def main():
    st.set_page_config(layout="wide")
    st.title("💊 PMDA 翻譯 (KEGG 網頁+API 混合版)")
    
    uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])
    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_dataframe(raw_df)
            if df is None or df.empty: continue
                
            st.write(f"### 📄 分頁：{sheet_name}")
            with st.status(f"正在檢索 {sheet_name}...", expanded=True) as status:
                log_area = st.empty()
                results = []
                for idx, row in df.iterrows():
                    # 執行檢索
                    en_trade = get_kegg_info_hybrid(row['JP_Trade'], log_area, is_trade=True)
                    en_ing = get_kegg_info_hybrid(row['JP_Ingredient'], log_area, is_trade=False)
                    
                    results.append({
                        "No.": row.get('No.', idx+1),
                        "商品名(日)": row['JP_Trade'],
                        "Trade Name (EN)": en_trade if en_trade else "[Azure] " + str(row['JP_Trade']),
                        "成分名(日)": row['JP_Ingredient'],
                        "Ingredient (EN)": en_ing if en_ing else "[Azure] " + str(row['JP_Ingredient'])
                    })
                status.update(label="完成", state="complete")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
