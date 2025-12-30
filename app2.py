import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- 版本資訊 ---
VERSION_DATE = "2025-12-30"
VERSION_TIME = "21:00" 

st.set_page_config(layout="wide", page_title=f"PMDA Multi-Sheet Tool")

st.title("💊 PMDA 跨分頁全自動解析器")
st.markdown(f"""
> **多分頁支援說明**：
> 1. **自動識別**：會讀取 Excel 內所有分頁（如：承認品目5月分、6月分...）。
> 2. **智能定位**：每個分頁都會獨立掃描標題列（No., 販売名）。
> 3. **彙整輸出**：將所有分頁的解析結果合併導出為一個 Excel。
""")
st.divider()

def fetch_data(japic_id_input, trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    try:
        # 1. ID 清洗
        raw_id = str(japic_id_input).split('.')[0].strip()
        final_id = re.sub(r'[^0-9]', '', raw_id)
        
        # 2. 如果沒有 ID，則搜尋關鍵字 (清洗藥名：取第一行且移除劑型數字)
        if not (5 <= len(final_id) <= 9):
            search_keyword = re.split(r'[\(\n\s（]', str(trade_jp_full))[0].strip()
            search_keyword = re.sub(r'\d+.*$', '', search_keyword)
            
            if len(search_keyword) >= 2:
                search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
                r_s = requests.get(search_url, headers=headers, timeout=10)
                codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
                if codes: final_id = codes[0]

        if final_id:
            final_id = final_id.zfill(8)
            res["target_id"] = final_id
            
            # --- [Part A] Trade Name ---
            t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            rt = requests.get(t_url, headers=headers, timeout=10)
            rt.encoding = rt.apparent_encoding
            soup_t = BeautifulSoup(rt.text, 'html.parser')
            t_text = soup_t.get_text(separator=" ", strip=True)
            
            if "欧文商標名" in t_text:
                after_anchor = t_text.split("欧文商標名")[-1].strip()
                t_match = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after_anchor)
                if t_match:
                    candidate = t_match.group(1).strip()
                    res["trade_en"] = re.split(r'[^\x00-\x7F]+', candidate)[0].strip()

            # --- [Part B] Ingredient ---
            i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
            ri = requests.get(i_url, headers=headers, timeout=10)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)

    except Exception:
        res["trade_en"] = "[解析錯誤]"
    return res

# --- 檔案上傳與處理 ---
f = st.file_uploader("請上傳包含多個分頁的『承認品目』Excel", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    sheet_names = xl.sheet_names
    st.info(f"偵測到分頁： {', '.join(sheet_names)}")
    
    if st.button("🚀 開始解析所有分頁"):
        all_final_results = []
        
        for s_name in sheet_names:
            st.write(f"正在掃描分頁：**{s_name}**...")
            raw_df = pd.read_excel(f, sheet_name=s_name, header=None)
            
            # 1. 定位標題列
            h_idx = -1
            cols = {'No': -1, 'Trade': -1, 'ID': -1}
            for i in range(min(15, len(raw_df))):
                r_str = "".join([str(x) for x in raw_df.iloc[i]])
                if any(k in r_str for k in ['販', '商', 'No']):
                    h_idx = i
                    for idx, val in enumerate(raw_df.iloc[i]):
                        v = str(val).replace(' ', '').replace('\n', '')
                        if 'No' in v: cols['No'] = idx
                        if '販' in v or '商' in v: cols['Trade'] = idx
                        if 'ID' in v or 'Japic' in v: cols['ID'] = idx
                    break
            
            if h_idx == -1 or cols['Trade'] == -1:
                st.warning(f"分頁 '{s_name}' 找不到有效欄位，跳過。")
                continue

            # 2. 逐行處理數據
            current_sheet_data = []
            rows = raw_df.iloc[h_idx + 1:]
            for _, row in rows.iterrows():
                # 確保 No. 是數字
                no_val = str(row.iloc[cols['No']]).strip().split('.')[0] if cols['No'] != -1 else ""
                if not no_val.isdigit(): continue
                
                trade_jp = str(row.iloc[cols['Trade']]).strip()
                jid_val = str(row.iloc[cols['ID']]).strip() if cols['ID'] != -1 else ""
                
                # 執行 API 抓取
                info = fetch_data(jid_val, trade_jp)
                
                all_final_results.append({
                    "來源分頁": s_name,
                    "No.": no_val,
                    "日文販賣名": trade_jp.replace('\n', ' '),
                    "JapicID": info["target_id"],
                    "Trade Name (EN)": info["trade_en"],
                    "Ingredient (EN)": info["ing_en"],
                    "網址": f"https://www.kegg.jp/medicus-bin/japic_med_product?id={info['target_id']}" if info['target_id'] != "None" else ""
                })
                time.sleep(0.5) # 防止請求過快

        # 3. 顯示結果與下載
        if all_final_results:
            res_df = pd.DataFrame(all_final_results)
            st.subheader("📊 跨分頁彙整結果")
            st.dataframe(res_df, use_container_width=True)
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False, sheet_name='Summary')
            st.download_button("📥 下載完整彙整 Excel", out.getvalue(), "PMDA_All_Sheets_Result.xlsx")
        else:
            st.error("未成功提取任何數據。")
