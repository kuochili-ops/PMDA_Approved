
import streamlit as st
import pandas as pd
import io

st.title("PMDA新藥品目中英文對照表產生器")

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"])
if uploaded_file is not None:
    # 讀取 Excel 檔案（自動抓第一個工作表，所有欄位以字串處理）
    df = pd.read_excel(uploaded_file, dtype=str)
    # 清理全空白列
    df = df.dropna(how='all')
    # 只保留有「承認日 Approval Date」的資料列
    if '承認日 Approval Date' in df.columns:
        df = df[df['承認日 Approval Date'].notna()]
    # 預覽資料
    st.dataframe(df)

    # 產生 Excel 檔案 bytes
    output = io.BytesIO()
    # encoding 參數在 to_excel 不需要，移除避免錯誤
    df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        label="下載中英文對照表 Excel",
        data=output,
        file_name="新藥中英文對照.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("請先上傳檔案！")
