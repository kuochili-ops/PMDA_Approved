
import streamlit as st
import pandas as pd

st.set_page_config(page_title="日台新藥主成分比對", layout="wide")
st.title("日本新藥與台灣未註銷藥品主成分比對工具")

jp_file = st.file_uploader("請上傳日本上市新藥一覽表（Excel）", type=["xlsx"])

def parse_japan_excel(file):
    xls = pd.ExcelFile(file)
    all_rows = []
    for sheet in xls.sheet_names:
        # 先讀前幾列，找出欄位名稱
        df_raw = pd.read_excel(xls, sheet, header=None)
        st.write(f"{sheet} 前10列：")
        st.dataframe(df_raw.head(10))
        # 假設欄位名稱在第2列（index=1），請根據實際情況調整
        df = pd.read_excel(xls, sheet, header=1)
        st.write(f"{sheet} 欄位名稱：", df.columns.tolist())
        for i, row in df.iterrows():
            if not isinstance(row.get("成  分  名\n(下線:新有効成分)", None), str):
                continue
            all_rows.append({
                "藥品類別": row.get("分野", ""),
                "核准日": row.get("承認日", ""),
                "商品名與藥商": row.get("販　　売　　名\n(　会　社　名、　法　人　番　号)", ""),
                "主成分": row.get("成  分  名\n(下線:新有効成分)", ""),
                "劑型/規格": row.get("No.", ""),
                "用途": row.get("効能・効果等", ""),
                "承認狀態": row.get("承認", ""),
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
                    "日本商品名與藥商": row["商品名與藥商"],
                    "日本核准日": row["核准日"],
                    "日本用途": row["用途"],
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
                "日本商品名與藥商": row["商品名與藥商"],
                "日本核准日": row["核准日"],
                "日本用途": row["用途"],
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
