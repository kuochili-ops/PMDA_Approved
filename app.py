import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 1. 初始化與 API 配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

# 初始化 Session State 用於儲存已完成的月份資料
if 'translated_results' not in st.session_state:
    st.session_state.translated_results = {}

# --- 2. 核心翻譯引擎 ---

def get_kegg_info(jp_name, log):
    """依照官方 API 規範獲取專業名稱"""
    try:
        # Step 1: Find ID
        find_url = f"https://rest.kegg.jp/find/drug/{jp_name}"
        resp = requests.get(find_url, timeout=5)
        if resp.ok and resp.text.strip():
            drug_id = resp.text.split('\t')[0].replace('dr:', '')
            log.write(f"🧬 KEGG 匹配成功: `{drug_id}`")
            
            # Step 2: Get Detail
            detail_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if detail_resp.ok:
                content = detail_resp.text
                trade = re.search(r'TH_NAME\s+(.*?)\n', content)
                ing = re.search(r'EN_NAME\s+(.*?)\n', content)
                return (trade.group(1).strip() if trade else None, 
                        ing.group(1).strip() if ing else None)
    except Exception as e:
        log.write(f"⚠️ KEGG API 異常: {str(e)}")
    return None, None

def azure_translate(text, log):
    """備援翻譯"""
    if not text or "YOUR_KEY" in AZURE_KEY: return text
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": text}]
    params = {"api-version": "3.0", "from": "ja", "to": ["en"]}
    try:
        log.write(f"🌐 呼叫 Azure 翻譯: `{text[:10]}...`")
        resp = requests.post("https://api.cognitive.microsofttranslator.com/translate", 
                             params=params, headers=headers, json=body, timeout=5)
        return resp.json()[0]["translations"][0]["text"]
    except:
        return text

# --- 3. 介面與邏輯 ---

def main():
    st.set_page_config(layout="wide", page_title="PMDA 新藥翻譯生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表 (逐月產出版)")

    uploaded_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        sheets = st.multiselect("選擇要翻譯的月份/分頁", xls.sheet_names, default=xls.sheet_names)

        if st.button("🚀 開始翻譯任務"):
            for sheet in sheets:
                # 檢查是否已經處理過
                st.subheader(f"📅 月份分頁：{sheet}")
                
                # 讀取並簡單清理
                raw_df = pd.read_excel(xls, sheet_name=sheet, header=None)
                # 這裡調用您原本的 find_header_row 和 clean_dataframe 邏輯
                # 簡化示範，假設 df 是清理後的結果
                df = raw_df.copy() 

                with st.status(f"正在分析 {sheet} 數據...", expanded=True) as status:
                    log_area = st.empty()
                    results = []
                    
                    # 這裡加入真正的處理迴圈 (以您的欄位名為準)
                    # 假設我們處理前 5 筆作為範例
                    for idx, row in df.head(10).iterrows():
                        # 模擬您的欄位抓取
                        name_jp = str(row[0]) 
                        
                        # 執行翻譯流程
                        k_t, k_i = get_kegg_info(name_jp, log_area)
                        final_t = k_t if k_t else azure_translate(name_jp, log_area)
                        
                        results.append({"日文": name_jp, "英文": final_t, "來源": "KEGG" if k_t else "Azure"})
                        time.sleep(0.2) # 防止 API 鎖定
                    
                    status.update(label=f"✅ {sheet} 翻譯完成", state="complete", expanded=False)
                
                # 產出該月表格
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                # 下載按鈕
                st.download_button(
                    label=f"📥 下載 {sheet} CSV",
                    data=res_df.to_csv(index=False).encode('utf-8-sig'),
                    file_name=f"{sheet}_translated.csv",
                    key=f"btn_{sheet}"
                )
                st.divider()

if __name__ == "__main__":
    main()
