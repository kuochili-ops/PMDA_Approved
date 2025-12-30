import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# 版本標記：2025-12-30 精簡片假名 + 抓取過程透明化版

st.set_page_config(layout="wide", page_title="PMDA 精確解析工具")

def get_pure_katakana(text):
    """只提取第一個出現的片假名區塊作為關鍵字"""
    if not text or pd.isna(text): return ""
    text = str(text).strip()
    # 匹配連續的片假名（包含長音符號與中間點）
    match = re.search(r'([ァ-ヶー・]+)', text)
    return match.group(1) if match else text

def fetch_dual_strings(japic_id, kw_trade):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {
        "trade_en": "[未檢出]", 
        "ing_en": "[未檢出]", 
        "target_id": "None", 
        "url": "N/A",
        "raw_reg_text": ""  # 新增：存儲原始 HTML 內容以便使用者判斷
    }
    
    try:
        # 1. JapicID 處理：補齊 8 位數
        final_id = None
        if japic_id and str(japic_id).lower() != 'none' and str(japic_id).strip() != "":
            final_id = str(japic_id).split('.')[0].strip().zfill(8)
        
        # 2. 如果無 ID，則執行搜尋
        if not final_id:
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
            if th_ing and th_ing.find_next_sibling('td'):
                res["ing_en"] = th_ing.find_next_sibling('td').get_text(strip=True)

            # --- [位置 2] 商品名：規制区分 ---
            th_reg = soup.find('th', string=re.compile(r'規制区分'))
            if th_reg and th_reg.find_next_sibling('td'):
                td_node = th_reg.find_next_sibling('td')
                raw_text = td_node.get_text(separator=" ", strip=True)
                res["raw_reg_text"] = raw_text # 紀錄原始文字供判斷
                
                # 提取最後一段連續英文 (包含空格與劑型)
                en_matches = re.findall(r'\b[A-Z][A-Za-z0-9\s\-\.]{3,}\b', raw_text)
                if en_matches:
                    res["trade_en"] = en_matches[-1].strip()
    except:
        res["trade_en"] = "[解析異常]"
    return res

# --- UI 部分 ---
st.title("💊 PMDA 雙英文字串精確版")

f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    try:
        raw_df = pd.read_excel(f, header=None)
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
            data_rows = []
            for _, row in raw_df.iloc[header_idx + 1:].iterrows():
                no_val = str(row.iloc[cols.get('No', 0)]).strip().replace('.0','')
                if not no_val.isdigit() and len(data_rows) > 0: break
                
                # 取得 JapicID 並處理 None 的顯示
                raw_id = str(row.iloc[cols.get('ID', -1)]).strip() if 'ID' in cols else "None"
                display_id = raw_id if raw_id.lower() != 'none' else "[待搜尋]"
                
                trade_name_jp = str(row.iloc[cols.get('Trade', 1)]).strip()
                data_rows.append({
                    "No.": no_val,
                    "商品名(日)": trade_name_jp,
                    "關鍵字(片假名)": get_pure_katakana(trade_name_jp),
                    "成分名(日)": str(row.iloc[cols.get('Ing', 2)]).strip(),
                    "JapicID": display_id
                })
            df = pd.DataFrame(data_rows)
            st.subheader("📋 1. 上傳資料預覽 (關鍵字已精簡)")
            st.dataframe(df, use_container_width=True)

            if st.button("🚀 開始深度解析"):
                results = []
                bar = st.progress(0)
                status = st.empty()
                
                for i, r in df.iterrows():
                    status.text(f"⏳ 正在處理 No.{r['No.']}：{r['關鍵字(片假名)']}...")
                    # 傳入原始 JapicID 與 關鍵字
                    info = fetch_dual_strings(r['JapicID'], r['關鍵字(片假名)'])
                    
                    results.append({
                        "No.": r['No.'],
                        "JapicID": info["target_id"],
                        "商品名(日)": r['商品名(日)'],
                        "Trade Name (EN)": info["trade_en"],
                        "成分名(日)": r['成分名(日)'],
                        "Ingredient (EN)": info["ing_en"],
                        "從[規制区分]抓到的原始內容": info["raw_reg_text"], # 供您判斷
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
                st.download_button("📥 下載 Excel", out.getvalue(), "PMDA_Deep_Analysis.xlsx")
        else:
            st.error("❌ 找不到表頭。")
    except Exception as e:
        st.error(f"錯誤: {e}")
