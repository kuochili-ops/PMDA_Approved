import streamlit as st
import requests
from bs4 import BeautifulSoup

def kegg_drug_search(japanese_name):
    # KEGG DRUG 搜尋網址
    search_url = f"https://www.kegg.jp/entry/dr:{japanese_name}"
    response = requests.get(search_url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        # 解析英文學名（通常在「Name」欄位）
        name_tag = soup.find("nobr", string="Name")
        if name_tag:
            english_name = name_tag.find_next("td").text.strip()
            return english_name
    return ""

# 範例查詢
result = kegg_drug_search("ドロスピレノン")
print("KEGG 英文學名：", result)
