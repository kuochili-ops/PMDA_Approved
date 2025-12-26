import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- Azure Setup (保持不變) ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# --- 改良版：增加日誌輸出的 KEGG API 函數 ---
def get_kegg_info_with_logs(jp_name, log_placeholder):
    """
    獲取資訊並將進度寫入 log_placeholder
    """
    try:
        # 1. Search Drug ID
        log_placeholder.write(f"🔍 正在 KEGG 搜尋藥品關鍵字: `{jp_name}`...")
        find_url = f"https://rest.kegg.jp/find/drug/{jp_name}"
        resp = requests.get(find_url, timeout=5)
        
        if resp.ok and resp.text.strip():
            drug_id = resp.text.split('\t')[0].replace('dr:', '')
            log_placeholder.write(f"✅ 找到 KEGG ID: `{drug_id}`，正在抓取詳細資料...")
            
            # 2. Get Details
            get_url = f"https://rest.kegg.jp/get/{drug_id}"
            detail_resp = requests.get(get_url, timeout=5)
            if detail_resp.ok:
                content = detail_resp.text
                trade = re.search(r'TH_NAME\s+(.*?)\n', content)
                ing = re.search(r'EN_NAME\s+(.*?)\n', content)
                return (trade.group(1).strip() if trade else None, 
                        ing.group(1).strip() if ing else None)
        else:
            log_placeholder.write(f"⚠️ KEGG 找不到 `{jp_name}`，準備切換至 Azure 翻譯。")
    except Exception as e:
        log_placeholder.write(f"❌ KEGG 連線異常: {e}")
    return None, None

# --- 改良版：主要翻譯迴圈 ---
def translate_and_combine_with_status(df):
    results = []
    
    # 建立總進度條
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 建立「工作狀況」狀態容器 (Streamlit 1.24+ 新功能)
    with st.status("🚀 正在啟動翻譯引擎...", expanded=True) as status:
        log_area = st.empty() # 用於顯示當前步驟的文字記錄
        
        for idx, row in df.iterrows():
            jp_trade = str(row.get('販賣名/公司 (日文)', '')).strip()
            jp_ing = str(row.get('成分名 (日文)', '')).strip()
            
            status_text.text(f"正在處理第 {idx+1}/{len(df)} 筆資料...")
            
            # --- 執行工作並更新日誌 ---
            k_trade, k_ing = get_kegg_info_with_logs(jp_trade, log_area)
            
            # 處理商標名
            if k_trade:
                final_trade, trade_src = k_trade, "KEGG"
            else:
                log_area.write(f"🌐 呼叫 Azure 翻譯商標名...")
                # 這裡調用您原有的 ms_translator
                final_trade, trade_src = "Azure 翻譯結果", "Azure" 
            
            # 處理成分名
            if k_ing:
                final_ing, ing_src = k_ing, "KEGG"
            else:
                log_area.write(f"🌐 呼叫 Azure 翻譯成分名...")
                final_ing, ing_src = "Azure 翻譯結果", "Azure"

            results.append({
                "日文販賣名": jp_trade,
                "英文商標名": final_trade,
                "來源(商標)": trade_src,
                "日文成分名": jp_ing,
                "英文成分名": final_ing,
                "來源(成分)": ing_src
            })
            
            # 更新進度
            progress_bar.progress((idx + 1) / len(df))
            time.sleep(0.1) # 稍微停頓讓使用者看得見日誌變化
            
        status.update(label="✅ 翻譯任務全部完成！", state="complete", expanded=False)

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)

# --- Main App 修改處 ---
def main():
    # ... 前面檔案上傳邏輯保持不變 ...
    if st.button("開始執行翻譯流水線"):
        # 假設已經讀取了 df
        translated_df = translate_and_combine_with_status(df)
        st.dataframe(translated_df)
