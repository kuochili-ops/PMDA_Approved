import streamlit as st
import pandas as pd
import requests
import re
import time

# --- 基礎設定 ---
try:
    AZURE_KEY = st.secrets["AZURE_KEY"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
except:
    AZURE_KEY, AZURE_REGION = "YOUR_KEY", "YOUR_REGION"

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

def get_kegg_drug_info(jp_name, log_container):
    if not jp_name or pd.isna(jp_name): return None
    # 只抓取第一行作為搜尋關鍵字 (排除括號內的廠商名)
    search_term = str(jp_name).split('\n')[0].split('（')[0].split('(')[0].strip()
    search_term = re.sub(r'［.*?］|（.*?）', '', search_term)
    if len(search_term) < 2: return None
    
    try:
        log_container.write(f"🔍 KEGG 檢索: `{search_term}`")
        url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={search_term}"
        resp = requests.get(url, timeout=10)
        if resp.ok:
            m = re.search(r'japic_code=(\d+)', resp.text)
            if m:
                d_resp = requests.get(f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={m.group(1)}", timeout=10)
                t = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', d_resp.text, re.DOTALL)
                g = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', d_resp.text, re.DOTALL)
                return (t.group(1) if t else (g.group(1) if g else None)).strip()
    except: pass
    return None

def ms_translator(text):
    if not text or pd.isna(text): return ""
    headers = {"Ocp-Apim-Subscription-Key": AZURE_KEY, "Ocp-Apim-Subscription-Region": AZURE_REGION, "Content-type": "application/json"}
    body = [{"text": str(text).replace('\n', ' ')}]
    try:
        r = requests.post(ENDPOINT, params={"api-version":"3.0","from":"ja","to":["en"]}, headers=headers, json=body, timeout=10)
        return r.json()[0]["translations"][0]["text"] if r.ok else text
    except: return text

# --- 核心：模擬 Excel 藍框 (Print Area) 判定 ---
def clean_pmda_data_v4(df):
    # 1. 強制從第三行 (Index 2) 抓取標題
    if len(df) < 3: return None
    
    # 清理標題列的空格與換行
    raw_header = df.iloc[2]
    clean_header = [re.sub(r'[\s\u3000\n]+', '', str(x)) for x in raw_header]
    
    # 尋找關鍵欄位索引
    idx_no, idx_trade, idx_ing = None, None, None
    for i, h in enumerate(clean_header):
        if 'No' in h: idx_no = i
        if '販賣名' in h: idx_trade = i
        if '成分名' in h: idx_ing = i
        
    if idx_trade is None or idx_ing is None: return None

    # 2. 開始從第四行向下讀取，並執行「藍框邊界」判定
    valid_list = []
    for i in range(3, len(df)):
        row = df.iloc[i]
        val_no = str(row[idx_no]).strip() if idx_no is not None else ""
        val_trade = str(row[idx_trade]).strip()
        val_ing = str(row[idx_ing]).strip()

        # --- 🛑 關鍵截斷邏輯：如果符合以下任一條件，視為超出藍框 ---
        # A. 販賣名為空或 NaN
        if not val_trade or val_trade.lower() == 'nan': break
        # B. No 欄位不是純數字且販賣名包含「注、承認」等備註字眼
        if not val_no.isdigit() and any(x in val_trade for x in ['注', '承認', '新医薬品']): break
        
        valid_list.append({
            "No.": val_no,
            "Trade_JP": val_trade,
            "Ingredient_JP": val_ing
        })
        
    return pd.DataFrame(valid_list)

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯 v4.0")
st.sidebar.markdown("[🔗 PMDA 官網連結](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0010.html)")
st.title("🇯🇵 PMDA 翻譯工具 (藍框區域限定版)")

up_file = st.file_uploader("上傳 PMDA Excel/CSV", type=['xlsx', 'xls', 'csv'])

if up_file:
    # 支援 CSV 或 Excel
    if up_file.name.endswith('.csv'):
        raw = pd.read_csv(up_file, header=None)
        sheets = ["CSV_Mode"]
    else:
        xls_obj = pd.ExcelFile(up_file)
        sheets = xls_obj.sheet_names
    
    s_name = st.selectbox("選擇分頁", sheets)
    if s_name:
        if not up_file.name.endswith('.csv'):
            raw = pd.read_excel(xls_obj, sheet_name=s_name, header=None)
        
        clean_df = clean_pmda_data_v4(raw)
        
        if clean_df is not None and not clean_df.empty:
            st.success(f"✅ 偵測到 {len(clean_df)} 筆有效紀錄 (已切斷藍框外空行)")
            st.table(clean_df.head(10)) # 顯示前10筆確認
            
            if st.button("開始翻譯"):
                final_results = []
                status = st.status("正在處理...", expanded=True)
                log = st.empty()
                p = st.progress(0)
                
                for idx, row in clean_df.iterrows():
                    # 執行 KEGG -> Azure 邏輯
                    en_t = get_kegg_drug_info(row['Trade_JP'], log) or ms_translator(row['Trade_JP'])
                    en_i = get_kegg_drug_info(row['Ingredient_JP'], log) or ms_translator(row['Ingredient_JP'])
                    
                    final_results.append({
                        "No.": row['No.'],
                        "日文販賣名": row['Trade_JP'],
                        "英文販賣名": en_t,
                        "日文成分名": row['Ingredient_JP'],
                        "英文成分名": en_i
                    })
                    p.progress((idx + 1) / len(clean_df))
                
                status.update(label="✅ 完成！", state="complete")
                res_df = pd.DataFrame(final_results)
                st.dataframe(res_df, use_container_width=True)
                st.download_button("📥 下載結果", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), "Result.csv")
        else:
            st.error("⚠️ 無法在第三行找到標題，或藍框內無有效資料。")
