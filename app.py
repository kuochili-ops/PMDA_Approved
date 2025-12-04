
import streamlit as st
import pandas as pd

st.set_page_config(page_title="日台新藥主成分比對", layout="wide")

st.title("日本新藥與台灣未註銷藥品主成分比對工具")

# 上傳日本新藥 Excel
jp_file = st.file_uploader("請上傳日本上市新藥一覽表（Excel）", type=["xlsx"])
# 上傳台灣未註銷藥品許可證資料集
tw_file = st.file_uploader("請上傳台灣未註銷藥品許可證資料集（CSV）", type=["csv"])

def parse_japan_excel(file):
    # 讀取所有 sheet
    xls = pd.ExcelFile(file)
    all_rows = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet)
        # 嘗試找出主成分、商品名、核准日等欄位
        # 這裡以你提供的格式為例，實際欄位需根據檔案調整
        for i, row in df.iterrows():
            # 跳過非資料列
            if not isinstance(row.get("成 分 名", None), str):
                continue
            all_rows.append({
                "藥品類別": row.get("分野", ""),
                "核准日": row.get("承認日", ""),
                "商品名": row.get("販　　売　　名", ""),
                "主成分": row.get("成 分 名", ""),
                "劑型/規格": row.get("No.", ""),
                "用途": row.get("効能・効果等", ""),
                "藥商": row.get("(　会社名、　法人番号)", ""),
            })
    return pd.DataFrame(all_rows)

if jp_file and tw_file:
    # 解析日本新藥
    jp_df = parse_japan_excel(jp_file)
    # 讀取台灣資料集
    tw_df = pd.read_csv(tw_file)
    st.subheader("比對結果")
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
                "台灣商品名": "無上市品項",
                "台灣主成分": "",
                "台灣劑型/規格": "",
                "台灣藥商": "",
                "台灣許可證號": "",
            })
    result_df = pd.DataFrame(results)
    st.dataframe(result_df)
    # 提供下載
    csv = result_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("下載比對結果 (CSV)", csv, "compare_result.csv", "text/csv")
else:
    st.info("請同時上傳日本新藥 Excel 及台灣未註銷藥品許可證 CSV。")

st.markdown("---")
st.markdown("本工具僅供學術或內部參考，資料來源請自行確認。")

