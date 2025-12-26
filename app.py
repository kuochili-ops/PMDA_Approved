import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 設定頁面 ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯器穩定版")

# --- 1. KEGG 關鍵字提取優化 ---
def get_clean_kegg_term(text):
    """將藥名精簡為 KEGG API 最容易識別的形式"""
    if not text or pd.isna(text): return ""
    # 移除括號及其內容 (公司名、代碼)
    name = re.split(r'\(|（|［|\[', str(text))[0]
    # 移除常見干擾詞
    noise = ['錠', 'カプセル', '注', 'シリンジ', '配合', '散', '顆粒', '軟膏', '液', '28', '21']
    for n in noise:
        name = name.replace(n, '')
    return name.strip()

# --- 2. 帶重試機制的 KEGG REST API ---
def kegg_api_lookup(jp_name, log_container, is_ingredient=False):
    term = get_clean_kegg_term(jp_name)
    if not term: return None

    # 使用 Session 保持連線，提高網路慢速時的效率
    session = requests.Session()
    try:
        log_container.write(f"🧬 KEGG 檢索: `{term}`")
        # Step 1: Find
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        # 增加 timeout 到 10 秒應對慢速網路
        resp = session.get(find_url, timeout=10)
        
        if resp.ok and resp.text.strip():
            # 取第一筆最相關的 ID
            drug_id = resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            
            # Step 2: Get
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            get_resp = session.get(get_url, timeout=10)
            
            if get_resp.ok:
                content = get_resp.text
                th_name = re.search(r'TH_NAME\s+(.*?)\n', content)
                en_name = re.search(r'EN_NAME\s+(.*?)\n', content)
                
                th_val = th_name.group(1).strip() if th_name else None
                en_val = en_name.group(1).strip() if en_name else None
                
                # 成分名拿 EN_NAME (一般名)，商品名拿 TH_NAME (歐文商標名)
                res = (en_val if en_val else th_val) if is_ingredient else (th_val if th_val else en_val)
                if res:
                    log_container.write(f"✅ KEGG 命中: `{res}`")
                    return res
    except Exception as e:
        log_container.write(f"⚠️ 網路請求延遲: {str(e)[:50]}...")
    return None

# --- 3. 標題與欄位識別 ---
def find_drug_table(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(x) for x in row if pd.notnull(x)])
        if '成分名' in row_str and '販' in row_str:
            df.columns = df.iloc[i]
            return df.iloc[i+1:].reset_index(drop=True)
    return None

# --- 主程式 ---
st.title("🇯🇵 PMDA 日本新藥清單翻譯 (防卡住穩定版)")

uploaded_file = st.file_uploader("請上傳您的 000277966 (2).xlsx", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet_name in xls.sheet_names:
        df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        df = find_drug_table(df_raw)
        
        if df is None or df.empty: continue
        
        st.subheader(f"📊 分頁: {sheet_name}")
        
        # 建立結果清單
        final_results = []
        
        # 使用專用容器顯示進度
        with st.status(f"正在翻譯 {sheet_name}...", expanded=True) as status:
            log_area = st.empty()
            
            # 遍歷資料
            for idx, row in df.iterrows():
                # 自動搜尋欄位
                row_dict = row.to_dict()
                jp_trade = next((v for k, v in row_dict.items() if '販' in str(k) and '名' in str(k)), None)
                jp_ing = next((v for k, v in row_dict.items() if '成' in str(k) and '名' in str(k)), None)
                
                if not jp_trade or not jp_ing: continue

                # 商品名查詢 (KEGG 優先)
                en_trade = kegg_api_lookup(jp_trade, log_area, is_ingredient=False)
                t_src = "KEGG API" if en_trade else "Azure (備援)"
                
                # 成分名查詢 (KEGG 優先，例如：ドロスピレノン)
                en_ing = kegg_api_lookup(jp_ing, log_area, is_ingredient=True)
                i_src = "KEGG API" if en_ing else "Azure (備援)"
                
                # 如果 KEGG 失敗，此處可串接您現有的 Azure 函數
                # ... (Azure 呼叫邏輯)
                
                final_results.append({
                    "販賣名 (日)": jp_trade,
                    "Trade Name (EN)": en_trade if en_trade else "Pending",
                    "來源(T)": t_src,
                    "成分名 (日)": jp_ing,
                    "Ingredient (EN)": en_ing if en_ing else "Pending",
                    "來源(I)": i_src
                })
                # 短暫停頓避免請求過於密集
                time.sleep(0.1)
                
            status.update(label="✅ 處理完成", state="complete", expanded=False)
        
        # 顯示結果
        res_df = pd.DataFrame(final_results)
        st.dataframe(res_df, use_container_width=True)
