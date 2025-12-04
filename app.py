import streamlit as st
import pandas as pd
import json
import time
import requests
import io
import re

# --- 配置 ---
MODEL_NAME = "gemini-1.5-flash"  # 改成穩定可用的模型
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"
def translate_drug_info(japanese_data_list):
    """使用 Gemini API 翻譯藥品資訊列表，並要求結構化 JSON 輸出。"""
    if not japanese_data_list:
        return []

    system_prompt = (
        "You are an expert pharmaceutical translator. Translate the provided Japanese drug information "
        "into Traditional Chinese and English. You MUST return a single JSON array that matches the provided JSON schema. "
        "Maintain the original Japanese text if the Japanese column contains complex formatting or identifiers. "
        "The translation must be accurate and concise."
    )

    data_to_translate = "\n---\n".join([
        f"Trade Name (JP): {item['trade_name_jp']}\nIngredient (JP): {item['ingredient_jp']}\nEfficacy (JP): {item['efficacy_jp']}"
        for item in japanese_data_list
    ])

    user_query = f"Translate the following Japanese drug entries. Respond ONLY with the JSON array.\n\n{data_to_translate}"

    response_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "trade_name_zh": {"type": "STRING"},
                "trade_name_en": {"type": "STRING"},
                "ingredient_zh": {"type": "STRING"},
                "ingredient_en": {"type": "STRING"},
                "efficacy_zh": {"type": "STRING"},
                "efficacy_en": {"type": "STRING"}
            },
            "required": ["trade_name_zh", "trade_name_en", "ingredient_zh", "ingredient_en", "efficacy_zh", "efficacy_en"]
        }
    }

    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        }
    }

    response = None
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(
                API_URL,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(payload),
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text')
            if json_text:
                return json.loads(json_text)
            st.error("API 回應成功，但未找到預期的 JSON 翻譯結果。")
            return None
        except requests.exceptions.RequestException as e:
            if response is not None and response.status_code == 403:
                st.error("API 呼叫失敗：403 Forbidden。請確認模型授權。")
                return None
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                st.error(f"API 呼叫失敗: {e}")
                return None
        except json.JSONDecodeError:
            st.error("翻譯結果格式錯誤，無法解析 JSON。")
            return None
        except Exception as e:
            st.error(f"翻譯過程中發生意外錯誤: {e}")
            return None
    return None
def process_uploaded_file(uploaded_file):
    """讀取 CSV/XLSX 檔案，清理資料。"""
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

        # 篩選關鍵欄位
        key_cols = ['Category', 'Approval_Date', 'No', 'Trade_Name_JP', 'Approval_Type', 'Ingredient_JP', 'Efficacy_JP']
        df = df[key_cols].dropna(subset=['Trade_Name_JP', 'Ingredient_JP', 'Efficacy_JP'], how='all').reset_index(drop=True)

        return df
    except Exception as e:
        st.error(f"處理檔案 {uploaded_file.name} 時發生錯誤: {e}")
        return None
def translate_and_combine(df):
    """翻譯並合併結果。"""
    data_for_translation = df.apply(
        lambda row: {
            'trade_name_jp': row['Trade_Name_JP'],
            'ingredient_jp': row['Ingredient_JP'],
            'efficacy_jp': row['Efficacy_JP']
        },
        axis=1
    ).tolist()

    st.info(f"正在翻譯 {len(data_for_translation)} 筆藥品資料...")
    translated_results = translate_drug_info(data_for_translation)

    if translated_results is None or len(translated_results) != len(df):
        st.warning("批次翻譯數量不一致，改用逐筆翻譯。")
        translated_results = []
        for item in data_for_translation:
            res = translate_drug_info([item])
            if res:
                translated_results.append(res[0])

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
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器")

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
                    st.dataframe(translated_df, use_container_width=True, hide_index=True)

                    # 提供下載按鈕
                    csv_export = translated_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 下載翻譯結果 ({uploaded_file.name})",
                        data=csv_export,
                        file_name=f"{uploaded_file.name}_Translated.csv",
                        mime='text/csv'
                    )

if __name__ == "__main__":
    main()
