
import streamlit as st
import pandas as pd
import requests
import time

def get_pubchem_synonyms(ingredient_name):
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient_name}/synonyms/JSON"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            synonyms = data.get('InformationList', {}).get('Information', [{}])[0].get('Synonym', [])
            return ', '.join(synonyms)
        else:
            return ""
    except Exception as e:
        return f"查詢錯誤：{e}"

def get_pubchem_iupac(ingredient_name):
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient_name}/property/IUPACName/JSON"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            iupac_name = data.get('PropertyTable', {}).get('Properties', [{}])[0].get('IUPACName', '')
            return iupac_name
        else:
            return ""
    except Exception as e:
        return f"查詢錯誤：{e}"

st.title("藥品成分 PubChem 學名查詢工具")

uploaded_file = st.file_uploader("請上傳藥品清單檔案（Excel 或 CSV）", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    # 讀取檔案
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    st.write("原始資料：", df)

    # 假設欄位名稱為 Ingredient_JP
    if 'Ingredient_JP' not in df.columns:
        st.error("找不到 'Ingredient_JP' 欄位，請確認檔案格式。")
    else:
        df['PubChem_Synonyms'] = ""
        df['PubChem_IUPAC'] = ""
        for idx, row in df.iterrows():
            name = str(row['Ingredient_JP'])
            if pd.isna(name) or name.strip() == "":
                continue
            synonyms = get_pubchem_synonyms(name)
            iupac = get_pubchem_iupac(name)
            df.at[idx, 'PubChem_Synonyms'] = synonyms
            df.at[idx, 'PubChem_IUPAC'] = iupac
            time.sleep(0.5)
        st.success("查詢完成！")
        st.dataframe(df)
        # 下載結果
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="下載查詢結果 CSV",
            data=csv,
            file_name="drug_list_with_pubchem.csv",
            mime='text/csv'
