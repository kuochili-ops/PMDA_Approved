import streamlit as st
import pandas as pd
import requests
import re
import time

# --- 核心設定 ---
AZURE_KEY = st.secrets.get("AZURE_KEY", "YOUR_KEY")
AZURE_REGION = st.secrets.get("AZURE_REGION", "YOUR_REGION")

# 初始化快取，減少重複請求
if 'kegg_cache' not in st.session_state:
    st.session_state.kegg_cache = {}

# --- 1. KEGG 校正函數 (REST API) ---
def kegg_correction(jp_name, is_ingredient=False):
    """針對 Azure 結果進行權威校正"""
    if not jp_name or pd.isna(jp_name): return None
    
    # 清理名稱：移除劑型與括號內容
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|21|28', '', term).strip()
    
    if term in st.session_state.kegg_cache:
        return st.session_state.kegg_cache[term]

    try:
        # Step 1: Find
        find_url = f"https://rest.kegg.jp/find/drug/{term}"
        resp = requests.get(find_url, timeout=3)
        if resp.ok and resp.text.strip():
            drug_id = resp.text.split('\n')[0].split('\t')[0].replace('dr:', '')
            # Step 2: Get
            get_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=3)
            if get_resp.ok:
                content = get_resp.text
                th = re.search(r'TH_NAME\s+(.*?)\n', content)
                en = re.search(r'EN_NAME\s+(.*?)\n', content)
                # 決定結果：成分名優先給 EN (Drospirenone)
                res = (en.group(1) if en else th.group(1)) if is_ingredient else (th.group(1) if th else en.group(1))
                st.session_state.kegg_cache[term] = res.strip()
                return res.strip()
    except:
        pass
    return None

# --- 2. Azure 快速翻譯 ---
def azure_translate(text):
    if not text or pd.isna(text): return ""
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=ja&to=en", 
                          headers=headers, json=body, timeout=5)
        return r.json()[0]["translations"][0]["text"]
    except:
        return str(text)

# --- 3. UI 主流程 ---
st.title("💊 PMDA 穩定翻譯版 (Azure + KEGG 校正)")

uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet_name in xls.sheet_names:
        # 讀取並定位表格
        df_raw = pd.read_excel(xls, sheet_name=sheet_name)
        
        # 找出包含 '販賣名' 和 '成分名' 的欄位
        trade_col = next((c for c in df_raw.columns if '販' in str(c)), None)
        ing_col = next((c for c in df_raw.columns if '成' in str(c)), None)
        
        if not trade_col or not ing_col:
            continue

        st.subheader(f"📄 月份：{sheet_name}")
        
        results = []
        # 使用 status 容器，讓過程可視化但不卡死頁面
        with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
            progress = st.progress(0)
            log_text = st.empty()
            
            for idx, row in df_raw.iterrows():
                jp_trade = str(row[trade_col])
                jp_ing = str(row[ing_col])
                
                # 第一步：先讓 Azure 翻譯 (確保速度)
                en_trade = azure_translate(jp_trade)
                en_ing = azure_translate(jp_ing)
                
                # 第二步：KEGG 校正 (確保專業)
                kegg_trade = kegg_correction(jp_trade, is_ingredient=False)
                kegg_ing = kegg_correction(jp_ing, is_ingredient=True)
                
                final_t = kegg_trade if kegg_trade else en_trade
                final_i = kegg_ing if kegg_ing else en_ing
                
                source_t = "KEGG" if kegg_trade else "Azure"
                source_i = "KEGG" if kegg_ing else "Azure"
                
                log_text.write(f"正在翻譯: {jp_trade} ... {source_t}")
                
                results.append({
                    "商品名(日)": jp_trade,
                    "Trade Name (EN)": final_t,
                    "商品來源": source_t,
                    "成分名(日)": jp_ing,
                    "Ingredient (EN)": final_i,
                    "成分來源": source_i
                })
                progress.progress((idx + 1) / len(df_raw))
            
            status.update(label="✅ 處理完成", state="complete")

        # 顯示表格與下載
        final_df = pd.DataFrame(results)
        st.dataframe(final_df, use_container_width=True)
        csv = final_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(f"📥 下載 {sheet_name} 結果", csv, f"{sheet_name}.csv", "text/csv")
