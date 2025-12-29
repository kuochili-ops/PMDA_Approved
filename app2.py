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
    # 提取核心藥名：取第一行，移除括號與公司名
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
                res = (t.group(1) if t else (g.group(1) if g else None)).strip()
                if res: return res
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

# --- 核心：模擬藍框判定 (排除 1000 筆無效紀錄) ---
def process_blue_frame_data(df):
    # 1. 鎖定第三行 (Index 2) 為標題
    if len(df) < 3: return None
    
    header_row = df.iloc[2]
    # 暴力清理標題字串
    clean_header = [re.sub(r'[\s\u3000\n]+', '', str(x)) for x in header_row]
    
    idx_no, idx_trade, idx_ing = None, None, None
    for i, h in enumerate(clean_header):
        if 'No' in h: idx_no = i
        if '販賣名' in h: idx_trade = i
        if '成分名' in h: idx_ing = i
        
    if idx_trade is None or idx_ing is None: return None

    # 2. 從第四行開始，一旦 No. 不是數字就切斷
    valid_data = []
    for i in range(3, len(df)):
        row = df.iloc[i]
        val_no = str(row[idx_no]).strip() if idx_no is not None else ""
        val_trade = str(row[idx_trade]).strip()
        val_ing = str(row[idx_ing]).strip()

        # 🛑 截斷邏輯：PMDA 藍框外特徵
        if not val_no.isdigit(): # 如果 No. 不是數字 (如空白、或備註文字)
            if len(valid_data) > 0: break # 只要已經抓到過資料，遇到非數字就代表出框了，立即停止
            continue # 如果還沒開始抓到資料，就跳過
        
        if val_trade == "" or val_trade.lower() == 'nan': break

        valid_data.append({
            "No.": val_no,
            "JP_Trade": val_trade,
            "JP_Ingredient": val_ing
        })
        
    return pd.DataFrame(valid_data)

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")
st.sidebar.markdown("### 🛠️ 設定資訊")
st.sidebar.info("本版本已優化：\n1. 固定鎖定第三行標題\n2. 偵測 No. 數字自動截斷空行")
st.sidebar.markdown("[🔗 PMDA 官網品目一覧](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0010.html)")

st.title("🇯🇵 PMDA 日本新藥翻譯 (v5.0 藍框鎖定版)")

up_file = st.file_uploader("上傳 Excel 檔案", type=['xlsx', 'xls', 'csv'])

if up_file:
    # 讀取檔案
    if up_file.name.endswith('.csv'):
        raw = pd.read_csv(up_file, header=None)
        sheets = ["CSV_Mode"]
    else:
        xls_obj = pd.ExcelFile(up_file)
        sheets = xls_obj.sheet_names
    
    s_name = st.selectbox("請選擇分頁 (月份)", sheets)
    if s_name:
        if not up_file.name.endswith('.csv'):
            raw = pd.read_excel(xls_obj, sheet_name=s_name, header=None)
        
        # 執行清洗
        df = process_blue_frame_data(raw)
        
        if df is not None and not df.empty:
            st.success(f"✅ 成功辨識 {len(df)} 筆有效紀錄（已排除藍框外的無效區）")
            st.table(df) # 預覽檢查
            
            if st.button("🚀 開始翻譯"):
                results = []
                status = st.status("正在檢索 KEGG 與 Azure...", expanded=True)
                log = st.empty()
                p = st.progress(0)
                
                for idx, row in df.iterrows():
                    # KEGG 優先，查不到才用 Azure
                    en_t = get_kegg_drug_info(row['JP_Trade'], log) or ms_translator(row['JP_Trade'])
                    en_i = get_kegg_drug_info(row['JP_Ingredient'], log) or ms_translator(row['JP_Ingredient'])
                    
                    results.append({
                        "No.": row['No.'],
                        "日文販賣名": row['JP_Trade'],
                        "English Trade Name": en_t,
                        "日文成分名": row['JP_Ingredient'],
                        "English Ingredient": en_i
                    })
                    p.progress((idx + 1) / len(df))
                
                status.update(label="✅ 處理完成！", state="complete")
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                st.download_button("📥 下載翻譯 CSV", res_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), f"PMDA_{s_name}.csv")
        else:
            st.error("⚠️ 無法辨識標題列或有效資料。請確認第三行是否為『販賣名』與『成分名』。")
