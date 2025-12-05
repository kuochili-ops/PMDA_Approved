
import streamlit as st
import requests
from bs4 import BeautifulSoup

def kegg_drug_search(japanese_name):
    search_url = f"https://www.kegg.jp/entry/dr:{japanese_name}"
    response = requests.get(search_url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        name_tag = soup.find("nobr", string="Name")
        if name_tag:
            english_name = name_tag.find_next("td").text.strip()
            return english_name
    return ""

st.title("KEGG 藥品英文學名查詢工具")
drug_name = st.text_input("請輸入日文成分名（如：ドロスピレノン）")
if drug_name:
    result = kegg_drug_search(drug_name)
    st.write("KEGG 英文學名：", result if result else "查無資料")
