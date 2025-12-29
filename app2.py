import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 22:15

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：精準定位「2. 禁忌」前的英文 ---
def fetch_exact_english_by_japic(japic_code):
    if not japic_code or str(japic_code) == "None": 
        return {"trade_en": "[無ID]", "ing_en": "[無ID]"}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}

    try:
        url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 取得網頁所有的純文字，並保留換行以利區分區塊
        full_text = soup.get_text(separator="\n", strip=True)
        
        # 物理規則：鎖定「2. 禁忌」之前的內容
        if "2. 禁忌" in full_text:
            pre_text = full_text.split("2. 禁忌")[0]
            
            # 尋找所有英文單字塊 (包含大小寫、空格、連字號)
            # 例如: "Iptacopan hydrochloride hydrate" 或 "Fabihal ta"
            # 改良的正則表達式：尋找連續的英文字符，排除掉掉單個字母或純數字
            raw_eng_list = re.findall(r'[A-Za-z][A-Za-z\s\-\,]{3,}', pre_text)
            
            # 過濾掉無意義的系統字詞
            filtered_names = []
            black_list = ["JAPIC", "KEGG", "MEDICUS", "PDF", "PDS", "INDEX", "HOME"]
            for name in raw_eng_list:
                clean_name = name.strip().strip(',')
                if clean_name.upper() not in black_list and len(clean_name) > 3:
                    if clean_name not in filtered_names:
                        filtered_names.append(clean_name)
            
            # 依照您的物理規則分配：
            # 第一個英文名詞為成分名，第二個英文名詞為商品名
            if len(filtered_names) >= 1:
                res["ing_en"] = filtered_names[0]
            if len(filtered_names) >= 2:
                res["trade_en"] = filtered_names[1]
                
        # 備援：如果上方沒抓到，嘗試抓取表格內的歐文名
        if res["trade_en"] == "[未檢出]":
            th_t = soup.find('th', string=re.compile(r'欧文商標名'))
            if th_t: res["trade_en"] = th_t.find_next_sibling('td').get_text(strip=True)
            th_i = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_i: res["ing_en"] = th_i.find_next_sibling('td').get_text(strip=True)

    except:
        pass
    return res

# --- 介面處理 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 物理定位翻譯機 (版本 22:15)")

st.markdown("""
### 運作說明
1. 上傳您那份帶有 **JapicID** 的檔案。
2. 程式會進入 `japic_med` 頁面，並在「2. 禁忌」標籤出現前抓取英文。
3. **規則**：第1個英文 = 成分名，第2個英文 = 商品名。
""")

f = st.file_uploader("上傳 Excel/CSV (需含 JapicID 欄位)", type=['xlsx', 'csv'])

if f:
    df_raw = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
    st.dataframe(df_raw.head(3))
    
    # 自動偵測 ID 欄位
    id_col = next((c for c in df_raw.columns if 'ID' in c.upper() or 'JAPIC' in c.upper()), df_raw.columns[-1])
    target_col = st.selectbox("請確認 JapicID 欄位", df_raw.columns, index=list(df_raw.columns).index(id_col))

    if st.button("🚀 執行精準解析"):
        results = []
        bar = st.progress(0)
        for i, row in df_raw.iterrows():
            code = str(row[target_col]).strip().zfill(8)
            if code == "0000None" or code == "nan":
                info = {"trade_en": "[無ID]", "ing_en": "[無ID]"}
            else:
                info = fetch_exact_english_by_japic(code)
            
            results.append({
                "No.": row.get("No.", i+1),
                "JapicID": code,
                "商品名(日)": row.get("商品名(日)", ""),
                "Trade Name (EN)": info["trade_en"],
                "成分名(日)": row.get("成分名(日)", ""),
                "Ingredient (EN)": info["ing_en"]
            })
            bar.progress((i + 1) / len(df_raw))
            time.sleep(1.2)
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 解析結果")
        st.dataframe(res_df, use_container_width=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載最終 Excel", output.getvalue(), "PMDA_Final_Fixed_2215.xlsx")
