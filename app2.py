import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

# --- 版本資訊 ---
VERSION_INFO = "2025-12-30 Multi-Sheet Support"

st.set_page_config(layout="wide", page_title=f"PMDA Multi-Tool")

st.title("💊 PMDA 承認品目全分頁自動解析器")
st.markdown(f"""
> **更新說明**：此版本專為包含多個分頁（5月-12月）的 Excel 設計。
> 1. **自動識別分頁**：會自動處理 Excel 內所有的工作表。
> 2. **智能定位標題**：自動尋找「販売名」所在行數。
> 3. **雙網址同步抓取**：獲取 Trade Name (EN) 與 Ingredient (EN)。
""")

def fetch_precise_data(trade_jp_full):
    """搜尋 JapicID 並提取英文資訊的核心函數"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"id": "[未檢出]", "trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    
    # 1. 提取搜尋關鍵字 (切掉換行、括號、劑型單位)
    clean_name = re.split(r'[\(\n\s]', str(trade_jp_full))[0].strip()
    search_keyword = re.sub(r'(\d+mg|注|錠|シリンジ|カプセル).*$', '', clean_name)
    
    if not search_keyword: return res

    try:
        # 第一步：搜尋 JapicID
        search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
        r_s = requests.get(search_url, headers=headers, timeout=10)
        match = re.search(r'japic_code=(\d+)', r_s.text + r_s.url)
        
        if match:
            jid = match.group(1).zfill(8)
            res["id"] = jid
            
            # 第二步：抓 Trade Name (Product 頁面)
            t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}"
            rt = requests.get(t_url, headers=headers, timeout=10)
            rt.encoding = rt.apparent_encoding
            soup_t = BeautifulSoup(rt.text, 'html.parser')
            t_text = soup_t.get_text(separator=" ", strip=True)
            
            if "欧文商標名" in t_text:
                after = t_text.split("欧文商標名")[-1].strip()
                m = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after)
                if m:
                    res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

            # 第三步：抓 Ingredient (Med 頁面)
            i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}"
            ri = requests.get(i_url, headers=headers, timeout=10)
            ri.encoding = ri.apparent_encoding
            si = BeautifulSoup(ri.text, 'html.parser')
            th = si.find('th', string=re.compile(r'欧文一般名'))
            if th and th.find_next_sibling('td'):
                res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

# --- 檔案處理 ---
f = st.file_uploader("請上傳原始多分頁 Excel", type=['xlsx'])

if f:
    xl = pd.ExcelFile(f)
    sheet_names = xl.sheet_names
    selected_sheets = st.multiselect("請選擇要處理的分頁", sheet_names, default=sheet_names)

    if st.button("🚀 開始跨分頁處理"):
        all_sheet_results = []
        overall_progress = st.progress(0)
        
        for s_idx, s_name in enumerate(selected_sheets):
            st.write(f"正在處理分頁：**{s_name}**...")
            df_temp = pd.read_excel(f, sheet_name=s_name, header=None)
            
            # 定位標題列
            h_row = 0
            trade_col = -1
            for i in range(min(15, len(df_temp))):
                row_str = "".join([str(x) for x in df_temp.iloc[i]])
                if '販' in row_str or '名' in row_str:
                    h_row = i
                    for idx, val in enumerate(df_temp.iloc[i]):
                        if '販' in str(val) or '名' in str(val):
                            trade_col = idx
                            break
                    break
            
            if trade_col != -1:
                # 取得該頁數據
                rows = df_temp.iloc[h_row + 1:].dropna(subset=[trade_col])
                for _, row in rows.iterrows():
                    jp_name = str(row.iloc[trade_col]).strip()
                    if "No." in jp_name or "承認" in jp_name: continue
                    
                    # 執行抓取
                    info = fetch_precise_data(jp_name)
                    all_sheet_results.append({
                        "來源分頁": s_name,
                        "日文販賣名": jp_name.replace('\n', ' '),
                        "JapicID": info["id"],
                        "Trade Name (EN)": info["trade_en"],
                        "Ingredient (EN)": info["ing_en"]
                    })
                    time.sleep(0.4) # 稍微延遲避免被封鎖
            
            overall_progress.progress((s_idx + 1) / len(selected_sheets))

        final_df = pd.DataFrame(all_sheet_results)
        st.subheader("📊 跨分頁彙整結果")
        st.dataframe(final_df, use_container_width=True)

        # 匯出匯總 Excel
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, index=False, sheet_name='Summary')
        st.download_button("📥 下載全分頁彙整 Excel", out.getvalue(), "PMDA_MultiSheet_Final.xlsx")
