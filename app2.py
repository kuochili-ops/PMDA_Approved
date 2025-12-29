import streamlit as st
import pandas as pd
import requests
import re

# --- 核心翻譯與 KEGG 函數 ---
def get_kegg_info(name, log):
    if not name or pd.isna(name): return None
    # 僅取藥名部分，切除公司名與劑型
    clean_n = str(name).split('\n')[0].split('（')[0].split('(')[0].strip()
    clean_n = re.sub(r'［.*?］|（.*?）', '', clean_n)
    if len(clean_n) < 2: return None
    try:
        url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={clean_n}"
        r = requests.get(url, timeout=10)
        m = re.search(r'japic_code=(\d+)', r.text)
        if m:
            dr = requests.get(f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={m.group(1)}", timeout=10)
            t = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', dr.text, re.DOTALL)
            g = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', dr.text, re.DOTALL)
            return (t.group(1) if t else (g.group(1) if g else None)).strip()
    except: pass
    return None

def azure_translate(text, key, region):
    if not text or pd.isna(text): return ""
    endpoint = "https://api.cognitive.microsofttranslator.com/translate"
    headers = {"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region, "Content-type": "application/json"}
    body = [{"text": str(text).replace('\n', ' ')}]
    try:
        r = requests.post(endpoint, params={"api-version":"3.0","from":"ja","to":["en"]}, headers=headers, json=body, timeout=10)
        return r.json()[0]["translations"][0]["text"] if r.ok else text
    except: return text

# --- 藍框邊界偵測邏輯 ---
def clean_pmda_v6(df):
    if len(df) < 3: return None
    
    # 直接鎖定第三行 (Index 2)
    header_row = df.iloc[2]
    # 清理所有隱形空格
    clean_h = [re.sub(r'[\s\u3000\n]+', '', str(x)) for x in header_row]
    
    # 定位欄位
    idx_no, idx_trade, idx_ing = None, None, None
    for i, h in enumerate(clean_h):
        if 'No' in h: idx_no = i
        if '販賣名' in h: idx_trade = i
        if '成分名' in h: idx_ing = i
        
    if idx_trade is None or idx_ing is None: return None

    # 從第四行開始掃描
    rows = []
    for i in range(3, len(df)):
        row = df.iloc[i]
        val_no = str(row[idx_no]).strip() if idx_no is not None else ""
        val_trade = str(row[idx_trade]).strip()
        val_ing = str(row[idx_ing]).strip()

        # 🛑 關鍵：偵測藍框邊界
        # 如果 No 欄位不是純數字，且已經有抓到資料，就代表進入了藍框外的「注」或「空行」
        if not val_no.isdigit():
            if len(rows) > 0: break # 強制切斷
            continue 
        
        # 排除完全空行
        if val_trade == "" or val_trade.lower() == 'nan': break

        rows.append({"No.": val_no, "Trade": val_trade, "Ing": val_ing})
        
    return pd.DataFrame(rows)

# --- Streamlit 介面 ---
st.set_page_config(layout="wide", page_title="PMDA 翻譯 v6.0")
st.title("🇯🇵 PMDA 翻譯工具 (v6.0 藍框區域修復版)")
st.sidebar.markdown("[🔗 PMDA 官網品目一覧](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0010.html)")

# 設定 Azure Key
a_key = st.sidebar.text_input("Azure Key", type="password")
a_reg = st.sidebar.text_input("Azure Region", value="eastasia")

up = st.file_uploader("上傳 PMDA 檔案", type=['xlsx', 'csv'])

if up:
    # 根據副檔名讀取
    if up.name.endswith('.csv'):
        df_raw = pd.read_csv(up, header=None)
    else:
        xls = pd.ExcelFile(up)
        sheet = st.selectbox("選擇分頁", xls.sheet_names)
        df_raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        
    df_clean = clean_pmda_v6(df_raw)
    
    if df_clean is not None and not df_clean.empty:
        st.success(f"✅ 辨識成功！偵測到 {len(df_clean)} 筆有效紀錄（已排除藍框外雜訊）。")
        st.dataframe(df_clean, use_container_width=True)
        
        if st.button("🚀 開始翻譯"):
            res = []
            status = st.status("正在檢索...", expanded=True)
            log_box = st.empty()
            for idx, r in df_clean.iterrows():
                # KEGG -> Azure 雙層邏輯
                en_t = get_kegg_info(r['Trade'], log_box) or azure_translate(r['Trade'], a_key, a_reg)
                en_i = get_kegg_info(r['Ing'], log_box) or azure_translate(r['Ing'], a_key, a_reg)
                res.append({
                    "No.": r['No.'],
                    "日文販賣名": r['Trade'],
                    "英文販賣名": en_t,
                    "日文成分名": r['Ing'],
                    "英文成分名": en_i
                })
            status.update(label="✅ 翻譯完成", state="complete")
            st.dataframe(pd.DataFrame(res), use_container_width=True)
    else:
        st.error("⚠️ 無法辨識有效紀錄。請確認分頁第 3 行包含『販賣名』與『成分名』。")
