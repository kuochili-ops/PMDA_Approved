import streamlit as st
import pandas as pd
import json
import time
import requests
import io

# --- 配置 (Configuration) ---
# 在 Canvas 環境中，API Key 會被自動提供。在外部環境，請確保您有設置 GEMINI_API_KEY
# For Canvas environment, leave API_KEY as empty string.
API_KEY = "" 
MODEL_NAME = "gemini-2.5-flash-preview-09-2025"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"


def translate_drug_info(japanese_data_list):
    """
    使用 Gemini API 翻譯藥品資訊列表，並要求結構化的 JSON 輸出。
    """
    if not japanese_data_list:
        return []

    # 限制 API 呼叫的資料量，避免超出上下文視窗
    # For large lists, translating in batches is safer, but for typical lists, one call is efficient.
    # We will process one file (one list) at a time, which is usually safe.

    system_prompt = (
        "You are an expert pharmaceutical translator. Translate the provided Japanese drug information "
        "into Traditional Chinese and English. You MUST return a single JSON array that matches the provided JSON schema. "
        "Maintain the original Japanese text if the Japanese column contains complex formatting or identifiers. "
        "The translation must be accurate and concise."
    )

    # 將要翻譯的資料格式化為單一字串
    data_to_translate = "\n---\n".join([
        f"Trade Name (JP): {item['trade_name_jp']}\nIngredient (JP): {item['ingredient_jp']}\nEfficacy (JP): {item['efficacy_jp']}"
        for item in japanese_data_list
    ])

    user_query = f"Translate the following Japanese drug entries. Respond ONLY with the JSON array.\n\n{data_to_translate}"

    # 定義結構化 JSON 輸出格式
    response_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "trade_name_zh": {"type": "STRING", "description": "Traditional Chinese translation of the trade name and company."},
                "trade_name_en": {"type": "STRING", "description": "English translation of the trade name and company."},
                "ingredient_zh": {"type": "STRING", "description": "Traditional Chinese translation of the ingredient name."},
                "ingredient_en": {"type": "STRING", "description": "English translation of the ingredient name."},
                "efficacy_zh": {"type": "STRING", "description": "Traditional Chinese translation of the efficacy and effects."},
                "efficacy_en": {"type": "STRING", "description": "English translation of the efficacy and effects."}
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

    # 實作指數退避 (Exponential Backoff) 處理 API 呼叫失敗
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(
                API_URL,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(payload),
                timeout=60 # 給予足夠的 API 執行時間
            )
            response.raise_for_status() # 檢查 HTTP 狀態碼
            
            result = response.json()
            
            # 從結果中提取 JSON 字串
            json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text')
            
            if json_text:
                return json.loads(json_text)
            
            st.error("API 回應成功，但未找到預期的 JSON 翻譯結果。")
            return None

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt # 1s, 2s, 4s, 8s...
                time.sleep(wait_time)
            else:
                st.error(f"經過 {max_retries} 次嘗試後，API 呼叫仍失敗。錯誤: {e}")
                return None
        except json.JSONDecodeError:
            st.error("翻譯結果格式錯誤，無法解析 JSON。")
            return None
        except Exception as e:
            st.error(f"翻譯過程中發生意外錯誤: {e}")
            return None
            
    return None


