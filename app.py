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

@st.cache_data(ttl=3600)
def fetch_top3_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        current_date = get_tw_time()
        success = False
        calls, puts = [], []
        
        for _ in range(10):
            if current_date.weekday() < 5:
                date_str = current_date.strftime('%Y/%m/%d')
                payload = {
                    'queryType': '2',
                    'marketCode': '0',
                    'commodity_id': 'TXO',
                    'queryDate': date_str,
                    'MarketCode': '0',
                    'commodity_idt': 'TXO'
                }
                res = requests.post(url, headers=headers, data=payload, timeout=5)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, 'html.parser')
                
                rows = soup.find_all('tr')
                for row in rows:
                    tds = [td.get_text(strip=True).replace(',', '') for td in row.find_all('td')]
                    if not tds: continue
                    
                    cp_idx = -1
                    for i, text in enumerate(tds):
                        if '買權' in text or '賣權' in text or 'Call' in text or 'Put' in text:
                            cp_idx = i
                            break
                            
                    if cp_idx >= 1 and len(tds) > cp_idx + 8:
                        strike_text = tds[cp_idx - 1]
                        oi_text = tds[cp_idx + 8]
                        
                        if strike_text.isdigit():
                            strike = int(strike_text)
                            oi = 0 if oi_text == '-' or not oi_text or not oi_text.isdigit() else int(oi_text)
                            
                            if strike >= 10000 and oi > 0:
                                if '買' in tds[cp_idx] or 'Call' in tds[cp_idx]:
                                    calls.append((strike, oi))
                                else:
                                    puts.append((strike, oi))
                
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
            
            # 排序：Call 由大到小，Put 由大到小
            top_calls = sorted(unique_calls, key=lambda x: x[1], reverse=True)[:3]
            top_puts = sorted(unique_puts, key=lambda x: x[1], reverse=True)[:3]
            
            return top_calls, top_puts
            
        return [], []
    except Exception as e:
        return [], []

with st.spinner("正在自動同步期交所最新籌碼數據..."):
    futures_records = fetch_5d_futures_data()
    top_calls, top_puts = fetch_top3_options_data()

# --- 區塊一：期貨近五日動向 ---
st.subheader("📈 外資期貨近五日動向")
if futures_records:
    df = pd.DataFrame(futures_records)
    latest = df.iloc[-1]
    
    col1, col2, col3 = st.columns(3)
    col1.metric(f"最新多單 ({latest['Date']})", f"{latest['Long']:,}")
    col2.metric(f"最新空單 ({latest['Date']})", f"{latest['Short']:,}")
    col3.metric("最新淨未平倉", f"{latest['Net']:,}", delta=int(latest['Net']))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['Date'],
        y=df['Net'],
        marker_color=['#ef4444' if val >= 0 else '#22c55e' for val in df['Net']],
        text=[f"{val:,}" for val in df['Net']],
        textposition='auto'
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#94a3b8'),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor='#334155')
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.warning("目前無法取得期貨資料，請稍後重試。")

# --- 區塊二：選擇權支撐壓力表 (純原生元件，絕不報錯) ---
st.subheader("🎯 選擇權大部位留倉觀測 (前三高 OI)")

if top_calls and top_puts:
    # 建立純數據的表格
    call_rows = []
    for i, (strike, oi) in enumerate(top_calls):
        tag = "⚠️ 最大壓力" if i == 0 else f"壓力 {i+1}"
        call_rows.append({"位置": tag, "履約價": strike, "未平倉量(口)": oi})
        
    put_rows = []
    for i, (strike, oi) in enumerate(top_puts):
        tag = "🛡️ LL 防守" if i == 0 else f"支撐 {i+1}"
        put_rows.append({"位置": tag, "履約價": strike, "未平倉量(口)": oi})

    # 轉成標準表格格式
    df_c = pd.DataFrame(call_rows)
    df_p = pd.DataFrame(put_rows)

    # 用 Streamlit 原生左右分欄展示
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.caption("🔴 買權 Call (上檔壓力)")
        st.dataframe(df_c, hide_index=True, use_container_width=True)
        
    with col_right:
        st.caption("🟢 賣權 Put (下檔支撐)")
        st.dataframe(df_p, hide_index=True, use_container_width=True)
else:
    st.warning("目前無法取得選擇權資料，請稍後重試。")

st.markdown("---")
if st.button("🔄 立即重新整理數據"):
    st.cache_data.clear()
    st.rerun()
