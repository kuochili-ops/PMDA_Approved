import streamlit as st
import pandas as pd
import requests
import re
import time
from urllib.parse import quote
import io
from bs4 import BeautifulSoup

st.set_page_config(layout="wide", page_title="PMDA Auto-Search Tool")

st.title("💊 PMDA 藥品自動搜尋與英文化工具")
st.markdown("> **工作流程**：上傳原始 Excel → 根據「販賣名」搜尋 JapicID → 進入 KEGG 抓取英文商品名與成分名。")

def get_japic_id_by_search(trade_name_jp):
    """第一步：透過販賣名搜尋 JapicID"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    # 清洗販賣名：去除括號內的公司名與換行符
    clean_name = re.split(r'[\(\n]', trade_name_jp)[0].strip()
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={quote(clean_name)}"
    
    try:
        r = requests.get(search_url, headers=headers, timeout=10)
        # 搜尋結果中找 japic_code=XXXXXXXX
        match = re.search(r'japic_code=(\d+)', r.text)
        if match:
            return match.group(1).zfill(8)
    except:
        pass
    return None

def fetch_details(japic_id):
    """第二步：根據 JapicID 抓取雙網頁資訊"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = {"trade_en": "[未檢出]", "ing_en": "[未檢出]"}
    
    try:
        # --- 抓商品名 (Product 頁面) ---
        t_url = f"https://www.kegg.jp/medicus-bin/japic_med_product?id={japic_id}"
        rt = requests.get(t_url, headers=headers, timeout=10)
        rt.encoding = rt.apparent_encoding
        soup_t = BeautifulSoup(rt.text, 'html.parser')
        
        anchor = soup_t.find(string=re.compile(r'欧文商標名'))
        if anchor:
            p_tag = anchor.find_parent('p')
            if p_tag:
                full_text = p_tag.get_text(separator=" ", strip=True)
                after_anchor = full_text.split("欧文商標名")[-1].strip()
                # 抓取大寫開頭的英文字串，遇到日文截斷
                en_match = re.search(r'\b([A-Z][A-Za-z0-9\s\-\.\/]{2,})\b', after_anchor)
                if en_match:
                    res["trade_en"] = re.split(r'[^\x00-\x7F]+', en_match.group(1))[0].strip()

        # --- 抓成分名 (Med 頁面) ---
        i_url = f"https://www.kegg.jp/medicus-bin/japic_med?japic_code={japic_id}"
        ri = requests.get(i_url, headers=headers, timeout=10)
        ri.encoding = ri.apparent_encoding
        soup_i = BeautifulSoup(ri.text, 'html.parser')
        th = soup_i.find('th', string=re.compile(r'欧文一般名'))
        if th and th.find_next_sibling('td'):
            res["ing_en"] = th.find_next_sibling('td').get_text(strip=True)
            
    except:
        pass
    return res

# --- 上傳與邏輯 ---
f = st.file_uploader("請上傳原始承認品目 Excel", type=['xlsx', 'csv'])

if f:
    # 讀取並自動跳過前兩行說明的 header
    df_raw = pd.read_excel(f, header=2) if f.name.endswith('xlsx') else pd.read_csv(f, header=2)
    
    # 識別販賣名欄位 (通常包含 "販" 或 "名")
    trade_col = next((c for c in df_raw.columns if '販' in str(c) or '名' in str(c)), None)

    if trade_col:
        st.success(f"✅ 已識別藥品名稱欄位：{trade_col}")
        if st.button("🚀 開始自動搜尋並提取"):
            results = []
            bar = st.progress(0)
            rows = df_raw.dropna(subset=[trade_col]).to_dict('records')
            
            for i, row in enumerate(rows):
                jp_name = str(row[trade_col])
                # 1. 搜尋 ID
                jid = get_japic_id_by_search(jp_name)
                
                if jid:
                    # 2. 抓詳細資訊
                    info = fetch_details(jid)
                    results.append({
                        "No.": row.get('No.', i+1),
                        "日文販賣名": jp_name.replace('\n', ' '),
                        "JapicID": jid,
                        "Trade Name (EN)": info["trade_en"],
                        "Ingredient (EN)": info["ing_en"]
                    })
                else:
                    results.append({
                        "No.": row.get('No.', i+1),
                        "日文販賣名": jp_name.replace('\n', ' '),
                        "JapicID": "[找不到ID]",
                        "Trade Name (EN)": "[搜尋失敗]",
                        "Ingredient (EN)": "[搜尋失敗]"
                    })
                
                bar.progress((i + 1) / len(rows))
                time.sleep(0.5)
            
            res_df = pd.DataFrame(results)
            st.subheader("📊 處理結果")
            st.dataframe(res_df, use_container_width=True)
            
            # 匯出成果
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                res_df.to_excel(writer, index=False)
            st.download_button("📥 下載 Excel 結果", out.getvalue(), "PMDA_Full_Search_Result.xlsx")
    else:
        st.error("❌ 找不到藥品名稱欄位，請確認 Excel 結構。")
