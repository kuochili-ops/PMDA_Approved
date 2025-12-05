
import streamlit as st
import pandas as pd

uploaded_file = st.file_uploader("請上傳藥品清單檔案（Excel 或 CSV）", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    # 嘗試不同 skiprows 直到找到正確欄位
    for skip in range(2, 6):
        df = pd.read_excel(uploaded_file, skiprows=skip)
        st.write(f"skiprows={skip} 欄位名稱：", df.columns.tolist())
        # 自動找成分欄位
        ingredient_col = None
        for col in df.columns:
            if "成分" in col.replace(" ", ""):
                ingredient_col = col
                break
        if ingredient_col:
            st.success(f"偵測到成分名欄位：{ingredient_col}（skiprows={skip}）")
            break
    else:
        st.error("找不到成分名相關欄位，請確認檔案格式。")
