
import streamlit as st
import pandas as pd

st.title("藥品成分 PubChem 學名查詢工具")

uploaded_file = st.file_uploader("請上傳藥品清單檔案（Excel 或 CSV）", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    # 先讀取檔案，產生 df
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    st.write("所有欄位名稱：", df.columns.tolist())

    # 再進行欄位偵測
    ingredient_col = None
    for col in df.columns:
        if "成分" in col.replace(" ", ""):
            ingredient_col = col
            break

    if not ingredient_col:
        st.error("找不到成分名相關欄位，請確認檔案格式。")
    else:
        st.success(f"偵測到成分名欄位：{ingredient_col}")
        # 這裡可以繼續進行 PubChem 查詢流程
