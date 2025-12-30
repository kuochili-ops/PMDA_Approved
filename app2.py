import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 08:30 完整修正版 (解決 NameError & 空白網址)

st.set_page_config(layout="wide", page_title="PMDA 解析工具")

def get_pure_katakana(text):
    """只提取第一個出現的片假名區塊作為關鍵字"""
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id_input, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None", "url": "N/A", "raw_reg_text": ""}
    
    try:
        # --- 1. 嚴謹的 ID 處理 ---
        final_id = None
        # 只保留純數字
        clean_id = re.sub(r'[^0-9]', '', str(japic_id_input))
        
        # 如果數字長度不足（代表原本可能是 "None" 或 "[待搜尋]"），則發動搜尋
        if clean_id and len(clean_id) >= 5:
            final_id = clean_id.zfill(8)
        else:
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

            # --- [位置 1] 成分名：定位「欧文一般名」 ---
            th_ing = soup.find('th', string=re.compile(r'欧文一般名'))
            if th_ing:
                td_ing = th_ing.find_next_sibling('td')
                if td_ing:
                    res["ing_en"] = td_ing.get_text(strip=True)

            # --- [位置 2] 商品名：定位「規制区分」 ---
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg:
                td_reg = th_reg.find_next_sibling('td')
                if td_reg:
                    # 取得內容並清理多餘換行
                    raw_text = td_reg.get_text(separator=" ", strip=True)
                    res["raw_reg_text"] = raw_text
                    
                    # 抓取邏輯：抓取最後一段連續的英文 (包含空格/劑型)
                    # 針對 Scemblix 模式：セムブリックス錠20mg SCEMBLIX tablets
                    en_pattern = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', raw_text)
                    if en_pattern:
                        res["trade_en"] = en_pattern[-1].strip()
                        
    except Exception as e:
        res["trade_en"] = f"[解析異常]"
        
    return res

# --- UI 介面 ---
st.title("💊 PMDA 雙英文字串精確對位版")

f = st.file_uploader("1. 請上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
        
        # --- 自動辨識表頭 ---
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
                    if any(k in val for k in ['Japic', 'ID']): cols['ID'] = idx
                break
        
        if header_idx is not None:
            # --- 建立預覽用 DataFrame (這就是解決 NameError 的關鍵) ---
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                # 取得 No.
                no_raw = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_raw.isdigit() and len(data_rows) > 0: break
                
                # 取得 JapicID
                raw_id = str(row.iloc[cols.get('ID', -1)]).strip() if 'ID' in cols else "None"
                # 清洗 ID，如果是 None 則顯示 [待搜尋]
                clean_id_for_display = raw_id if (raw_id.lower() != 'none' and raw_id != "" and raw_id != "nan") else "[待搜尋]"
                
                trade_jp = str(row.iloc[cols.get('Trade', 1)]).strip()
                
                data_rows.append({
                    "No.": no_raw,
                    "商品名(日)": trade_jp,
                    "關鍵字(片假名)": get_pure_katakana(trade_jp),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": clean_id_for_display
                })
            
            # 正式定義 df 變數
            df = pd.DataFrame(data_rows)
            
            st.subheader("📋 1. 待處理清單預覽")
            st.dataframe(df, use_container_width=True)

            if st.button("🚀 開始深度解析"):
                results = []
                bar = st.progress(0)
                status = st.empty()
                
                for i, r in df.iterrows():
                    status.text(f"⏳ 正在分析 No.{r['No.']}：{r['關鍵字(片假名)']}...")
                    
                    # 傳入 ID 前確保排除掉 "[待搜尋]" 這種文字
                    input_id = r['JapicID'] if r['JapicID'] != "[待搜尋]" else ""
                    info = fetch_dual_strings(input_id, r['關鍵字(片假名)'])
                    
                    results.append({
                        "No.": r['No.'],
                        "JapicID": info["target_id"],
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": info["trade_en"],
                        "成分名(日)": r['成分名(日)'],
                        "Ingredient (EN)": info["ing_en"],
                        "規制区分原始內容": info["raw_reg_text"],
                        "來源網址": info["url"]
                    })
                    bar.progress((i + 1) / len(df))
                    time.sleep(1.0)
                
                res_df = pd.DataFrame(results)
                st.subheader("📊 2. 最終解析結果")
                st.dataframe(res_df, use_container_width=True)
                
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 下載 Excel", out.getvalue(), "PMDA_Analysis_Report.xlsx")
        else:
            st.error("❌ 找不到 Excel 表頭，請確認欄位包含『商品名』與『成分名』。")
    except Exception as e:
        st.error(f"程式執行發生錯誤: {e}")
else:
    st.info("請上傳 Excel 檔案以開始。")
