
import requests
from bs4 import BeautifulSoup

def kegg_drug_search(japanese_name):
    # 用搜尋頁面查詢
    search_url = f"https://www.kegg.jp/kegg-bin/search?q={japanese_name}&display=drug&from=drug&lang=ja"
    response = requests.get(search_url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        # 找到搜尋結果表格
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:  # 跳過表頭
                cols = row.find_all("td")
                if len(cols) >= 2:
                    entry = cols[0].text.strip()
                    name = cols[1].text.strip()
                    # 取英文學名（通常在括號內）
                    if "(" in name:
                        english_name = name.split("(")[1].split(")")[0]
                        return entry, english_name
                    else:
                        return entry, name
    return None, None

# 範例查詢
entry, english_name = kegg_drug_search("ベネトクラクス")
print("KEGG Entry:", entry)
