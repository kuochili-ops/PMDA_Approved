
if '成 分 名' not in df.columns:
    st.error("找不到 '成 分 名' 欄位，請確認檔案格式。")
else:
    df['PubChem_Synonyms'] = ""
    df['PubChem_IUPAC'] = ""
    for idx, row in df.iterrows():
        name = str(row['成 分 名'])
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
