import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- 1. 配置與 API 設定 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 2. 核心功能函數 ---

def get_kegg_info(jp_name, log_container):
    """透過 KEGG API 獲取專業翻譯"""
    try:
        # 使用 REST API 搜尋
        find_url = f"https://rest.kegg.jp/find/drug/{jp_name}"
        resp = requests.get(find_url, timeout=5)
        if resp.ok and resp.text.strip():
            drug_id = resp.text.split('\t')[0].replace('dr:', '')
            log_container.write(f"🧬 KEGG 命中: `{drug_id}`")
            
            detail_resp = requests.get(f"https://rest.kegg.jp/get/{drug_id}", timeout=5)
            if detail_resp.ok:
                content = detail_resp.text
                trade = re.search(r'TH_NAME\s+(.*?)\n', content)
                ing = re.search(r'EN_NAME\s+(.*?)\n', content)
                return (trade.group(1).strip() if trade else None, 
                        ing.group(1).strip() if ing else None)
    except:
        pass
    return None, None

def azure_translate(text, from_lang="ja"):
    """Azure 翻譯備援"""
    if not text or "YOUR_KEY" in AZURE_KEY: return text
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": text}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=5)
        return resp.json()[0]["translations"][0]["text"] if resp.ok else text
    except:
        return text

# --- 3. 資料清理邏輯 ---

def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if '成分名' in row_str and '名' in row_str and '販' in row_str:
            return i
    return None

def clean_sheet(df):
    header_idx = find_header_row(df)
    if header_idx is None: return None
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    rename_map = {}
    for col in df.columns:
        c = str(col)
        if '販' in c and '名' in c: rename_map[col] = 'JP_Trade'
        elif '成' in c and '名' in c: rename_map[col] = 'JP_Ing'
    
    df = df.rename(columns=rename_map)
    return df[df['JP_Trade'].notnull()].copy() if 'JP_Trade' in df.columns else None

# --- 4. 主程式介面 ---

def main():
    st.set_page_config(layout="wide", page_title="PMDA 翻譯助手")
    st.title("💊 PMDA 日本新藥逐月翻譯生成器")
    st.caption("支援 KEGG API 優先查詢 + Azure 翻譯備援")

    uploaded_file = st.file_uploader("上傳 PMDA 公告 Excel", type=['xlsx'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        # 讓使用者選擇要處理哪些月份 (分頁)
        all_sheets = xls.sheet_names
        selected_sheets = st.multiselect("請選擇要處理的分頁 (月份)", all_sheets, default=all_sheets)

        if st.button("🚀 開始逐月生成翻譯"):
            for sheet_name in selected_sheets:
                st.markdown(f"### 📅 正在處理分頁：{sheet_name}")
                
                # 讀取並清理
                raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                df = clean_sheet(raw_df)

                if df is None or df.empty:
                    st.warning(f"分頁 `{sheet_name}` 格式不符或無數據，跳過。")
                    continue

                # 建立該月份的工作區
                with st.status(f"正在翻譯 {sheet_name}...", expanded=True) as status:
                    log_area = st.empty()
                    progress_bar = st.progress(0)
                    results = []
                    total = len(df)

                    for idx, row in df.iterrows():
                        jp_trade = str(row['JP_Trade']).split('\n')[0]
                        jp_ing = str(row['JP_Ing'])
                        
                        log_area.write(f"⏱️ 正在處理 ({idx+1}/{total}): **{jp_trade}**")
                        
                        # 執行翻譯邏輯
                        k_trade, k_ing = get_kegg_info(jp_trade, log_area)
                        
                        final_trade = k_trade if k_trade else azure_translate(jp_trade)
                        trade_src = "KEGG" if k_trade else "Azure"
                        
                        final_ing = k_ing if k_ing else azure_translate(jp_ing)
                        ing_src = "KEGG" if k_ing else "Azure"

                        results.append({
                            "月份": sheet_name,
                            "日文販賣名": jp_trade,
                            "英文商標名": final_trade,
                            "商標來源": trade_src,
                            "日文成分名": jp_ing,
                            "英文成分名": final_ing,
                            "成分來源": ing_src
                        })
                        progress_bar.progress((idx + 1) / total)
                        time.sleep(0.1) # 避免 API 併發過快

                    status.update(label=f"✅ {sheet_name} 處理完成！", state="complete", expanded=False)
                
                # --- 當月份翻譯完畢，立即顯示表格與下載按鈕 ---
                month_df = pd.DataFrame(results)
                st.dataframe(month_df, use_container_width=True, hide_index=True)
                
                csv = month_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    label=f"📥 下載 {sheet_name} 翻譯結果",
                    data=csv,
                    file_name=f"PMDA_{sheet_name}_Translated.csv",
                    mime="text/csv",
                    key=f"dl_{sheet_name}" # 唯一的 key 防止 Streamlit 報錯
                )
                st.divider()

if __name__ == "__main__":
    main()
