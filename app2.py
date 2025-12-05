
import pandas as pd
import requests
import time

# 1. PubChem 查詢同義詞
def get_pubchem_synonyms(ingredient_name):
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient_name}/synonyms/JSON"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            synonyms = data.get('InformationList', {}).get('Information', [{}])[0].get('Synonym', [])
            return ', '.join(synonyms)
        else:
            return ""
    except Exception as e:
        print(f"查詢 {ingredient_name} 發生錯誤：{e}")
        return ""

# 2. PubChem 查詢 IUPAC 學名
def get_pubchem_iupac(ingredient_name):
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient_name}/property/IUPACName/JSON"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            iupac_name = data.get('PropertyTable', {}).get('Properties', [{}])[0].get('IUPACName', '')
            return iupac_name
        else:
            return ""
    except Exception as e:
        print(f"查詢 {ingredient_name} 發生錯誤：{e}")
        return ""

# 3. 讀取 Excel/CSV 檔案
def read_drug_file(file_path):
    if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
        df = pd.read_excel(file_path)
    elif file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
    else:
        raise ValueError("只支援 Excel 或 CSV 檔案")
    return df

# 4. 主流程：批次查詢並加入新欄位
def process_drug_file(file_path, ingredient_col='Ingredient_JP'):
    df = read_drug_file(file_path)
    # 新增查詢結果欄位
    df['PubChem_Synonyms'] = ""
    df['PubChem_IUPAC'] = ""
    for idx, row in df.iterrows():
        name = str(row[ingredient_col])
        if pd.isna(name) or name.strip() == "":
            continue
        print(f"查詢：{name}")
        synonyms = get_pubchem_synonyms(name)
        iupac = get_pubchem_iupac(name)
        df.at[idx, 'PubChem_Synonyms'] = synonyms
        df.at[idx, 'PubChem_IUPAC'] = iupac
        time.sleep(0.5)  # 避免 API 過度頻繁
    return df

# 5. 儲存結果
def save_result(df, output_path):
    df.to_excel(output_path, index=False)
    print(f"已儲存查詢結果到 {output_path}")

# ======= 使用範例 =======
if __name__ == "__main__":
    input_file = "drug_list.xlsx"  # 你的藥品清單檔案
    output_file = "drug_list_with_pubchem.xlsx"
    result_df = process_drug_file(input_file, ingredient_col='Ingredient_JP')
    save_result(result_df, output_file)
