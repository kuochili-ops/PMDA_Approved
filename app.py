
import streamlit as st
import pandas as pd
import io
from fuzzywuzzy import process

st.set_page_config(page_title="日台新藥主成分比對", layout="wide")
st.title("日本新藥與台灣未註銷藥品主成分比對工具")

jp_file = st.file_uploader("請上傳日本上市新藥一覽表（Excel）", type=["xlsx"])

# 翻譯字典
category_dict = {
    "抗悪": "抗癌藥",
    "ワクチン": "疫苗",
    "血液": "血液製劑",
    "バイオ": "生物製劑",
    "放射": "放射性藥品",
    "一般": "一般藥品",
    "希少疾病用医薬品": "罕見疾病用藥"
}
approval_dict = {
    "承認": "新藥核准",
    "一変": "部分變更核准"
}
company_dict = {
    "あすか製薬㈱": "Aska Pharmaceutical",
    "ノバルティスファーマ㈱": "Novartis Pharma",
}
ingredient_dict = {
    "ドロスピレノン": "Drospirenone",
    "イプタコパン塩酸塩水和物": "Iptacopan Hydrochloride Hydrate",
}
indication_dict = {
    "避妊を効能・効果とする新効能・新用量・その他の医薬品": "避孕",
    "C3腎症を効能・効果とする新効能医薬品": "C3腎症治療",
}

def parse_japan_excel(file):
    xls = pd.ExcelFile(file)
    all_rows = []
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet, header=2)
        except Exception as e:
            st.warning(f"{sheet} 分頁讀取失敗：{e}")
            continue
        df = df.rename(columns={
            "分野": "藥品類別",
            "承認日": "核准日",
            "No.": "項次編號",
            "販　　売　　名 (　会　社　名、　法　人　番　号)": "商品名與藥商",
            "承認": "核可狀態",
            "成  分  名 (下線:新有効成分)": "主成分",
            "効能・効果等": "用途"
        })
        df = df.dropna(how='all')
        for _, row in df.iterrows():
            prod_info = str(row.get("商品名與藥商", ""))
            ingr_jp = str(row.get("主成分", "")).strip()
            if not prod_info or not ingr_jp:
                continue
            if "（" in prod_info:
                prod_name = prod_info.split("（")[0].strip()
                company_jp = prod_info.split("（")[-1].replace("）", "").strip()
            else:
                prod_name = prod_info
                company_jp = ""
            ingr_en = ingredient_dict.get(ingr_jp, ingr_jp)
            company_en = company_dict.get(company_jp, company_jp)
            indication_jp = str(row.get("用途", "")).strip()
            indication_zh = indication_dict.get(indication_jp, indication_jp)
            category_zh = category_dict.get(row.get("藥品類別", ""), row.get("藥品類別", ""))
            approval_zh = approval_dict.get(row.get("核可狀態", ""), row.get("核可狀態", ""))
            all_rows.append({
                "月份": sheet,
                "藥品類別": category_zh,
                "核准日": row.get("核准日", ""),
                "商品名": prod_name,
                "藥商": company_en,
                "主成分": ingr_en,
                "用途": indication_zh,
                "核可狀態": approval_zh,
            })
    return pd.DataFrame(all_rows)

if jp_file:
    with st.spinner("資料處理中，請稍候..."):
        jp_df = parse_japan_excel(jp_file)
        tw_df = pd.read_csv("37_2.csv")

        st.subheader("日本新藥項目資訊")
        st.dataframe(jp_df)

        st.subheader("主成分比對台灣未註銷藥品結果（含模糊比對）")
        results = []
        tw_ingredients = tw_df["主成分"].astype(str).str.strip().tolist()

        for _, row in jp_df.iterrows():
            jp_inn = str(row["主成分"]).strip()
            # 模糊比對
            match, score = process.extractOne(jp_inn, tw_ingredients)
            if score >= 80:  # 相似度門檻
                matched = tw_df[tw_df["主成分"].astype(str).str.strip() == match]
                for _, tw_row in matched.iterrows():
                    results.append({
                        "日本主成分": jp_inn,
                        "日本商品名": row["商品名"],
                        "日本核准日": row["核准日"],
                        "日本用途": row["用途"],
                        "日本藥商": row["藥商"],
                        "日本核可狀態": row["核可狀態"],
                        "台灣商品名": tw_row.get("商品名", ""),
                        "台灣主成分": tw_row.get("主成分", ""),
                        "台灣劑型/規格": tw_row.get("劑型/規格", ""),
                        "台灣藥商": tw_row.get("藥商", ""),
                        "台灣許可證號": tw_row.get("許可證號", ""),
                        "比對相似度": score
                    })
            else:
                results.append({
                    "日本主成分": jp_inn,
                    "日本商品名": row["商品名"],
                    "日本核准日": row["核准日"],
                    "日本用途": row["用途"],
                    "日本藥商": row["藥商"],
                    "日本核可狀態": row["核可狀態"],
                    "台灣商品名": "無上市品項",
                    "台灣主成分": "",
                    "台灣劑型/規格": "",
                    "台灣藥商": "",
                    "台灣許可證號": "",
                    "比對相似度": score
                })

        result_df = pd.DataFrame(results)
        st.dataframe(result_df)

        # CSV 下載
        csv = result_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("下載比對結果 (CSV)", csv, "compare_result.csv", "text/csv")

        # Excel 下載
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='比對結果')
        st.download_button("下載比對結果 (Excel)", output.getvalue(), "compare_result.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("請上傳日本新藥 Excel 檔案。")

st.markdown("---")
