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
VERSION_TIME = "18:20" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙網址精確解析版")
st.markdown(f"""
> **解析策略更新**：
> 1. **Trade Name**：鎖定 `japic_med_product` 頁面，採用「標籤後繼文字流」掃描。
> 2. **Ingredient**：鎖定 `japic_med` 頁面，提取 `欧文一般名` 儲存格。
""")
st.divider()

def fetch_data(japic_id_input, trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    try:
        # ID 清洗
        raw_id = str(japic_id_input).split('.')[0].strip()
        final_id = re.sub(r'[^0-9]', '', raw_id).zfill(8)
        res["target_id"] = final_id
        
        # --- [Part A] 抓 Trade Name (產品情報頁) ---
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        soup_t = BeautifulSoup(rt.text, 'html.parser')
        
        # 尋找包含「欧文商標名」的元素
        anchor = soup_t.find(string=re.compile(r'欧文商標名'))
        if anchor:
            # 取得該元素父層之後的所有文字
            parent = anchor.find_parent()
            # 獲取 parent 內部所有文字並移除標籤干擾
            full_txt = parent.get_text(separator=" ", strip=True)
            # 使用正則：匹配「欧文商標名」後方第一個英文字串 (允許空格、橫線、點)
            match = re.search(r'欧文商標名\s*([A-Za-z0-9][A-Za-z0-9\s\-\.\/]{3,})', full_txt)
            if match:
                res["trade_en"] = match.group(1).strip()
            else:
                # 備援：若 regex 失敗，抓取 parent 之後的下一個兄弟節點文字
                res["trade_en"] = parent.get_text(strip=True).replace("欧文商標名", "").strip()

        # --- [Part B] 抓 Ingredient (醫療主頁) ---
        i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={final_id}"
        ri = requests.get(i_url, headers=headers, timeout=10)
        ri.encoding = ri.apparent_encoding
        soup_i = BeautifulSoup(ri.text, 'html.parser')
        th = soup_i.find('th', string=re.compile(r'欧文一般名'))
        if th and th.find_next_sibling('td'):
            res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)

    except Exception:
        pass
        
    return res

# --- 主程式 ---
f = st.file_uploader("1. 上傳 Excel", type=['xlsx'])

if f:
    raw_df = pd.read_excel(f, header=None)
    h_idx, cols = 0, {'No': 0, 'Trade': 1, 'ID': 2}
    for i in range(min(20, len(raw_df))):
        r_str = "".join([str(x) for x in raw_df.iloc[i]])
        if any(k in r_str for k in ['商', '販', 'ID', 'Japic']):
            h_idx = i
            for idx, val in enumerate(raw_df.iloc[i]):
                v = str(val)
                if 'No' in v: cols['No'] = idx
                if any(k in v for k in ['商', '販']): cols['Trade'] = idx
                if 'ID' in v or 'Japic' in v: cols['ID'] = idx
            break

    data_list = []
    for _, row in raw_df.iloc[h_idx + 1:].iterrows():
        no = str(row.iloc[cols['No']]).strip().split('.')[0]
        if not no.isdigit() and len(data_list) > 0: break
        data_list.append({
            "No.": no,
            "商品名(日)": str(row.iloc[cols['Trade']]).strip(),
            "JapicID": str(row.iloc[cols['ID']]).strip()
        })

    st.subheader("📋 預覽清單")
    st.dataframe(pd.DataFrame(data_list))

    if st.button("🚀 開始深度解析 (文字流掃描版)"):
        results = []
        bar = st.progress(0)
        for i, r in enumerate(data_list):
            info = fetch_data(r['JapicID'], r['商品名(日)'])
            results.append({
                "No.": r['No.'],
                "JapicID": info["target_id"],
                "Trade Name (EN)": info["trade_en"],
                "Ingredient (EN)": info["ing_en"]
            })
            bar.progress((i + 1) / len(data_list))
            time.sleep(0.5)
        
        res_df = pd.DataFrame(results)
        st.subheader("📊 解析結果")
        st.dataframe(res_df)
        
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載成果", out.getvalue(), "PMDA_DeepScan_Result.xlsx")
