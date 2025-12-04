
import streamlit as st
import pandas as pd

st.set_page_config(page_title="日台新藥主成分比對", layout="wide")
st.title("日本新藥與台灣未註銷藥品主成分比對工具")

jp_file = st.file_uploader("請上傳日本上市新藥一覽表（Excel）", type=["xlsx"])

# 這裡可建立藥商、主成分、用途的對照表或串接API
company_dict = {
    "あすか製薬㈱": "Aska Pharmaceutical",
    "ノバルティスファーマ㈱": "Novartis Pharma",
    # ...可自行擴充
}
ingredient_dict = {
    "ドロスピレノン": "Drospirenone",
    "イプタコパン塩酸塩水和物": "Iptacopan Hydrochloride Hydrate",
    # ...可自行擴充
}
indication_dict = {
    "避妊を効能・効果とする新効能・新用量・その他の医薬品": "避孕",
    "C3腎症を効能・効果とする新効能医薬品": "C3腎症治療",
    # ...可自行擴充
}

def parse_japan_excel(file):
    xls = pd.ExcelFile(file)
    all_rows = []
    for sheet in xls.sheet_names:
        # 跳過前兩列，header=2
        df = pd.read_excel(xls, sheet, header=2)
        # 欄位標準化
        df = df.rename(columns={
            "分野": "藥品類別",
            "承認日": "核准日",
            "No.": "項次編號",
            "販　　売　　名 (　会　社　名、　法　人　番　号)": "商品名與藥商",
            "承認": "承認狀態",
            "成  分  名 (下線:新有効成分)": "主成分",
            "効能・効果等": "用途"
        })
        for i, row in df.iterrows():
            # 商品名與藥商分開
            prod_info = str(row.get("商品名與藥商", ""))
            if "（" in prod_info:
                prod_name = prod_info.split("（")[0].strip()
                company_jp = prod_info.split("（")[-1].replace("）", "").strip()
            else:
                prod_name = prod_info
                company_jp = ""
            # 主成分轉英文
            ingr_jp = str(row.get("主成分", "")).replace("（下線:新有効成分）", "").strip()
            ingr_en = ingredient_dict.get(ingr_jp, ingr_jp)
            # 藥商轉英文
            company_en = company_dict.get(company_jp, company_jp)
            # 用途轉中文
            indication_jp = str(row.get("用途", "")).strip()
            indication_zh = indication_dict.get(indication_jp, indication_jp)
            all_rows.append({
                "藥品類別": row.get("藥品類別", ""),
                "核准日": row.get("核准日", ""),
                "商品名": prod_name,  # 保留片假名
                "藥商": company_en,   # 中文或英文
                "主成分": ingr_en,    # 英文或中文
                "用途": indication_zh, # 中文或英文簡介
                "承認狀態": row.get("承認狀態", ""),
            })
    return pd.DataFrame(all_rows)

if jp_file:
    jp_df = parse_japan_excel(jp_file)
    tw_df = pd.read_csv("37_2.csv")
    
    st.subheader("日本新藥項目資訊")
    st.dataframe(jp_df)
    
    st.subheader("主成分比對台灣未註銷藥品結果")
    results = []
    for idx, row in jp_df.iterrows():
        jp_inn = str(row["主成分"]).strip()
        matched = tw_df[tw_df["主成分"].astype(str).str.strip() == jp_inn]
        if not matched.empty:
            for _, tw_row in matched.iterrows():
                results.append({
                    "日本主成分": jp_inn,
                    "日本商品名": row["商品名"],
                    "日本核准日": row["核准日"],
                    "日本用途": row["用途"],
                    "日本藥商": row["藥商"],
                    "日本承認狀態": row["承認狀態"],
                    "台灣商品名": tw_row.get("商品名", ""),
                    "台灣主成分": tw_row.get("主成分", ""),
                    "台灣劑型/規格": tw_row.get("劑型/規格", ""),
                    "台灣藥商": tw_row.get("藥商", ""),
                    "台灣許可證號": tw_row.get("許可證號", ""),
                })
        else:
            results.append({
                "日本主成分": jp_inn,
                "日本商品名": row["商品名"],
                "日本核准日": row["核准日"],
                "日本用途": row["用途"],
                "日本藥商": row["藥商"],
                "日本承認狀態": row["承認狀態"],
                "台灣商品名": "無上市品項",
                "台灣主成分": "",
                "台灣劑型/規格": "",
                "台灣藥商": "",
                "台灣許可證號": "",
            })
    result_df = pd.DataFrame(results)
    st.dataframe(result_df)
    csv = result_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("下載比對結果 (CSV)", csv, "compare_result.csv", "text/csv")
else:
    st.info("請上傳日本新藥 Excel 檔案。")

st.markdown("---")
st.markdown("本工具僅供學術或內部參考，資料來源請自行確認。")
