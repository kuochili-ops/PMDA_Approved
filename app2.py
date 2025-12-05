
import streamlit as st
import pandas as pd
import requests
import io
import re
import time

# 讀取 Streamlit Cloud Secrets Manager 的金鑰
AZURE_KEY = st.secrets["AZURE_KEY"]
AZURE_REGION = st.secrets["AZURE_REGION"]

# Microsoft Translator API 設定
endpoint = "https://api.cognitive.microsofttranslator.com/translate"
headers = {
    "Ocp-Apim-Subscription-Key": AZURE_KEY,
    "Ocp-Apim-Subscription-Region": AZURE_REGION,
    "Content-type": "application/json"
}

def kegg_drug_english_names(jp_name):
    """查詢 KEGG API，回傳商品名與學名（英文），查不到則回傳空字串"""
    url = f"https://rest.kegg.jp/find/drug/{jp_name}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok and resp.text:
            line = resp.text.split('\n')[0]
            fields = line.split()
            if len(fields) > 1:
                names = [n.strip() for n in fields[1].split(';')]
                # 商品名（英文）：通常是首字大寫且有非全大寫
                trade_names = [n for n in names if n and n[0].isupper() and not n.isupper()]
                # 學名（英文）：全英文且首字母大寫
                english_names = [n for n in names if n and n[0].isupper() and n.isalpha()]
                return {
                    "trade_name_en_kegg": trade_names[0] if trade_names else "",
                    "ingredient_en_kegg": english_names[0] if english_names else ""
                }
    except Exception:
        pass
    return {"trade_name_en_kegg": "", "ingredient_en_kegg": ""}

def ms_translator(text, from_lang="ja"):
    """Microsoft Translator API 單句翻譯成英文"""
    body = [{"text": text}]
    params = {"api-version": "3.0", "from": from_lang, "to": ["en"]}
    try:
        resp = requests.post(endpoint, params=params, headers=headers, json=body, timeout=10)
        if resp.ok:
            data = resp.json()
            return data[0]["translations"][0]["text"]
    except Exception:
        pass
    return ""

def ms_translator_multi(japanese_data_list):
    """Microsoft Translator API 批次翻譯商品名、功效等（繁中、英文）"""
    results = []
    for item in japanese_data_list:
        body = [{"text": f"{item['trade_name_jp']} {item['ingredient_jp']} {item['efficacy_jp']}"}]
        params = {"api-version": "3.0", "from": "ja", "to": ["zh-Hant", "en"]}
        resp = requests.post(endpoint, params=params, headers=headers, json=body)
        data = resp.json()[0]["translations"]
        results.append({
            "trade_name_zh": data[0]["text"],
            "trade_name_en_translator": data[1]["text"],
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
        df.columns = df.columns.str.replace(r'[\s\n\u3000]', '', regex=True)
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
    st.info("正在查詢主成分與商品名英文（KEGG→Microsoft Translator）...")
    trade_name_en_list = []
    ingredient_en_list = []
    for idx, row in df.iterrows():
        # 先查 KEGG
        kegg_result = kegg_drug_english_names(row['Trade_Name_JP'])
        trade_name_en = kegg_result["trade_name_en_kegg"]
        ingredient_en = kegg_result["ingredient_en_kegg"]
        # 若查不到再用 Microsoft Translator
        if not trade_name_en:
            trade_name_en = ms_translator(row['Trade_Name_JP'])
        if not ingredient_en:
            ingredient_en = ms_translator(row['Ingredient_JP'])
        trade_name_en_list.append(trade_name_en)
        ingredient_en_list.append(ingredient_en)
        time.sleep(0.34)  # KEGG 頻率限制

    # 其他欄位翻譯
    data_for_translation = df.apply(
        lambda row: {
            'trade_name_jp': row['Trade_Name_JP'],
            'ingredient_jp': row['Ingredient_JP'],
            'efficacy_jp': row['Efficacy_JP']
        },
        axis=1
    ).tolist()
    st.info(f"正在翻譯 {len(data_for_translation)} 筆藥品資料（商品名、功效）...")
    translated_results = ms_translator_multi(data_for_translation)
    df_translated = pd.DataFrame(translated_results)

    # 合併結果
    final_df = pd.concat([df.reset_index(drop=True), df_translated.reset_index(drop=True)], axis=1)
    final_df['Trade Name/Company (English)'] = trade_name_en_list
    final_df['Ingredient Name (English)'] = ingredient_en_list

    # 欄位顯示名稱
    display_names = {
        'Category': '分野 (Category)',
        'Approval_Date': '承認日',
        'No': 'No.',
        'Trade_Name_JP': '販賣名/公司 (日文)',
        'Trade Name/Company (English)': 'Trade Name/Company (English)',
        'Ingredient_JP': '成分名 (日文)',
        'Ingredient Name (English)': 'Ingredient Name (English)',
        'Approval_Type': '承認類型',
        'Efficacy_JP': '功效・效果 (日文)',
        'efficacy_zh': '功效・效果 (中文)',
        'efficacy_en': 'Efficacy/Effects (English)'
    }
    final_df = final_df.rename(columns=display_names)
    # 只保留需要的欄位
    keep_cols = [
        '分野 (Category)', '承認日', 'No.', '販賣名/公司 (日文)', 'Trade Name/Company (English)',
        '成分名 (日文)', 'Ingredient Name (English)', '承認類型',
        '功效・效果 (日文)', '功效・效果 (中文)', 'Efficacy/Effects (English)'
    ]
    final_df = final_df[[col for col in keep_cols if col in final_df.columns]]
    return final_df

def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器 (KEGG+Microsoft Translator 版)")
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
                    # 分段依月份顯示
                    translated_df["月份"] = pd.to_datetime(translated_df["承認日"], errors="coerce").dt.month.astype(str) + "月"
                    month_groups = translated_df.groupby("月份")
                    tabs = st.tabs([f"{month}" for month in month_groups.groups.keys()])
                    for i, (month, group_df) in enumerate(month_groups):
                        with tabs[i]:
                            st.header(f"{month} 翻譯結果")
                            st.dataframe(group_df, use_container_width=True, hide_index=True)
                            # 下載按鈕
                            csv_export = group_df.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label=f"📥 下載 {month} 翻譯結果 (CSV)",
                                data=csv_export,
                                file_name=f"{uploaded_file.name}_{month}_Translated.csv",
                                mime='text/csv'
                            )

if __name__ == "__main__":
