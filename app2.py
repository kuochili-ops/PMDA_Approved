
import requests

def get_pubchem_synonyms(japanese_name):
    # PubChem API: 根據成分名稱查詢同義詞
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{japanese_name}/synonyms/JSON"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        synonyms = data.get('InformationList', {}).get('Information', [{}])[0].get('Synonym', [])
        return synonyms
    else:
        print("查詢失敗，請確認成分名稱或網路連線。")
        return []

# 範例查詢
synonyms = get_pubchem_synonyms("アセトアミノフェン")
print(synonyms)
