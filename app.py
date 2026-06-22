import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import datetime

st.set_page_config(page_title="籌碼戰情室", layout="centered", initial_sidebar_state="collapsed")
st.title("📊 籌碼戰情室")

@st.cache_data(ttl=3600)
def fetch_all_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    payload = {'queryType': '2', 'marketCode': '0', 'commodity_id': 'TXO'}
    try:
        res = requests.post(url, data=payload, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 建立一個字典來存放所有數據
        data_dict = {}
        
        # 遍歷所有行，強制區分 Call 和 Put
        for row in soup.find_all('tr'):
            cells = [c.get_text(strip=True).replace(',', '') for c in row.find_all('td')]
            if len(cells) < 8: continue
            
            # 嘗試解析履約價與 OI
            strike = 0
            for c in cells:
                if c.isdigit() and 10000 < int(c) < 40000:
                    strike = int(c)
                    break
            
            if strike > 0:
                oi = int(cells[-1]) if cells[-1].isdigit() else 0
                if oi > 0:
                    if strike not in data_dict:
                        data_dict[strike] = {'Call': 0, 'Put': 0}
                    
                    # 判斷是 Call 還是 Put
                    text_row = str(cells)
                    if '買權' in text_row or 'Call' in text_row:
                        data_dict[strike]['Call'] = max(data_dict[strike]['Call'], oi)
                    elif '賣權' in text_row or 'Put' in text_row:
                        data_dict[strike]['Put'] = max(data_dict[strike]['Put'], oi)
        
        return pd.DataFrame.from_dict(data_dict, orient='index').sort_index(ascending=False)
    except:
        return pd.DataFrame()

# 顯示表格
df = fetch_all_data()
if not df.empty:
    st.dataframe(df, use_container_width=True)
else:
    st.warning("數據抓取中，請稍後按下方按鈕重試。")

if st.button("🔄 強制重新整理"):
    st.cache_data.clear()
    st.rerun()
