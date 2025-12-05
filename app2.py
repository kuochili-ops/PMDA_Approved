
import streamlit as st
import pandas as pd
import requests
import io
import re
import time
import os

# ...（API 金鑰與函式略，請用你現有的）

def save_sheets_to_csv(uploaded_file):
    """將每個分頁另存為 csv，回傳 {月份: csv檔名} 字典"""
    xls = pd.ExcelFile(uploaded_file)
    sheet_map = {}
    for sheet_name in xls.sheet_names:
        # 只處理有「承認品目」的分頁
        if "承認品目" in sheet_name:
            df = pd.read_excel(xls, sheet_name)
            # 取月份（如「5月」）
            month_match = re.search(r'(\d+)月', sheet_name)
            if not month_match:
                # 若分頁名沒月份，從內容找
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
            sheet_map[month] = csv_name
    return sheet_map

def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器 (自動分頁轉 CSV + 翻譯)")
    uploaded_file = st.file_uploader("上傳 PMDA 公告 Excel 檔案", type=['xlsx', 'xls'])
    if uploaded_file:
        # 1. 自動分頁另存 csv
        st.info("正在自動分割各月份...")
        month_csv_map = save_sheets_to_csv(uploaded_file)
        if not month_csv_map:
            st.warning("未偵測到任何月份分頁。")
            return
        # 2. 每個月份 csv 讀取、翻譯、顯示
        for month, csv_name in month_csv_map.items():
            st.subheader(f"{month} 翻譯結果")
            df = pd.read_csv(csv_name, encoding="utf-8")
            # 這裡直接呼叫你現有的翻譯主流程
            translated_df = translate_and_combine(df)
            st.dataframe(translated_df, use_container_width=True, hide_index=True)
            # 下載按鈕
            csv_export = translated_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"📥 下載 {month} 翻譯結果 (CSV)",
                data=csv_export,
                file_name=f"{month}_Translated.csv",
                mime='text/csv'
            )
            # 清理暫存 csv
            os.remove(csv_name)

if __name__ == "__main__":
    main()
