import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

st.set_page_config(layout="wide", page_title="PMDA Auto-Search Pro")

st.title("💊 PMDA 承認品目全自動解析器")
st.markdown("> **適用對象**：厚生勞動省「承認品目一覧」Excel 格式。自動搜尋 JapicID 並提取雙網頁英文資訊。")

def get_japic_id(jp_name_raw):
    """從販賣名中提取關鍵字並搜尋 JapicID"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    # 清洗邏輯：取左側藥名，過濾掉 (公司名) 與換行
    clean_keyword = re.split(r'[\(\n\s]', str(jp_name_raw))[0].strip()
    # 移除劑型單位以便增加搜尋成功率 (如 200mg)
    search_keyword = re.sub(r'\d+.*$', '', clean_keyword)
    
    url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(search_keyword)}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        match = re.search(r'japic_code=(\d+)', r.text)
        return match.group(1).zfill(8) if match else None
    except:
        return None

def fetch_en_info(jid):
    """根據 ID 從兩個不同網頁抓取資訊"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    
    try:
        # 1. 抓 Trade Name (產品頁)
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={jid}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        soup_t = BeautifulSoup(rt.text, 'html.parser')
        anchor = soup_t.find(string=re.compile(r'欧文商標名'))
        if anchor:
            p_tag = anchor.find_parent('p')
            full_txt = p_tag.get_text(separator=" ", strip=True) if p_tag else ""
            after = full_txt.split("欧文商標名")[-1].strip()
            m = re.search(r'([A-Z][A-Za-z0-9\s\-\.\/]{2,})', after)
            if m: res["trade_en"] = re.split(r'[^\x00-\x7F]+', m.group(1))[0].strip()

        # 2. 抓 Ingredient (醫藥頁)
        i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={jid}"
        ri = requests.get(i_url, headers=headers, timeout=10)
        ri.encoding = ri.apparent_encoding
        soup_i = BeautifulSoup(ri.text, 'html.parser')
        th = soup_i.find('th', string=re.compile(r'欧文一般名'))
        if th and th.find_next_sibling('td'):
            res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
    except:
        pass
    return res

f = st.file_uploader("上傳承認品目 Excel (承認品目5月分等)", type=['xlsx'])

if f:
    # 關鍵：header=2 代表從 Excel 第三行讀取標題 (No. / 販賣名)
    df = pd.read_excel(f, header=2)
    # 修正欄位名稱中的空格與換行問題
    df.columns = [str(c).replace('\n', '').replace(' ', '') for c in df.columns]
    
    # 尋找販賣名欄位 (名稱通常為 '販売名' 或含有 '販')
    target_col = next((c for c in df.columns if '販' in c), None)

    if target_col:
        st.success(f"已定位藥名欄位：{target_col}")
        if st.button("🚀 開始全自動搜尋解析"):
            final_data = []
            rows = df.dropna(subset=[target_col]).to_dict('records')
            bar = st.progress(0)
            
            for i, row in enumerate(rows):
                jp_name = row[target_col]
                jid = get_japic_id(jp_name)
                
                if jid:
                    info = fetch_en_info(jid)
                    final_data.append({
                        "No.": row.get('No.', i+1),
                        "原販賣名": str(jp_name).replace('\n', ' '),
                        "JapicID": jid,
                        "Trade Name (EN)": info["trade_en"],
                        "Ingredient (EN)": info["ing_en"]
                    })
                else:
                    final_data.append({
                        "No.": row.get('No.', i+1),
                        "原販賣名": str(jp_name).replace('\n', ' '),
                        "JapicID": "[找不到]", "Trade Name (EN)": "-", "Ingredient (EN)": "-"
                    })
                bar.progress((i + 1) / len(rows))
                time.sleep(0.5)

            res_df = pd.DataFrame(final_data)
            st.dataframe(res_df, use_container_width=True)
            
            # 下載成果
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載最終 Excel", out.getvalue(), "PMDA_Search_Final.xlsx")
    else:
        st.error("無法辨識「販賣名」欄位，請確認 Excel 第 3 行是否有正確標題。")
