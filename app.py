def get_kegg_priority_translation(jp_name, log_container, is_ingredient=False):
    """
    優化後的 KEGG 優先查詢：支援直接跳轉頁面與清單頁面
    """
    if not jp_name or pd.isna(jp_name): return None
    
    clean_name = refine_drug_name_for_kegg(jp_name)
    if len(clean_name) < 2: return None
    
    # 使用 Medicus 搜尋
    search_url = f"https://www.kegg.jp/medicus-bin/search_drug?search_keyword={clean_name}"
    
    try:
        log_container.write(f"🧬 KEGG 檢索: `{clean_name}`")
        resp = requests.get(search_url, timeout=10)
        
        if resp.ok:
            # 情況 A：在搜尋清單頁，尋找 japic_code
            japic_match = re.search(r'japic_code=(\d+)', resp.text)
            
            # 情況 B：搜尋結果只有一筆，直接跳轉到了詳細頁 (檢查 URL 或內容)
            if not japic_match:
                # 嘗試從目前網址提取代碼
                japic_match = re.search(r'japiccode=(\d+)', resp.url)
            
            if japic_match:
                japic_code = japic_match.group(1)
                drug_url = f"https://www.kegg.jp/medicus-bin/japicmed?japiccode={japic_code}"
                # 如果已經在詳細頁就不用再 request 一次
                detail_html = resp.text if "japicmed" in resp.url else requests.get(drug_url, timeout=10).text
                
                # 抓取英文名稱
                trade_en = re.search(r'欧文商標名.*?:\s*(.*?)(?=<)', detail_html, re.DOTALL)
                generic_en = re.search(r'英文一般名.*?:\s*(.*?)(?=<)', detail_html, re.DOTALL)
                
                t_val = trade_en.group(1).strip() if trade_en else None
                g_val = generic_en.group(1).strip() if generic_en else None
                
                # 回傳邏輯：成分名(is_ingredient=True) 務必拿 Generic Name
                if is_ingredient:
                    result = g_val if g_val else t_val
                else:
                    result = t_val if t_val else g_val
                
                if result:
                    log_container.write(f"✅ KEGG 命中: `{result}`")
                    return result
                    
    except Exception as e:
        log_container.write(f"⚠️ KEGG 異常: {e}")
    
    return None
