import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import datetime

st.set_page_config(page_title="籌碼戰情室", layout="centered", initial_sidebar_state="collapsed")

# 這裡移除複雜CSS，保留最乾淨的效能
st.title("📊 籌碼戰情室")

def get_tw_time():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

@st.cache_data(ttl=3600)
def fetch_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    payload = {'queryType': '2', 'marketCode': '0', 'commodity_id': 'TXO'}
    try:
        res = requests.post(url, data=payload, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 尋找所有資料行
        data_rows = []
        for row in soup.find_all('tr'):
            cells = [c.get_text(strip=True).replace(',', '') for c in row.find_all('td')]
            if len(cells) < 10: continue
            
            # 偵測買權(Call)或賣權(Put)列
            # 策略：抓出該列所有數字，履約價必為其中之一，OI必為最後一格
            strike = 0
            for c in cells:
                if c.isdigit() and 10000 < int(c) < 40000:
                    strike = int(c)
                    break
            
            if strike > 0:
                oi = int(cells[-1]) if cells[-1].isdigit() else 0
                if oi > 0:
                    data_rows.append({'履約價': strike, '買賣權': 'Call' if '買權' in str(cells) else 'Put', 'OI': oi})
        
        return pd.DataFrame(data_rows)
    except:
        return pd.DataFrame()

# 顯示資料
df = fetch_options_data()
if not df.empty:
    # 轉為 T 字表
    calls = df[df['買賣權'] == 'Call'].groupby('履約價')['OI'].max()
    puts = df[df['買賣權'] == 'Put'].groupby('履約價')['OI'].max()
    t_df = pd.concat([calls, puts], axis=1, keys=['Call_OI', 'Put_OI']).fillna(0).sort_index(ascending=False)
    
    st.dataframe(t_df, use_container_width=True)
else:
    st.warning("暫無資料，請稍後重試。")

if st.button("🔄 重刷數據"):
    st.cache_data.clear()
    st.rerun()
