import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import datetime
import csv
from io import StringIO

# 設定網頁標題與手機優化排版
st.set_page_config(page_title="期權籌碼自動化儀表板", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
    h1 { font-size: 1.8rem !important; color: #38bdf8; }
    h2 { font-size: 1.3rem !important; }
    .stButton>button { width: 100%; border-radius: 12px; height: 3rem; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("📊 台指期權籌碼自動化追蹤")

# 策略備忘
st.info("""
    **💡 SIP 策略備忘**
    * 盤勢推演節奏：**情緒超跌 ➔ 理性回補 ➔ 中盤動盪**
    * 核心守則：密切留意賣權 (Put) 的 **LL (下限區間)**，若伴隨最大量 OI 增長且未被實質跌破，往往是「情緒超跌」後的絕佳觀察點；向上挑戰 Call 最大壓力區時需防洗盤。
""")

def get_tw_time():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

@st.cache_data(ttl=3600)
def fetch_5d_futures_data():
    url = "https://www.taifex.com.tw/cht/3/futContractsDate"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    records = []
    current_date = get_tw_time()
    days_checked = 0
    
    while len(records) < 5 and days_checked < 15:
        if current_date.weekday() < 5: 
            date_str = current_date.strftime('%Y/%m/%d')
            date_display = current_date.strftime('%m/%d')
            try:
                payload = {'queryDate': date_str}
                res = requests.post(url, headers=headers, data=payload, timeout=5)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, 'html.parser')
                
                rows = soup.find_all('tr')
                tx_idx = -1
                for i, r in enumerate(rows):
                    texts = [c.get_text(strip=True) for c in r.find_all(['td', 'th'])]
                    if '臺股期貨' in texts:
                        tx_idx = i
                        break
                
                if tx_idx != -1:
                    foreign_row = rows[tx_idx + 2]
                    tds = foreign_row.find_all('td')
                    if '外資' in tds[0].get_text(strip=True):
                        long_pos = int(tds[7].get_text(strip=True).replace(',', ''))
                        short_pos = int(tds[9].get_text(strip=True).replace(',', ''))
                        net_pos = int(tds[11].get_text(strip=True).replace(',', ''))
                        records.append({
                            'Date': date_display, 
                            'Long': long_pos, 
                            'Short': short_pos, 
                            'Net': net_pos
                        })
            except:
                pass
        current_date -= datetime.timedelta(days=1)
        days_checked += 1
        
    return records[::-1]

# 核心修正：使用最穩定的 CSV 下載 API，絕對不會抓錯格子！
@st.cache_data(ttl=3600)
def fetch_top3_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDataDown"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        current_date = get_tw_time()
        success = False
        calls, puts = [], []
        
        for _ in range(10):
            if current_date.weekday() < 5:
                date_str = current_date.strftime('%Y/%m/%d')
                payload = {
                    'down_type': '1',
                    'commodity_id': 'TXO',
                    'queryStartDate': date_str,
                    'queryEndDate': date_str
                }
                res = requests.post(url, headers=headers, data=payload, timeout=5)
                
                try:
                    text_data = res.content.decode('big5')
                except:
                    text_data = res.content.decode('utf-8', errors='ignore')
                    
                if "交易日期" in text_data and "履約價" in text_data:
                    reader = csv.DictReader(StringIO(text_data))
                    for row in reader:
                        try:
                            strike, cp, oi = 0, '', 0
                            for k, v in row.items():
                                if not k or not v: continue
                                k_str = str(k).strip()
                                v_str = str(v).strip()
                                
                                if '履約價' in k_str:
                                    strike = int(float(v_str))
                                elif '買賣權' in k_str:
                                    cp = v_str
                                elif '未平倉' in k_str:  
                                    val = v_str.replace(',', '')
                                    oi = 0 if val == '-' or not val else int(float(val))
                                    
                            if strike >= 10000 and oi > 0:
                                if '買' in cp or 'Call' in cp:
                                    calls.append((strike, oi))
                                elif '賣' in cp or 'Put' in cp:
                                    puts.append((strike, oi))
                        except:
                            pass
                            
                    if calls and puts:
                        success = True
                        break
                        
            current_date -= datetime.timedelta(days=1)
            
        if success and calls and puts:
            call_dict = {}
            put_dict = {}
            for strike, oi in calls:
                call_dict[strike] = max(call_dict.get(strike, 0), oi)
            for strike, oi in puts:
                put_dict[strike] = max(put_dict.get(strike, 0), oi)
            
            unique_calls = list(call_dict.items())
            unique_puts = list(put_dict.items())
            
            top_calls = sorted(sorted(unique_calls, key=lambda x: x[1], reverse=True)[:3], key=lambda x
