
import streamlit as st
import pandas as pd
import requests
import re
import time
import os

# ====== API 金鑰設定 ======
AZURE_KEY = st.secrets["AZURE_KEY"]
AZURE_REGION = st.secrets["AZURE_REGION"]
endpoint = "https://api.cognitive.microsofttranslator.com/translate"
headers = {
    "Ocp-Apim-Subscription-Key": AZURE_KEY,
    "Ocp-Apim-Subscription-Region": AZURE_REGION,
    "Content-type": "application/json"
}

def get_kegg_trade_name_and_japic(jp_name):
    url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={jp_name}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            # 解析 japic code
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            japic_code = japic_match.group(1) if japic_match else None
            # 解析欧文商標名
            trade_match = re.search(r'欧文商標名</span>\s*:\s*([^\s<]+(?:\s[^\s<]+)*)', resp.text)
            trade_name = trade_match.group(1).strip() if trade_match else ""
            return japic_code, trade_name
    except Exception:
        pass
    return None, ""

def ms_translator(text, from_lang="ja"):
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

def find_header_row(df):
    for i, row in df.iterrows():
        row_str = ''.join([str(cell) for cell in row if pd.notnull(cell)])
        row_str_clean = re.sub(r'[\s\u3000\r\n\t]+', '', row_str)
        if row_str_clean.count('名') >= 2 and '成' in row_str_clean and '販' in row_str_clean:
            return i
        if ('成分名' in row_str_clean or ('成' in row_str_clean and '分' in row_str_clean and '名' in row_str_clean)) \
           and ('販売名' in row_str_clean or '販賣名' in row_str_clean or ('販' in row_str_clean and '売' in row_str_clean and '名' in row_str_clean)):
            return i
    return None

def is_number(val):
    try:
        val_str = str(val).strip()
        val_str = val_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        float(val_str)
        return True
    except:
        return False

def clean_dataframe(df):
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    rename_map = {}
    for col in df.columns:
        col_str = str(col)
        col_clean = re.sub(r'[\s\u3000\r\n\t]+', '', col_str)
        col_clean = re.sub(r'（.*?）|\(.*?\)', '', col_clean)
        if '販' in col_clean and '名' in col_clean:
            rename_map[col] = '販賣名/公司 (日文)'
        elif '成' in col_clean and '名' in col_clean:
            rename_map[col] = '成分名 (日文)'
        elif 'No' in col_clean:
            rename_map[col] = 'No.'
    df = df.rename(columns=rename_map)
    st.write(f"重命名後欄位：{list(df.columns)}")
    if 'No.' in df.columns:
        st.write("No. 欄位前 20 筆：", df['No.'].head(20).tolist())
    if {'No.', '販賣名/公司 (日文)', '成分名 (日文)'}.issubset(df.columns):
        df = df[
            df['No.'].apply(is_number) &
            df['販賣名/公司 (日文)'].astype(str).str.strip().ne('') &
            df['成分名 (日文)'].astype(str).str.strip().ne('')
        ]
    elif '成分名 (日文)' in df.columns:
        df = df[df['成分名 (日文)'].notnull() & (df['成分名 (日文)'].astype(str).str.strip() != '')]
    else:
        df = pd.DataFrame()
    if not df.empty:
        df = df.dropna(how='all')
        df = df[~(df.applymap(lambda x: str(x).strip() == '').all(axis=1))]
        df = df.reset_index(drop=True)
    return df

def save_sheets_to_csv_auto_header(uploaded_file):
    xls = pd.ExcelFile(uploaded_file)
    sheet_map = {}
    for sheet_name in xls.sheet_names:
        raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        st.write(f"分頁「{sheet_name}」原始資料預覽：")
        st.dataframe(raw_df.head(15))
        header_row = find_header_row(raw_df)
        if header_row is None:
            st.write(f"分頁「{sheet_name}」找不到欄位名稱，已跳過。")
            continue
        df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
        st.write(f"分頁「{sheet_name}」偵測到欄位名稱行 index={header_row}，實際欄位名稱：{list(df.columns)}")
        raw_count = len(df)
        st.write(f"分頁「{sheet_name}」清理前筆數：{raw_count}")
        df = clean_dataframe(df)
        clean_count = len(df)
        st.write(f"分頁「{sheet_name}」清理後筆數：{clean_count}")
        if df is None or df.empty:
            st.write(f"分頁「{sheet_name}」無有效資料，已跳過。")
            continue
        month_match = re.search(r'(\d+)月', sheet_name)
        if not month_match:
            for col in df.columns:
                m = re.search(r'(\d+)月', str(col))
                if m:
                    month_match = m
                    break
        if month_match:
            month = month_match.group(1) + "月"
        else:
            month = sheet_name
        csv_name = f"{month}.csv"
        df.to_csv(csv_name, index=False, encoding="utf-8")
        sheet_map[month] = (csv_name, raw_count, clean_count)
    return sheet_map

def translate_and_combine(df):
    st.write(f"清理後有效資料共 {len(df)} 筆")
    trade_name_en_list = []
    trade_name_source_list = []
    ingredient_en_list = []
    ingredient_source_list = []
    progress = st.empty()
    for idx, row in df.iterrows():
        progress.info(f"第 {idx+1} 項翻譯中…")
        jp_trade_name_raw = str(row.get('販賣名/公司 (日文)', ''))
        japic_code, trade_name_en = get_kegg_trade_name_and_japic(jp_trade_name_raw)
        if trade_name_en:
            trade_name_source = "KEGG搜尋頁"
        else:
            trade_name_en = ms_translator(jp_trade_name_raw)
            trade_name_source = "自動翻譯"
        ingredient_en = ms_translator(str(row.get('成分名 (日文)', '')))
        ingredient_source = "自動翻譯"
        trade_name_en_list.append(trade_name_en)
        trade_name_source_list.append(trade_name_source)
        ingredient_en_list.append(ingredient_en)
        ingredient_source_list.append(ingredient_source)
        time.sleep(0.34)
    progress.success("全部翻譯完成！")
    df['Trade Name/Company (English)'] = trade_name_en_list
    df['Trade Name/Company (來源)'] = trade_name_source_list
    df['Ingredient Name (English)'] = ingredient_en_list
    df['Ingredient Name (來源)'] = ingredient_source_list
    return df

def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器 (自動分頁轉 CSV + 翻譯)")
    uploaded_file = st.file_uploader("上傳 PMDA 公告 Excel 檔案", type=['xlsx', 'xls'])
    if uploaded_file:
        st.info("正在自動分割各月份（最大容錯）...")
        month_csv_map = save_sheets_to_csv_auto_header(uploaded_file)
        if not month_csv_map:
            st.warning("未偵測到任何有效分頁。")
            return
        for month, (csv_name, raw_count, clean_count) in month_csv_map.items():
            st.subheader(f"{month} 翻譯結果")
            st.write(f"原始筆數：{raw_count}，清理後：{clean_count}")
            df = pd.read_csv(csv_name, encoding="utf-8")
            if df.empty:
                st.warning(f"{month} 無有效資料，已跳過。")
                continue
            translated_df = translate_and_combine(df)
            st.dataframe(translated_df, use_container_width=True, hide_index=True)
            csv_export = translated_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"📥 下載 {month} 翻譯結果 (CSV)",
                data=csv_export,
                file_name=f"{month}_Translated.csv",
                mime='text/csv'
            )
            os.remove(csv_name)

if __name__ == "__main__":
    main()
