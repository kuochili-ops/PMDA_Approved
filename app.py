import streamlit as st
import pandas as pd
import requests
import re
import time

# --- 1. 核心翻譯函數 (保持簡單穩定) ---
def get_kegg_correction(jp_name, is_ingredient=False):
    # 極度清理
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21', '', term).strip()
    if not term: return None
    try:
        # Step 1: Find ID
        f_resp = requests.get(f"https://rest.kegg.jp/find/drug/{term}", timeout=5)
        if f_resp.ok and f_resp.text.strip():
            drug_id = f_resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            # Step 2: Get Details
            g_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if g_resp.ok:
                content = g_resp.text
                th = re.search(r'TH_NAME\s+(.*?)\n', content)
                en = re.search(r'EN_NAME\s+(.*?)\n', content)
                return (en.group(1) if en else th.group(1)).strip() if is_ingredient else (th.group(1) if th else en.group(1)).strip()
    except:
        return None
    return None

# --- 2. 表格結構解析函數 ---
def analyze_structure(df):
    """嘗試找出包含關鍵字的標題行"""
    for i in range(len(df)):
        row_content = "".join(df.iloc[i].astype(str))
        if '販' in row_content and '名' in row_content:
            return i
    return None

# --- 3. UI 邏輯 ---
st.title("💊 PMDA 翻譯校正 (穩定版)")

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=['xlsx'])

if uploaded_file:
    # 步驟 1: 讀取 Excel (使用 engine='openpyxl' 增加相容性)
    try:
        xls = pd.ExcelFile(uploaded_file, engine='openpyxl')
        st.success(f"成功讀取檔案，包含分頁: {xls.sheet_names}")
    except Exception as e:
        st.error(f"檔案讀取失敗: {e}")
        st.stop()

    for sheet_name in xls.sheet_names:
        with st.expander(f"📊 檢視分頁：{sheet_name}", expanded=True):
            df_raw = pd.read_excel(xls, sheet_name=sheet_name)
            
            # 找標題行
            header_idx = analyze_structure(df_raw)
            
            if header_idx is not None:
                st.info(f"偵測到表格標題位於第 {header_idx + 1} 行")
                # 重新整理 DataFrame
                df_clean = pd.read_excel(xls, sheet_name=sheet_name, skiprows=header_idx + 1)
                st.dataframe(df_clean.head(5)) # 先秀出前五筆確認
                
                # 按鈕觸發翻譯，避免上傳後直接卡死
                if st.button(f"開始翻譯校正 {sheet_name}", key=sheet_name):
                    results = []
                    status_ui = st.status(f"正在處理 {sheet_name}...")
                    
                    # 找出販賣名與成分名欄位 (透過位置或關鍵字)
                    # 這裡假設第 1 欄是商品名, 第 4 欄是成分名 (請依實際調整)
                    for idx, row in df_clean.iterrows():
                        jp_trade = str(row.iloc[1]) if len(row) > 1 else ""
                        jp_ing = str(row.iloc[4]) if len(row) > 4 else ""
                        
                        if not jp_trade or "nan" in jp_trade.lower(): continue
                        
                        # 校正邏輯
                        k_trade = get_kegg_correction(jp_trade, False)
                        k_ing = get_kegg_correction(jp_ing, True)
                        
                        results.append({
                            "販賣名(日)": jp_trade,
                            "Trade Name (EN)": k_trade if k_trade else "Azure 翻譯待補",
                            "成分名(日)": jp_ing,
                            "Ingredient (EN)": k_ing if k_ing else "Azure 翻譯待補",
                            "來源": "KEGG" if (k_trade or k_ing) else "Azure"
                        })
                        status_ui.write(f"已處理: {jp_trade}")
                    
                    status_ui.update(label="處理完成!", state="complete")
                    res_df = pd.DataFrame(results)
                    st.dataframe(res_df)
            else:
                st.warning(f"分頁 {sheet_name} 未能自動偵測到 '販賣名' 欄位。")
