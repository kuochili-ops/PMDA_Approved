
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
    # 直接用 skiprows=2 讀取
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
        df['PubChem_Synonyms'] = ""
        df['PubChem_IUPAC'] = ""
        for idx, row in df.iterrows():
            name = str(row[ingredient_col])
            if pd.isna(name) or name.strip() == "":
                continue
            synonyms = get_pubchem_synonyms(name)
            iupac = get_pubchem_iupac(name)
            df.at[idx, 'PubChem_Synonyms'] = synonyms
            df.at[idx, 'PubChem_IUPAC'] = iupac
            time.sleep(0.5)
        st.success("查詢完成！")
        st.dataframe(df)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="下載查詢結果 CSV",
            data=csv,
            file_name="drug_list_with_pubchem.csv",
            mime='text/csv'
        )
