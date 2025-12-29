import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-29 21:30

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    # 提取字串中的片假名部分作為關鍵字
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

# --- 核心邏輯：利用 JapicID 直接進入頁面並根據「2. 禁忌」前文字進行解析 ---
def fetch_by_direct_japic(japic_code):
    if not japic_code or japic_code == "None": 
        return {"trade_en": "[ID不明]", "ing_en": "[ID不明]"}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}

    try:
        # 直接根據 ID 構造 URL
        url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_code}"
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 移除不必要的標籤（如腳本、樣式、頁首頁尾）以純化文字
        for s in soup(["script", "style", "header", "footer"]):
            s.decompose()
        
        # 取得整頁純文字，並用換行符號隔開
        full_text = soup.get_text(separator="\n", strip=True)
        
        # 以「2. 禁忌」作為錨點切割文字
        if "2. 禁忌" in full_text:
            target_area = full_text.split("2. 禁忌")[0]
            
            # 使用正則表達式尋找英文名稱（大寫開頭，至少3個字母）
            # 格式涵蓋了單字、空格、連字號與逗號
            found_names = re.findall(r'\b[A-Z][a-zA-Z\s\-\,]{3,}\b', target_area)
            
            # 清理結果：去除多餘符號、排除常見系統關鍵字（如 JAPIC、PDF 等）
            cleaned_names = []
            for n in found_names:
                n = n.strip().strip(',')
                if n.upper() not in ["JAPIC", "KEGG", "MEDICUS", "PDF"] and len(n) > 2:
                    if n not in cleaned_names:
                        cleaned_names.append(n)
            
            # 套用您的物理定義規則：
            # 第 1 個是成分名 (Ingredient)，第 2 個是商品名 (Trade Name)
            if len(cleaned_names) >= 1:
                res["ing_en"] = cleaned_names[0]
            if len(cleaned_names) >= 2:
                res["trade_en"] = cleaned_names[1]
                
    except Exception as e:
        res["trade_en"] = f"錯誤: {str(e)}"
    return res

# --- Streamlit 介面與檔案處理 ---
st.set_page_config(layout="wide")
st.title("💊 PMDA 翻譯工具 (JapicID 精準抽出版：21:30)")

st.info("若您已有 JapicID（如 00071464），本工具將直接解析該頁面文字以提取英文名稱。")

f = st.file_uploader("上傳含有 JapicID 欄位的 Excel 或 CSV 檔案", type=['xlsx', 'csv'])
if f:
    # 讀取檔案
    if f.name.endswith('.csv'):
        df_raw = pd.read_csv(f)
    else:
        df_raw = pd.read_excel(f)
    
    st.write("已讀取資料（請確認 JapicID 欄位是否存在）：")
    st.dataframe(df_raw.head())
    
    # 讓使用者選擇包含 JapicID 的欄位名稱
    id_col = st.selectbox("請選擇 JapicID 所在的欄位", df_raw.columns)

    if st.button("🚀 開始從 JapicID 提取英文資訊"):
        results = []
        bar = st.progress(0)
        for i, row in df_raw.iterrows():
            # 格式化 ID 為 8 位數（補零）
            code = str(row[id_col]).strip().zfill(8)
            
            # 執行解析邏輯
            info = fetch_by_direct_japic(code)
            
            results.append({
                "No.": row.get("No.", i+1),
                "JapicID": code,
                "商品名(日)": row.get("商品名(日)", ""),
                "Trade Name (EN)": info["trade_en"],
                "成分名(日)": row.get("成分名(日)", ""),
                "Ingredient (EN)": info["ing_en"]
            })
            bar.progress((i + 1) / len(df_raw))
            time.sleep(1.0) # 延遲以避免被網頁封鎖
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 提取結果")
        st.dataframe(res_df, use_container_width=True)
        
        # 提供 Excel 下載
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載翻譯結果", output.getvalue(), "PMDA_Direct_Result.xlsx")
