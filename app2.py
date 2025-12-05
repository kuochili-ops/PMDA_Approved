
import streamlit as st
import pandas as pd

st.title("KEGG藥品查詢工具")

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
        st.dataframe(df[[ingredient_col]])  # 顯示成分名欄位