def process_uploaded_file(uploaded_file):
    """
    讀取 CSV 或 XLSX 檔案，清理資料，並識別月份名稱。
    """
    try:
        # 1. 識別月份名稱
        filename = uploaded_file.name
        # 嘗試從檔名中提取月份，例如 '承認品目5月分.csv' -> '5月分'
        month_name_match = filename.split('承認品目')[-1].replace('.csv', '').replace('.xlsx - ', '').replace('.xlsx', '')
        month_name = month_name_match.strip() if month_name_match.strip() else "未知月份"
        
        # 2. 讀取檔案
        file_type = uploaded_file.type
        filename_lower = uploaded_file.name.lower()
        
        # 根據 PMDA 檔案結構，跳過前 2 行標頭 (skiprows=2)
        if 'excel' in file_type or filename_lower.endswith(('.xlsx', '.xls')):
            # 讀取 Excel 檔案
            # 將上傳的檔案物件直接傳遞給 read_excel
            df = pd.read_excel(uploaded_file, sheet_name=0, skiprows=2)
        elif 'csv' in file_type or filename_lower.endswith('.csv'):
            # 讀取 CSV 檔案
            # 必須使用 io.StringIO 處理 Streamlit 的上傳物件的內容
            csv_data = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            df = pd.read_csv(csv_data, skiprows=2)
        else:
            st.error("不支援的檔案格式。請上傳 CSV 或 XLSX 檔案。")
            return None, None


        # 3. 清理與重命名欄位
        # 關鍵修正: 使用正則表達式去除所有空格 (半形\s、全形　) 和換行符號\n，以確保正確匹配日文欄位名稱。
        df.columns = df.columns.str.replace(r'[\s\n　]', '', regex=True)
        
        japanese_cols = {
            # 修正後的鍵名 (必須與清理後的 DataFrame 欄位名稱完全匹配)
            '販賣名(會社名、法人番號)': 'Trade_Name_JP',
            '成分名(下線:新有効成分)': 'Ingredient_JP',
            '効能・効果等': 'Efficacy_JP',
            '承認日': 'Approval_Date',
            '分野': 'Category',
            'No.': 'No',
            '承認': 'Approval_Type'
        }
        
        # 檢查欄位是否存在後才進行重命名
        cols_to_rename = {k: v for k, v in japanese_cols.items() if k in df.columns}
        if len(cols_to_rename) < 7: # 至少要有三個主要欄位
             st.error("錯誤: 檔案標頭結構與預期的 PMDA 列表不符。請確認檔案內容是否正確。")
             return None, None

        df = df.rename(columns=cols_to_rename)
        
        # 4. 篩選關鍵欄位並清理空行
        key_cols = ['Category', 'Approval_Date', 'No', 'Trade_Name_JP', 'Approval_Type', 'Ingredient_JP', 'Efficacy_JP']
        # 檢查關鍵列是否全部存在
        missing_cols = [col for col in key_cols if col not in df.columns]
        if missing_cols:
             # 如果 missing_cols 不為空，表示重命名後仍有欄位缺失，這不應該發生在成功的重命名後，但作為最終防護。
             st.error(f"錯誤: 處理後的 DataFrame 缺少關鍵欄位: {', '.join(missing_cols)}。")
             return None, None
        
        df = df[key_cols].dropna(subset=['Trade_Name_JP', 'Ingredient_JP', 'Efficacy_JP'], how='all').reset_index(drop=True)
        
        return month_name, df

    except Exception as e:
        # 針對讀取 Excel/CSV 檔案本身的錯誤進行報告
        st.error(f"處理檔案 **{uploaded_file.name}** 時發生錯誤。請確認檔案是正確的 PMDA 列表格式 (CSV 或 XLSX)。錯誤訊息: {e}")
        return None, None
    
    
def translate_and_combine(df):
    """呼叫翻譯函式並將結果合併回 DataFrame。"""
    
    # 準備翻譯資料
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
    
    if translated_results is None:
        return None
    
    # 檢查結果數量是否匹配
    if len(translated_results) != len(df):
        st.warning(f"翻譯結果數量 ({len(translated_results)}) 與原始資料數量 ({len(df)}) 不符。請重試或檢查原始資料。")
        return None
        
    # 合併資料
    df_translated = pd.DataFrame(translated_results)
    final_df = pd.concat([df.reset_index(drop=True), df_translated.reset_index(drop=True)], axis=1)

    # 重新排序和命名欄位以供顯示
    final_cols = [
        'Category', 'Approval_Date', 'No', 
        'Trade_Name_JP', 'trade_name_zh', 'trade_name_en',
        'Ingredient_JP', 'ingredient_zh', 'ingredient_en',
        'Approval_Type',
        'Efficacy_JP', 'efficacy_zh', 'efficacy_en'
    ]
    
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
    
    final_df = final_df[final_cols].rename(columns=display_names)
    
    return final_df

