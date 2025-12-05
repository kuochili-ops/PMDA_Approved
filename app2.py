
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time

def kegg_drug_search(japanese_name):
    # KEGG DRUG 搜尋頁面
    search_url = f"https://www.kegg.jp/kegg-bin/search?q={japanese_name}&display=drug&from=drug&lang=ja"
    response = requests.get(search_url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:  # 跳過表頭
                cols = row.find_all("td")
                if len(cols) >= 2:
                    entry = cols[0].text.strip()
                    name = cols[1].text.strip()
                    # 英文學名抽取
                    if "(" in name:
                        english_name = name.split("(")[1].split(")")[0]
                        return entry, english_name
                    else:
                        return entry, name
    return None, None

st.title("KEGG藥品學名查詢工具")

uploaded_file = st.file_uploader("請上傳藥品清單（Excel/CSV）", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    df = pd.read_excel(uploaded_file, skiprows=2)
    st.write("所有欄位名稱：", df.columns.tolist())

    # 自動偵測成分名欄位
    ingredient_col = None
    for col in df.columns:
        if "成分" in col.replace(" ", ""):
            ingredient_col = col
            break

    if not ingredient_col:
        st.error("找不到成分名相關欄位，請確認檔案格式。")
    else:
        st.success(f"偵測到成分名欄位：{ingredient_col}")
        df['KEGG_Entry'] = ""
        df['KEGG_English_Name'] = ""
        for idx, row in df.iterrows():
            name = str(row[ingredient_col]).strip()
            if not name or pd.isna(name):
                continue
            entry, english_name = kegg_drug_search(name)
            df.at[idx, 'KEGG_Entry'] = entry if entry else ""
            df.at[idx, 'KEGG_English_Name'] = english_name if english_name else ""
            time.sleep(1)  # 建議每筆間隔1秒，避免被封鎖
        st.dataframe(df)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="下載查詢結果 CSV",
            data=csv,
            file_name="drug_list_with_kegg.csv",
            mime='text/csv'
