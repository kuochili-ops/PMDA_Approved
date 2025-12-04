
import streamlit as st
import pandas as pd
import io
import re

st.title("PMDA新藥品目商品名與公司名分欄工具")

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"])
if uploaded_file is not None:
    # 讀取 Excel 檔案
    df = pd.read_excel(uploaded_file, dtype=str)
    df = df.dropna(how='all')

    # 自動偵測商品名+公司名欄位（含「販」和「売」）
    col_candidates = [col for col in df.columns if "販" in col and "売" in col]
    if col_candidates:
        product_col = col_candidates[0]
    else:
        st.error("找不到商品名與公司名欄位，請確認欄位名稱。")
        st.stop()

    # 商品名與公司名分欄
    def split_product_company(val):
        val = str(val).replace('\n', '').replace('\r', '').strip()
        # 用括號分隔
        # 例：スリンダ錠28 (あすか製薬㈱、9010401018375)
        match = re.match(r"^(.*?)(?:（|\()(.*?)(?:）|\))$", val)
        if match:
            product_name = match.group(1).strip()
            company_info = match.group(2).strip()
            # 公司名通常在逗號或全形逗號前
            company_name = company_info.split("、")[0].strip()
        else:
            product_name = val
            company_name = ""
        return pd.Series([product_name, company_name])

    df[['商品名', '公司名']] = df[product_col].apply(split_product_company)

    # 預覽分欄結果
    st.dataframe(df[['商品名', '公司名']])

    # 下載分欄後 Excel
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    st.download_button(
        label="下載分欄後 Excel",
        data=output,
        file_name="商品名_公司名分欄.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("請先上傳檔案！")
