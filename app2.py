import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 05:00 穩定渲染版

# 設定頁面最開頭，確保 UI 一定會出現
st.set_page_config(layout="wide", page_title="PMDA 翻譯工具")

def get_katakana_prefix(text):
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else ""

def fetch_dual_strings(japic_id, kw_trade):
    """
    核心邏輯：分別從兩個不同位置抓取英文字串
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A"}
    
    try:
        # 1. ID 處理
        final_id = str(japic_id).strip().split('.')[0].zfill(8) if japic_id and str(japic_id).lower() != 'none' else None
        
        # 2. 如果沒 ID，透過搜尋補抓
        if not final_id or final_id == "0000None":
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(kw_trade)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0].zfill(8)

        if final_id:
            target_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            res["target_id"], res["url"] = final_id, target_url
            
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # --- [位置 1] 成分名：欧文一般名 ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing:
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [位置 2] 商品名：規制区分 ---
            # 邏輯：從該格內容中，提取所有英文字串，並取「最後一個」
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_text = th_reg.find_next_sibling('td').get_text(separator=" ", strip=True)
                # 抓取包含空格的英文單字 (例如 SCEMBLIX tablets)
                en_matches = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', td_text)
                if en_matches:
                    res["trade_en"] = en_matches[-1].strip()
    except:
        pass
    return res

# --- UI 介面 ---
st.title("💊 PMDA 藥品名翻譯 (雙欄位精確版)")

# 說明文字
st.markdown("""
**抓取規則：**
1. **Ingredient (EN)**: 取自 `欧文一般名` 欄位。
2. **Trade Name (EN)**: 取自 `規制区分` 欄位中的末尾英文字串。
""")

f = st.file_uploader("1. 請上傳含有 JapicID 或商品名的 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        
        # 自動辨識表頭
        header_idx, cols = None, {}
        for i in range(min(20, len(raw_df))):
            row_vals = [str(x) for x in raw_df.iloc[i]]
            row_str = "".join(row_vals)
            if any(k in row_str for k in ['商', '成', '販']):
                header_idx = i
                for idx, val in enumerate(row_vals):
                    if 'No' in val: cols['No'] = idx
                    if any(k in val for k in ['商', '販']): cols['Trade'] = idx
                    if '成' in val: cols['Ing'] = idx
                    if 'Japic' in val or 'ID' in val: cols['ID'] = idx
                break
        
        if header_idx is not None:
            # 清洗資料
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_val = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_val.isdigit() and len(data_rows) > 0: break
                data_rows.append({
                    "No.": no_val,
                    "商品名(日)": str(row.iloc[cols.get('Trade', 1)]).strip(),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": str(row.iloc[cols.get('ID', -1)]).strip() if 'ID' in cols else "None"
                })
            df = pd.DataFrame(data_rows)
            st.success(f"✅ 辨識成功，共 {len(df)} 筆資料")
            st.dataframe(df, use_container_width=True)

            if st.button("🚀 開始解析"):
                results = []
                bar = st.progress(0)
                status = st.empty()
                
                for i, r in df.iterrows():
                    status.text(f"⏳ 正在分析 No.{r['No.']}...")
                    info = fetch_dual_strings(r['JapicID'], get_katakana_prefix(r['商品名(日)']))
                    
                    results.append({
                        "No.": r['No.'],
                        "JapicID": info["target_id"],
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": info["trade_en"],
                        "成分名(日)": r['成分名(日)'],
                        "Ingredient (EN)": info["ing_en"],
                        "來源網址": info["url"]
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(1.0)
                
                res_df = pd.DataFrame(results)
                st.subheader("📊 解析結果")
                st.dataframe(res_df, use_container_width=True)
                
                # 下載
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載 Excel 報告", out.getvalue(), "PMDA_Result.xlsx")
        else:
            st.error("❌ 無法辨識 Excel 表頭，請確認欄位包含『商品名』與『成分名』。")
            
    except Exception as e:
        st.error(f"發生錯誤: {e}")
else:
    st.info("請上傳檔案以開始。")
