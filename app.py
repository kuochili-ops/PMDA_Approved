
import streamlit as st
import pandas as pd
import io

st.title("PMDA新藥品目中英文對照表產生器")

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"])
if uploaded_file is not None:
    # 讀取 Excel 檔案
    xls = pd.ExcelFile(uploaded_file, engine="openpyxl")
    sheet_names = xls.sheet_names
    # 讓使用者選擇分頁（月份）
    target_sheet = st.selectbox("請選擇月份分頁", sheet_names)
    df = pd.read_excel(uploaded_file, sheet_name=target_sheet, header=2, engine="openpyxl")
    st.write("原始欄位名稱：", df.columns.tolist())

    # 欄位清理
    def clean_col(col):
        return col.replace("　", "").replace(" ", "").replace("\\", "").replace("(", "").replace(")", "")

    df.columns = [clean_col(col) for col in df.columns]

    # 自動尋找主要欄位
    def find_col(cols, keywords):
        for kw in keywords:
            for col in cols:
                if kw in col:
                    return col
        return None

    approval_col = find_col(df.columns, ["承認日"])
    product_col = find_col(df.columns, ["販売名", "売名"])
    ingredient_col = find_col(df.columns, ["成分名"])
    indication_col = find_col(df.columns, ["効能・効果等"])

    # 選取必要欄位
    df = df[[approval_col, product_col, ingredient_col, indication_col]]

    # 建立中英文對照表格
    translated_rows = []
    for _, row in df.iterrows():
        approval_date = str(row[approval_col]).strip()
        product_info = str(row[product_col]).strip()
        ingredient = str(row[ingredient_col]).strip()
        indication = str(row[indication_col]).strip()
        # 分離商品名與公司名
        if "、" in product_info:
            product_name = product_info.split("、")[0].strip()
            company_name = product_info.split("、")[-1].strip()
        elif "(" in product_info:
            product_name = product_info.split("(")[0].strip()
            company_name = product_info.split("(")[-1].replace(")", "").strip()
        else:
            product_name = product_info
            company_name = ""
        # 備註判斷
        note = ""
        if "希少疾病用医薬品" in indication:
            note = "希少疾病用 Orphan drug"
        elif "新有効成分" in indication:
            note = "新有效成分 New active ingredient"
        elif "新効能" in indication:
            note = "新適應症 New indication"
        elif "新用量" in indication:
            note = "新用量 New dosage"
        translated_rows.append({
            "承認日 Approval Date": approval_date,
            "藥品名稱 Product Name": product_name,
            "公司名稱 Company": company_name,
            "成分名稱 Ingredient": ingredient,
            "適應症/用途 Indication/Use": indication,
            "備註 Note": note
        })

    result_df = pd.DataFrame(translated_rows)
    st.dataframe(result_df)

    # 產生 Excel 檔案 bytes
    output = io.BytesIO()
    result_df.to_excel(output, index=False, encoding="utf-8")
    output.seek(0)

    st.download_button(
        label="下載中英文對照表 Excel",
        data=output,
        file_name="新藥中英文對照.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("請先上傳檔案！")
