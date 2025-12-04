
import streamlit as st
import pandas as pd

st.title("PMDA 新藥品目中英文對照表產生器")

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"])
if uploaded_file is not None:
    # 直接用 uploaded_file 讀取 Excel
    xls = pd.ExcelFile(uploaded_file, engine="openpyxl")
    sheet_names = xls.sheet_names
    # 以5月分為例
    target_sheet = [s for s in sheet_names if "5月" in s][0]
    df = pd.read_excel(uploaded_file, sheet_name=target_sheet, header=2, engine="openpyxl")
    st.write("原始欄位名稱：", df.columns.tolist())
    # ...（後續資料清理與轉換同前，請將之前的資料處理程式碼接在這裡）
else:
    st.warning("請先上傳檔案！")



# 讀取 Excel 檔案
file_path = "000277966.xlsx"
xls = pd.ExcelFile(file_path, engine="openpyxl")

# 自動尋找含「5月」的分頁名稱
target_sheet = [s for s in xls.sheet_names if "5月" in s][0]

# 讀取分頁資料，根據檔案格式調整 header（通常為2或3）
df = pd.read_excel(file_path, sheet_name=target_sheet, header=2, engine="openpyxl")

# 顯示所有欄位名稱，方便對照
print("欄位名稱：", df.columns.tolist())

# 清理欄位名稱：去除空白、全形空格、括號等
def clean_col(col):
    return col.replace("　", "").replace(" ", "").replace("\\", "").replace("(", "").replace(")", "").replace("：", "").replace("、", "").replace("分野", "").replace("No.", "").replace("承認", "").replace("日", "日").replace("一覧", "").replace("新医薬品", "").replace("分", "").replace("会社名", "公司名").replace("法人番号", "法人番號").replace("成分名", "成分名").replace("効能・効果等", "効能・効果等")

df.columns = [clean_col(col) for col in df.columns]

# 嘗試自動匹配主要欄位
def find_col(cols, keywords):
    for kw in keywords:
        for col in cols:
            if kw in col:
                return col
    return None

approval_col = find_col(df.columns, ["承認日"])
product_col = find_col(df.columns, ["販売名", "売名"])
company_col = find_col(df.columns, ["会社名", "法人番號"])
ingredient_col = find_col(df.columns, ["成分名"])
indication_col = find_col(df.columns, ["効能・効果等"])

# 若公司名與販售名在同一欄，分離處理
if company_col is None and product_col is not None:
    company_col = product_col

# 選取必要欄位
df = df[[approval_col, product_col, ingredient_col, indication_col]]

# 建立中英文對照表格
translated_rows = []
for _, row in df.iterrows():
    approval_date = str(row[approval_col]).strip()
    product_info = str(row[product_col]).strip()
    ingredient = str(row[ingredient_col]).strip()
    indication = str(row[indication_col]).strip()
    
    # 分離商品名與公司名（以括號或逗號分隔）
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

# 轉換為 DataFrame
result_df = pd.DataFrame(translated_rows)

# 儲存為 Excel 檔案
output_file = "2025年5月新藥中英文對照.xlsx"
result_df.to_excel(output_file, index=False)
print(f"已儲存：{output_file}")
