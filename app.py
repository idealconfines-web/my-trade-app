import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import datetime

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

# 頂部策略備忘卡片
st.info("""
    **💡 SIP 策略備忘**
    * 盤勢推演節奏：**情緒超跌 ➔ 理性回補 ➔ 中盤動盪**
    * 核心守則：密切留意賣權 (Put) 的 **LL (下限區間)**，若伴隨最大量 OI 增長且未被實質跌破，往往是「情緒超跌」後的絕佳觀察點；向上挑戰 Call 最大壓力區時需防洗盤。
""")

# 定義抓取期貨近5日資料的函式
@st.cache_data(ttl=3600)
def fetch_5d_futures_data():
    url = "https://www.taifex.com.tw/cht/3/futContractsDate"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    records = []
    current_date = datetime.datetime.now()
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

# 定義抓取選擇權前三大 OI 的函式 (修正版：精準鎖定未平倉量)
@st.cache_data(ttl=3600)
def fetch_top3_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        # 改用 POST 請求並明確指定 TXO，防止期交所擋掉空白查詢
        payload = {
            'queryType': '2',
            'marketCode': '0',
            'commodity_id': 'TXO',
            'queryDate': '',
            'MarketCode': '0',
            'commodity_idt': 'TXO'
        }
        response = requests.post(url, headers=headers, data=payload, timeout=5)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        rows = soup.find_all('tr')
        calls, puts = [], []
        current_strike = 0
        
        for row in rows:
            tds = [td.get_text(strip=True).replace(',', '') for td in row.find_all('td')]
            if len(tds) < 10: 
                continue
            
            for text in tds:
                if text.isdigit() and 10000 <= int(text) <= 40000:
                    current_strike = int(text)
                    break
            
            # 期交所的「未平倉量」固定在表格的最後一格 (tds[-1])
            oi_str = tds[-1]
            if not oi_str.isdigit():
                continue
                
            if '買權' in tds:
                calls.append((current_strike, int(oi_str)))
            elif '賣權' in tds:
                puts.append((current_strike, int(oi_str)))
        
        if calls and puts:
            # 針對相同的履約價可能有多個合約月份，我們先用 dict 整合出各履約價的最大 OI
            call_dict = {}
            put_dict = {}
            for strike, oi in calls:
                call_dict[strike] = max(call_dict.get(strike, 0), oi)
            for strike, oi in puts:
                put_dict[strike] = max(put_dict.get(strike, 0), oi)
            
            # 轉回 list 並排序取前三大
            unique_calls = list(call_dict.items())
            unique_puts = list(put_dict.items())
            
            top_calls = sorted(sorted(unique_calls, key=lambda x: x[1], reverse=True)[:3], key=lambda x: x[0], reverse=True)
            top_puts = sorted(sorted(unique_puts, key=lambda x: x[1], reverse=True)[:3], key=lambda x: x[0], reverse=True)
            
            return top_calls, top_puts
            
        return [], []
    except Exception as e:
        return [], []

with st.spinner("正在抓取期交所近五日籌碼與選擇權數據..."):
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

# --- 區塊二：選擇權支撐壓力階梯圖 ---
st.subheader("🎯 選擇權價格階梯 (前三大 OI)")

if top_calls and top_puts:
    max_call_oi = max(top_calls, key=lambda x: x[1])[1]
    max_put_oi = max(top_puts, key=lambda x: x[1])[1]
    
    html_str = '<div style="background-color: #1e293b; padding: 20px; border-radius: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5);">'
    
    for strike, oi in top_calls:
        is_max = (oi == max_call_oi)
        color = "#fca5a5" if is_max else "#94a3b8"
        weight = "bold" if is_max else "normal"
        label = "⚠️ 最大壓力" if is_max else "上檔壓力"
        html_str += f'''
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; color: {color}; font-weight: {weight};">
            <span style="width: 30%; font-size: 0.9rem;">{label}</span>
            <span style="width: 35%; text-align: center; font-size: 1.3rem;">{strike}</span>
            <span style="width: 35%; text-align: right; font-size: 0.9rem;">{oi:,} 口</span>
        </div>
        '''
        
    html_str += '<div style="text-align: center; color: #475569; margin: 15px 0; font-size: 0.8rem; letter-spacing: 2px;">▼ 結算震盪區間 ▲</div>'
    
    for strike, oi in top_puts:
        is_max = (oi == max_put_oi)
        color = "#86efac" if is_max else "#94a3b8"
        weight = "bold" if is_max else "normal"
        label = "🛡️ LL 防守" if is_max else "下檔支撐"
        html_str += f'''
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; color: {color}; font-weight: {weight};">
            <span style="width: 30%; font-size: 0.9rem;">{label}</span>
            <span style="width: 35%; text-align: center; font-size: 1.3rem;">{strike}</span>
            <span style="width: 35%; text-align: right; font-size: 0.9rem;">{oi:,} 口</span>
        </div>
        '''
        
    html_str += '</div>'
    st.markdown(html_str, unsafe_allow_html=True)
else:
    st.warning("目前無法取得選擇權資料，請稍後重試。")

if st.button("🔄 立即重新整理數據"):
    st.cache_data.clear()
    st.rerun()
