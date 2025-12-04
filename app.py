import streamlit as st
import pandas as pd
import requests
import io
import re

# 從 Streamlit Cloud Secrets Manager 讀取金鑰
AZURE_KEY = st.secrets["AZURE_KEY"]
AZURE_REGION = st.secrets["AZURE_REGION"]

endpoint = "https://api.cognitive.microsofttranslator.com/translate"
params = {"api-version": "3.0", "from": "ja", "to": ["zh-Hant", "en"]}
headers = {
    "Ocp-Apim-Subscription-Key": AZURE_KEY,
    "Ocp-Apim-Subscription-Region": AZURE_REGION,
    "Content-type": "application/json"
}
def translate_drug_info_ms(japanese_data_list):
    results = []
    for item in japanese_data_list:
        body = [{"text": f"{item['trade_name_jp']} {item['ingredient_jp']} {item['efficacy_jp']}"}]
        response = requests.post(endpoint, params=params, headers=headers, json=body)
        data = response.json()[0]["translations"]

        results.append({
            "trade_name_zh": data[0]["text"],
            "trade_name_en": data[1]["text"],
            "ingredient_zh": data[0]["text"],
            "ingredient_en": data[1]["text"],
            "efficacy_zh": data[0]["text"],
            "efficacy_en": data[1]["text"]
        })
    return results
def process_uploaded_file(uploaded_file):
    try:
        filename = uploaded_file.name
        file_type = uploaded_file.type
        filename_lower = filename.lower()

        if 'excel' in file_type or filename_lower.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file, sheet_name=0, skiprows=2)
        elif 'csv' in file_type or filename_lower.endswith('.csv'):
            csv_data = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            df = pd.read_csv(csv_data, skiprows=2)
        else:
            st.error("不支援的檔案格式。")
            return None

        # 清理欄位名稱
        df.columns = df.columns.str.replace(r'[\s\n　]', '', regex=True)

        # 正則化欄位對應
        rename_map = {}
        for col in df.columns:
            if re.match(r'^販.*売.*名.*', col):
                rename_map[col] = 'Trade_Name_JP'
            elif re.match(r'^成.*分.*名.*', col):
                rename_map[col] = 'Ingredient_JP'
            elif re.match(r'^効能.*効果.*', col):
                rename_map[col] = 'Efficacy_JP'
            elif col == '承認日':
                rename_map[col] = 'Approval_Date'
            elif col == '分野':
                rename_map[col] = 'Category'
            elif col.startswith('No'):
                rename_map[col] = 'No'
            elif col.startswith('承認'):
                rename_map[col] = 'Approval_Type'

        df = df.rename(columns=rename_map)
        key_cols = ['Category', 'Approval_Date', 'No', 'Trade_Name_JP', 'Approval_Type', 'Ingredient_JP', 'Efficacy_JP']
        df = df[key_cols].dropna(subset=['Trade_Name_JP', 'Ingredient_JP', 'Efficacy_JP'], how='all').reset_index(drop=True)

        return df
    except Exception as e:
        st.error(f"處理檔案 {uploaded_file.name} 時發生錯誤: {e}")
        return None
def translate_and_combine(df):
    data_for_translation = df.apply(
        lambda row: {
            'trade_name_jp': row['Trade_Name_JP'],
            'ingredient_jp': row['Ingredient_JP'],
            'efficacy_jp': row['Efficacy_JP']
        },
        axis=1
    ).tolist()

    st.info(f"正在翻譯 {len(data_for_translation)} 筆藥品資料...")
    translated_results = translate_drug_info_ms(data_for_translation)

    df_translated = pd.DataFrame(translated_results)
    final_df = pd.concat([df.reset_index(drop=True), df_translated.reset_index(drop=True)], axis=1)

    display_names = {
        'Category': '分野 (Category)',
        'Approval_Date': '承認日',
        'No': 'No.',
        'Trade_Name_JP': '販賣名/公司 (日文)',
        'trade_name_zh': '商品名稱/公司 (中文)',
        'trade_name_en': 'Trade Name/Company (English)',
        'Ingredient_JP': '成分名 (日文)',
        'ingredient_zh': '成分名稱 (中文)',
        'ingredient_en': 'Ingredient Name (English)',
        'Approval_Type': '承認類型',
        'Efficacy_JP': '功效・效果 (日文)',
        'efficacy_zh': '功效・效果 (中文)',
        'efficacy_en': 'Efficacy/Effects (English)'
    }
    final_df = final_df.rename(columns=display_names)
    return final_df
def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器 (Microsoft Translator 版)")

    uploaded_files = st.file_uploader(
        "上傳新藥列表檔案 (CSV/XLSX)", 
        type=['csv', 'xlsx', 'xls'], 
        accept_multiple_files=True
    )

    if uploaded_files:
        for uploaded_file in uploaded_files:
            df = process_uploaded_file(uploaded_file)
            if df is not None:
                translated_df = translate_and_combine(df)
                if translated_df is not None:
                    st.subheader(f"翻譯結果：{uploaded_file.name}")

                    # 🔑 分段依月份顯示
                    translated_df["月份"] = pd.to_datetime(translated_df["承認日"], errors="coerce").dt.month.astype(str) + "月"

                    month_groups = translated_df.groupby("月份")
                    tabs = st.tabs([f"{month}" for month in month_groups.groups.keys()])

                    for i, (month, group_df) in enumerate(month_groups):
                        with tabs[i]:
                            st.header(f"{month} 翻譯結果")
                            st.dataframe(group_df, use_container_width=True, hide_index=True)

                            # 提供下載按鈕
                            csv_export = group_df.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label=f"📥 下載 {month} 翻譯結果 (CSV)",
                                data=csv_export,
                                file_name=f"{uploaded_file.name}_{month}_Translated.csv",
                                mime='text/csv'
                            )

if __name__ == "__main__":
    main()
