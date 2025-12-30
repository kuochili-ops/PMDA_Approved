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
VERSION_TIME = "17:30" 

st.set_page_config(layout="wide", page_title=f"PMDA Tool {VERSION_DATE}")

st.title("💊 PMDA 雙網址精確解析版")
st.markdown(f"""
> **解析邏輯說明**：
> 1. **Trade Name (EN)**：由 `japic_med_product?id=` 網址獲取。
> 2. **Ingredient (EN)**：由 `japic_med?japic_code=` 網址獲取。
> 3. **關鍵修正**：解決 `欧文商標名` 標籤與文字分離導致抓取失敗的問題。
""")
st.divider()

def fetch_data(japic_id_input, trade_jp_full):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]", "target_id": "None"}
    
    try:
        # 1. ID 清洗 (確保 8 位純數字)
        raw_id = str(japic_id_input).split('.')[0].strip()
        final_id = re.sub(r'[^0-9]', '', raw_id)
        
        if not (5 <= len(final_id) <= 9):
            # 備援：搜尋 ID
            search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(trade_jp_full[:8])}"
            r_s = requests.get(search_url, headers=headers, timeout=10)
            codes = re.findall(r'japic_code=(\d+)', r_s.text + r_s.url)
            if codes: final_id = codes[0]

        if final_id:
            final_id = final_id.zfill(8)
            res["target_id"] = final_id
            
            # --- [Part A] 抓商品名 (Trade Name) ---
            t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={final_id}"
            rt = requests.get(t_url, headers=headers, timeout=10)
            rt.encoding = rt.apparent_encoding
            # 使用文字流匹配，無視標籤
            t_text = BeautifulSoup(rt.text, 'html.parser').get_text(separator=" ", strip=True)
            # 尋找「欧文商標名」後方 100 字元內的英文字
            t_match = re.search(r'欧文商標名\s*([A-Z0-9][A-Za-z0-9\s\-\.\/]{3,})', t_text)
            if t_match:
                # 清洗抓到的字串，遇到下一個日文字就截斷
                raw_en = t_match.group(1).strip()
                res["trade_en"] = re.split(r'[^\x00-\x7F]+', raw_en)[0].strip()

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
f = st.file_uploader("上傳 Excel", type=['xlsx'])

if f:
    raw_df = pd.read_excel(f, header=None)
    # 掃描表頭
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

    st.subheader("📋 待處理預覽")
    st.dataframe(pd.DataFrame(data_list))

    if st.button("🚀 開始同步解析 (雙網址代入)"):
        results = []
        bar = st.progress(0)
        for i, r in enumerate(data_list):
            info = fetch_data(r['JapicID'], r['商品名(日)'])
            results.append({
                "No.": r['No.'],
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
        st.dataframe(res_df)
        
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 成果", out.getvalue(), "PMDA_DualLink_Result.xlsx")
