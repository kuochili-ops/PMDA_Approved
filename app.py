import streamlit as st
import pandas as pd
import requests
import re
import time
from concurrent.futures import ThreadPoolExecutor

# --- 設定與初始化 ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯器 (穩定效能版)")

# 從 Secrets 讀取 Key
AZURE_KEY = st.secrets.get("AZURE_KEY", "YOUR_KEY")
AZURE_REGION = st.secrets.get("AZURE_REGION", "YOUR_REGION")

# 建立快取以避免重複查詢
if 'translation_cache' not in st.session_state:
    st.session_state.translation_cache = {}

# --- 1. 快速翻譯 (Azure) ---
def azure_translate(text):
    if not text or pd.isna(text): return text
    if text in st.session_state.translation_cache:
        return st.session_state.translation_cache[text]
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    try:
        r = requests.post("https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=ja&to=en", 
                          headers=headers, json=body, timeout=5)
        res = r.json()[0]["translations"][0]["text"]
        st.session_state.translation_cache[text] = res
        return res
    except:
        return text

# --- 2. 專業校正 (KEGG REST API) ---
def kegg_refine(jp_name, is_ingredient=False):
    # 極簡化清理以提高命中率
    term = re.split(r'\(|（|［|\[', str(jp_name))[0]
    term = re.sub(r'錠|カプセル|注|シリンジ|配合|28|21', '', term).strip()
    
    if not term or len(term) < 2: return None
    
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
                # 校正邏輯：成分名優先 EN，商品名優先 TH
                kegg_res = (en.group(1) if en else th.group(1)) if is_ingredient else (th.group(1) if th else en.group(1))
                return kegg_res.strip()
    except:
        return None
    return None

# --- 3. 處理主邏輯 ---
st.title("💊 PMDA 翻譯助手 (Azure 翻譯 + KEGG 校正)")

uploaded_file = st.file_uploader("上傳 Excel", type=['xlsx'])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        
        # 尋找關鍵欄位 (販賣名/成分名)
        trade_col = next((c for c in df.columns if '販' in str(c)), None)
        ing_col = next((c for c in df.columns if '成' in str(c)), None)
        
        if not trade_col or not ing_col: continue

        st.subheader(f"頁籤: {sheet}")
        
        # 第一階段：Azure 快速翻譯生成預覽
        with st.status("🚀 第一階段：Azure 快速翻譯中...", expanded=True) as status:
            progress_bar = st.progress(0)
            rows = []
            total = len(df)
            
            for i, row in df.iterrows():
                jp_t, jp_i = str(row[trade_col]), str(row[ing_col])
                
                # 先用 Azure
                en_t = azure_translate(jp_t)
                en_i = azure_translate(jp_i)
                
                rows.append({
                    "販賣名(日)": jp_t,
                    "Trade Name (EN)": en_t,
                    "成分名(日)": jp_i,
                    "Ingredient (EN)": en_i,
                    "校正狀態": "等待校正..."
                })
                progress_bar.progress((i+1)/total)
            
            status.update(label="✅ 第一階段完成，開始 KEGG 校正", state="running")
            
            # 第二階段：KEGG 校正
            st.write("🔍 第二階段：KEGG API 專業校正中...")
            for idx, item in enumerate(rows):
                # 校正商品名
                k_t = kegg_refine(item["販賣名(日)"], is_ingredient=False)
                if k_t:
                    item["Trade Name (EN)"] = k_t
                
                # 校正成分名 (如: ドロスピレノン)
                k_i = kegg_refine(item["成分名(日)"], is_ingredient=True)
                if k_i:
                    item["Ingredient (EN)"] = k_i
                
                item["校正狀態"] = "✅ KEGG 已校正" if (k_t or k_i) else "⚠️ Azure 翻譯"
                
            status.update(label="🎉 全部處理完成", state="complete", expanded=False)

        # 呈現最終表格
        final_df = pd.DataFrame(rows)
        st.dataframe(final_df, use_container_width=True)
        
        # 下載按鈕
        csv = final_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(f"📥 下載 {sheet} 結果", csv, f"{sheet}_translated.csv", "text/csv")
