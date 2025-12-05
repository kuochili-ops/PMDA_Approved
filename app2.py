
ingredient_col = None
for col in df.columns:
    if "成分" in col.replace(" ", ""):  # 去除空格後比對
        ingredient_col = col
        break

if not ingredient_col:
    st.error("找不到成分名相關欄位，請確認檔案格式。")
else:
    st.success(f"偵測到成分名欄位：{ingredient_col}")
    # 以下照原流程查詢 PubChem
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
    st.dataframe(df)
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="下載查詢結果 CSV",
        data=csv,
        file_name="drug_list_with_pubchem.csv",
        mime='text/csv'
