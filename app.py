import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# --- API 配置 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY = os.environ.get("AZURE_KEY", "YOUR_KEY")
    AZURE_REGION = os.environ.get("AZURE_REGION", "YOUR_REGION")

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# --- 深度清理函數：提高 KEGG 命中率的關鍵 ---
def refine_drug_name_for_kegg(name):
    """移除干擾 KEGG 搜尋的術語，只保留核心藥名"""
    if not name or pd.isna(name): return ""
    # 1. 移除所有括號內容 (包含日文與英文括號)
    name = re.sub(r'［.*?］|（.*?）|\(.*?\)', '', str(name))
    # 2. 移除常見藥學修飾詞
    modifiers = ['日局', '水和物', 'エステル', '塩酸塩', 'マレイン酸塩', '臭化水素酸塩', '遺伝子組換え']
    for mod in modifiers:
        name = name.replace(mod, '')
    return name.strip()

# --- KEGG API 優先查詢邏輯 ---
def get_kegg_priority_translation(jp_name, log_container, is_ingredient=False):
    """
    實踐 KEGG API 優先：
    成分名優先抓 '英文一般名'；商品名優先抓 '欧文商標名'。
    """
    if not jp_name or pd.isna(jp_name): return None
    
    # 步驟 1: 清理名稱
    clean_name = refine_drug_name_for_kegg(jp_name)
    if len(clean_name) < 2: return None
    
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={clean_name}"
    
    try:
        log_container.write(f"🧬 KEGG 優先檢索中: `{clean_name}`")
        resp = requests.get(search_url, timeout=10)
        if resp.ok:
            # 尋找 JAPIC Code 連結
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                drug_resp = requests.get(drug_url, timeout=10)
                
                if drug_resp.ok:
                    # 抓取兩種名稱
                    trade_en = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    generic_en = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', drug_resp.text, re.DOTALL)
                    
                    t_val = trade_en.group(1).strip() if trade_en else None
                    g_val = generic_en.group(1).strip() if generic_en else None
                    
                    # 根據欄位屬性回傳最精確的名稱
                    if is_ingredient:
                        result = g_val if g_val else t_val
                    else:
                        result = t_val if t_val else g_val
                        
                    if result:
                        log_container.write(f"✅ KEGG 命中成功: `{result}`")
                        return result
    except Exception as e:
        log_container.write(f"⚠️ KEGG 連線異常: {e}")
    
    return None

def ms_translator_fallback(text, from_lang="ja"):
    """Azure 翻譯僅作為 KEGG 未命中時的備援"""
    if not text or pd.isna(text) or "YOUR" in AZURE_KEY: return text
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-type": "application/json"
    }
    body = [{"text": str(text)}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=10)
        return resp.json()[0]["translations"][0]["text"] if resp.ok else text
    except:
        return text

# --- 資料清理邏輯 (偵測標題列) ---
def clean_pmda_dataframe(df):
    header_idx = None
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        if ('成分名' in row_str or '成' in row_str) and '販' in row_str:
            header_idx = i
            break
    
    if header_idx is None: return None
    
    df.columns = df.iloc[header_idx]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    
    # 統一欄位名稱
    rename_dict = {}
    for col in df.columns:
        c = str(col).replace('\n', '').strip()
        if '販' in c and '名' in c: rename_dict[col] = 'JP_Trade'
        elif '成' in c and '名' in c: rename_dict[col] = 'JP_Ingredient'
    
    df = df.rename(columns=rename_dict)
    return df.dropna(subset=['JP_Trade', 'JP_Ingredient']).reset_index(drop=True)

# --- 主程式介面 ---
def main():
    st.set_page_config(layout="wide", page_title="PMDA 專業翻譯助手")
    st.title("💊 PMDA 日本新藥翻譯 (KEGG API 優先)")

    uploaded_file = st.file_uploader("上傳 PMDA 公告 Excel", type=['xlsx'])

    if uploaded_file:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            df = clean_pmda_dataframe(raw_df)
            
            if df is None or df.empty: continue
            
            st.divider()
            st.subheader(f"📅 月份分頁：{sheet_name}")
            
            with st.status(f"正在處理 {sheet_name}...", expanded=True) as status:
                log_box = st.empty()
                progress = st.progress(0)
                final_data = []
                
                for idx, row in df.iterrows():
                    # 1. 處理商品名 (Trade Name)
                    raw_trade = row['JP_Trade']
                    en_trade = get_kegg_priority_translation(raw_trade, log_box, is_ingredient=False)
                    trade_src = "KEGG API" if en_trade else "Azure (備援)"
                    if not en_trade: en_trade = ms_translator_fallback(raw_trade)
                    
                    # 2. 處理成分名 (Ingredient Name)
                    raw_ing = row['JP_Ingredient']
                    en_ing = get_kegg_priority_translation(raw_ing, log_box, is_ingredient=True)
                    ing_src = "KEGG API" if en_ing else "Azure (備援)"
                    if not en_ing: en_ing = ms_translator_fallback(raw_ing)
                    
                    final_data.append({
                        "商品名 (日)": raw_trade,
                        "Trade Name (EN)": en_trade,
                        "來源": trade_src,
                        "成分名 (日)": raw_ing,
                        "Ingredient (EN)": en_ing,
                        "來源 ": ing_src
                    })
                    progress.progress((idx + 1) / len(df))
                    time.sleep(0.1)
                
                status.update(label=f"✅ {sheet_name} 處理完成！", state="complete", expanded=False)
            
            # 顯示結果表格
            res_df = pd.DataFrame(final_data)
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            
            # 下載按鈕
            csv = res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(label=f"📥 下載 {sheet_name} 翻譯結果", data=csv, 
                               file_name=f"PMDA_{sheet_name}.csv", mime='text/csv', key=f"dl_{sheet_name}")

if __name__ == "__main__":
    main()
