
import streamlit as st
import pandas as pd
import io
import re
import requests

st.title("PMDA新藥品目商品名、公司名分欄與成分英文名自動比對")

def kegg_drug_lookup(japanese_name):
    """用 KEGG DRUG API 查詢片假名成分英文名（簡易版）"""
    # KEGG DRUG API: https://www.genome.jp/dbget-bin/www_bfind_sub?mode=bfind&dbkey=drug&keywords=
    url = f"https://www.genome.jp/dbget-bin/www_bfind_sub?mode=bfind&dbkey=drug&keywords={japanese_name}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            # 簡單解析：找 <pre> 標籤內的英文名
            lines = resp.text.splitlines()
            for line in lines:
                # 例：D00001 Aspirin; アスピリン
                if japanese_name in line:
                    parts = line.split()
                    if len(parts) > 1:
                        return parts[1].split(';')[0]  # 取英文名
        return ""
    except Exception:
        return ""

uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"])
if uploaded_file is not None:
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
        match = re.match(r"^(.*?)(?:（|\()(.*?)(?:）|\))$", val)
        if match:
            product_name = match.group(1).strip()
            company_info = match.group(2).strip()
            company_name = company_info.split("、")[0].strip()
        else:
            product_name = val
            company_name = ""
        return pd.Series([product_name, company_name])

    df[['商品名', '公司名']] = df[product_col].apply(split_product_company)

    # 成分英文名自動比對（以 KEGG DRUG 為例）
    if '成分名' in df.columns:
        st.info("正在查詢成分英文名，請稍候...")
        df['成分英文名'] = df['成分名'].apply(lambda x: kegg_drug_lookup(str(x)) if pd.notna(x) else "")
    else:
        st.warning("找不到成分名欄位，未進行英文名比對。")

    # 預覽分欄結果
    st.dataframe(df[['商品名', '公司名', '成分名', '成分英文名']] if '成分英文名' in df.columns else df[['商品名', '公司名', '成分名']])

    # 下載分欄後 Excel
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    st.download_button(
        label="下載分欄後 Excel（含成分英文名）",
        data=output,
        file_name="商品名_公司名_成分英文名分欄.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