# --- Streamlit 應用程式主體 ---

def main():
    st.set_page_config(layout="wide", page_title="PMDA 日本新藥翻譯列表生成器")
    
    st.title("🇯🇵 PMDA 日本新藥翻譯列表生成器")
    st.markdown("請上傳從 [PMDA 網站](https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0039.html) 下載的新藥承認品目列表檔案。")
    st.markdown("程式將自動讀取、清理，並使用 **Gemini API** 將藥品資訊翻譯為**中文 (繁體)** 及 **英文**。")

    # 初始化 Session State 來儲存已處理的資料
    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = {}

    # 1. 檔案上傳 (更新以支援 XLSX)
    uploaded_files = st.file_uploader(
        "選擇多個月份的新藥列表檔案 (支援 CSV 或 XLSX 格式)",
        type=['csv', 'xlsx', 'xls'],
        accept_multiple_files=True
    )
    
    if uploaded_files:
        
        # 檢查是否有新檔案需要處理
        files_to_process = [
            f for f in uploaded_files 
            if f.name not in st.session_state.processed_data 
            or st.session_state.processed_data[f.name].get('needs_reprocess', False)
        ]
        
        if files_to_process:
            
            # 使用進度條顯示處理狀態
            processing_bar = st.progress(0, text="準備開始處理檔案...")
            
            for i, uploaded_file in enumerate(files_to_process):
                processing_bar.progress((i) / len(files_to_process), text=f"處理並翻譯中: **{uploaded_file.name}**")
                
                # 清理檔案名稱以供顯示和儲存
                month_name, df = process_uploaded_file(uploaded_file)
                
                if df is not None:
                    # 翻譯資料
                    translated_df = translate_and_combine(df)
                    
                    if translated_df is not None:
                        # 儲存成功的結果
                        st.session_state.processed_data[uploaded_file.name] = {
                            'month_name': month_name,
                            'df': translated_df,
                            'error': False,
                            'needs_reprocess': False
                        }
                    else:
                        # 儲存翻譯失敗的標記
                        st.session_state.processed_data[uploaded_file.name] = {
                            'month_name': month_name,
                            'df': None,
                            'error': True,
                            'needs_reprocess': False
                        }
                else:
                    # 儲存處理失敗的標記
                    st.session_state.processed_data[uploaded_file.name] = {
                        'month_name': "未知月份",
                        'df': None,
                        'error': True,
                        'needs_reprocess': False
                    }

            processing_bar.progress(1.0, text="所有檔案處理完畢！")
            time.sleep(1)
            processing_bar.empty()
            st.success("所有新檔案處理完畢！")


        # 2. 結果顯示 (使用 Tab)
        
        # 過濾出成功處理的檔案
        successful_files = {k: v for k, v in st.session_state.processed_data.items() if v['df'] is not None}
        
        if successful_files:
            # 建立分頁名稱列表
            tab_names = [data['month_name'] for data in successful_files.values()]
            
            # 建立分頁
            tabs = st.tabs(tab_names)
            
            # 顯示每個分頁的內容
            for i, (filename, data) in enumerate(successful_files.items()):
                month_name = data['month_name']
                df = data['df']
                
                with tabs[i]:
                    st.header(f"新藥承認品目列表：{month_name}")
                    st.subheader("已翻譯結果 (中文/英文)")
                    
                    # 顯示可互動的表格
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    # 3. 下載按鈕
                    csv_export = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 下載 {month_name} 翻譯列表 (CSV)",
                        data=csv_export,
                        file_name=f"PMDA_Approval_List_{month_name}_Translated.csv",
                        mime='text/csv'
                    )
        
        # 4. 處理失敗檔案的提示
        failed_files = {k: v for k, v in st.session_state.processed_data.items() if v.get('error') and v['df'] is None}
        if failed_files:
            st.error("以下檔案處理或翻譯失敗：")
            for filename in failed_files.keys():
                st.write(f"- {filename}")
            st.markdown("請確認檔案為標準 PMDA 列表格式，且內容符合預期結構。")


if __name__ == "__main__":
    main()
