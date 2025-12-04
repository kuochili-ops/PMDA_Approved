
def parse_japan_excel(file):
    xls = pd.ExcelFile(file)
    all_rows = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet)
        st.write(f"{sheet} 欄位名稱：", df.columns.tolist())  # 顯示欄位名稱
        for i, row in df.iterrows():
            # 這裡請根據實際欄位名稱調整
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
