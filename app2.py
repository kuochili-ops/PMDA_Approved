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
VERSION_TIME = "18:00" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙網址精確解析版")
st.markdown(f"""
> **解析邏輯說明**：
> 1. **Trade Name (EN)**：由 `japic_med_product?id=` 網址獲取。針對換行與標籤分離進行優化。
> 2. **Ingredient (EN)**：由 `japic_med?japic_code=` 網址獲取。
> 3. **欄位自動適應**：自動識別「販賣名」並清洗搜尋關鍵字。
""")
st.divider()

def fetch_data(japic_id_input, trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    try:
        # 1. ID 清洗 (確保 8 位純數字)
        raw_id = str(japic_id_input).split('.')[0].strip()
        final_id = re.sub(r'[^0-9]', '', raw_id)
        
        # 2. 如果 Excel 裡沒有 ID，則利用「販賣名」進行搜尋
        if not (5 <= len(final_id) <= 9):
            # 清洗販賣名：取第一行且過濾掉括號
            search_keyword = re.split(r'[\(\n\s]', str(trade_jp_full))[0].strip()
            # 移除劑型數字如 200mg 以增加搜尋成功率
            search_keyword = re.sub(r'\d+.*$', '', search_keyword)
            
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0]

        if final_id:
            final_id = final_id.zfill(8)
            res["target_id"] = final_id
            
            # --- [Part A] 抓商品名 (Trade Name) ---
            # 關鍵修改：進入專屬產品頁面抓取英文商標
            t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            rt = requests.get(t_url, headers=headers, timeout=10)
            rt.encoding = rt.apparent_encoding
            
            # 使用 separator=" " 處理所有內嵌標籤與換行，確保英文字串完整連貫
            soup_t = BeautifulSoup(rt.text, 'html.parser')
            t_text = soup_t.get_text(separator=" ", strip=True)
            
            # 尋找「欧文商標名」後方的內容
            if "欧文商標名" in t_text:
                after_anchor = t_text.split("欧文商標名")[-1].strip()
                # 正則：找尋首組大寫開頭的英文字串 (包含空格、橫線、斜槓)
                t_match = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after_anchor)
                if t_match:
                    candidate = t_match.group(1).strip()
                    # 再次過濾：遇到第一個非 ASCII (日文/全形符號) 就切斷
                    res["trade_en"] = re.split(r'[^\x00-\x7F]+', candidate)[0].strip()

            # --- [Part B] 抓成分名 (Ingredient) ---
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

# --- UI 介面 ---
f = st.file_uploader("請上傳原始承認品目 Excel", type=['xlsx'])

if f:
    # 針對厚勞省格式：標題通常在第 3 行 (header=2)
    raw_df = pd.read_excel(f, header=None)
    
    # 動態掃描標題列邏輯
    h_idx = 0
    cols = {'No': 0, 'Trade': 1, 'ID': -1} # ID 預設為 -1 表示可能不存在
    
    for i in range(min(10, len(raw_df))):
        r_str = "".join([str(x) for x in raw_df.iloc[i]])
        if any(k in r_str for k in ['販', '商', 'No']):
            h_idx = i
            for idx, val in enumerate(raw_df.iloc[i]):
                v = str(val).replace(' ', '').replace('\n', '')
                if 'No' in v: cols['No'] = idx
                if '販' in v or '商' in v: cols['Trade'] = idx
                if 'ID' in v or 'Japic' in v: cols['ID'] = idx
            break

    # 建立處理清單
    data_list = []
    for _, row in raw_df.iloc[h_idx + 1:].iterrows():
        no_val = str(row.iloc[cols['No']]).strip().split('.')[0]
        if not no_val.isdigit(): continue # 排除非數據行
        
        # 獲取 JapicID (如果 Excel 裡有)
        jid_val = str(row.iloc[cols['ID']]).strip() if cols['ID'] != -1 else ""
        
        data_list.append({
            "No.": no_val,
            "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
            "JapicID_Excel": jid_val
        })

    st.subheader(f"📋 待處理預覽 (已識別標題於第 {h_idx+1} 行)")
    st.dataframe(pd.DataFrame(data_list), use_container_width=True)

    if st.button("🚀 開始全自動搜尋與同步解析"):
        results = []
        bar = st.progress(0)
        for i, r in enumerate(data_list):
            # 核心執行
            info = fetch_data(r['JapicID_Excel'], r['商品名(日)'])
            results.append({
                "No.": r['No.'],
                "日文販賣名": r['商品名(日)'].replace('\n', ' '),
                "JapicID": info["target_id"],
                "Trade Name (EN)": info["trade_en"],
                "Ingredient (EN)": info["ing_en"],
                "Trade_URL": f"https://www.kegg.jp/medicus-bin/japic_med_product?id={info['target_id']}",
                "Ing_URL": f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={info['target_id']}"
            })
            bar.progress((i + 1) / len(data_list))
            time.sleep(0.5)
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 最終解析結果")
        st.dataframe(res_df, use_container_width=True)
        
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 成果", out.getvalue(), "PMDA_Final_Results.xlsx")
