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
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0px 0px; padding: 10px 16px; background-color: #1e293b; }
    .stTabs [aria-selected="true"] { background-color: #38bdf8 !important; color: #0f172a !important; font-weight: bold;}
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

# 終極防禦版：動態雷達尋找網頁表頭，不再依賴固定格式
@st.cache_data(ttl=3600)
def fetch_all_active_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        current_date = get_tw_time()
        success = False
        contracts_data = {}
        
        for _ in range(10):
            if current_date.weekday() < 5:
                date_str = current_date.strftime('%Y/%m/%d')
                payload = {
                    'queryType': '2',
                    'marketCode': '0',
                    'commodity_id': 'TXO',
                    'queryDate': date_str
                }
                res = requests.post(url, headers=headers, data=payload, timeout=5)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, 'html.parser')
                
                rows = soup.find_all('tr')
                
                header_idx = -1
                col_month, col_strike, col_cp, col_oi = -1, -1, -1, -1
                
                # 掃描表頭位置
                for idx, row in enumerate(rows):
                    ths = [th.get_text(strip=True) for th in row.find_all(['th', 'td'])]
                    if '履約價' in ths and '未平倉量' in ths:
                        header_idx = idx
                        for i, text in enumerate(ths):
                            if '到期' in text or '週別' in text: col_month = i
                            elif '履約價' in text: col_strike = i
                            elif '買賣權' in text: col_cp = i
                            elif '未平倉' in text: col_oi = i
                        break
                        
                # 若成功定位，開始掃描數據
                if header_idx != -1 and col_strike != -1 and col_oi != -1:
                    for row in rows[header_idx+1:]:
                        tds = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(tds) <= max(col_month, col_strike, col_cp, col_oi):
                            continue
                            
                        try:
                            month = tds[col_month]
                            strike = int(float(tds[col_strike].replace(',', '')))
                            cp = tds[col_cp]
                            oi_str = tds[col_oi].replace(',', '')
                            oi = int(float(oi_str)) if oi_str.isdigit() else 0
                            
                            # 嚴格篩選：履約價合理、口數存在
                            if strike >= 10000 and oi > 0 and month:
                                if month not in contracts_data:
                                    contracts_data[month] = {'calls': {}, 'puts': {}, 'total_oi': 0}
                                    
                                contracts_data[month]['total_oi'] += oi
                                
                                if '買' in cp or 'Call' in cp:
                                    contracts_data[month]['calls'][strike] = max(contracts_data[month]['calls'].get(strike, 0), oi)
                                elif '賣' in cp or 'Put' in cp:
                                    contracts_data[month]['puts'][strike] = max(contracts_data[month]['puts'].get(strike, 0), oi)
                        except:
                            pass
                            
                    if contracts_data:
                        success = True
                        break
                        
            current_date -= datetime.timedelta(days=1)
            
        if success and contracts_data:
            result = {}
            for contract, data in contracts_data.items():
                calls = sorted(list(data['calls'].items()), key=lambda x: x[0], reverse=True)
                puts = sorted(list(data['puts'].items()), key=lambda x: x[0], reverse=True)
                result[contract] = {
                    'total_oi': data['total_oi'],
                    'calls': calls,
                    'puts': puts
                }
            return result
            
        return {}
    except Exception as e:
        return {}

with st.spinner("正在自動同步期交所最新籌碼數據..."):
    futures_records = fetch_5d_futures_data()
    all_opt_data = fetch_all_active_options_data()

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

st.subheader("🎯 選擇權全戰區 T 字報價單")

if all_opt_data:
    sorted_contracts = sorted(all_opt_data.keys(), key=lambda k: all_opt_data[k]['total_oi'], reverse=True)[:3]
    tabs = st.tabs([f"📅 {c}" for c in sorted_contracts])
    
    for idx, tab in enumerate(tabs):
        with tab:
            contract = sorted_contracts[idx]
            top_calls = all_opt_data[contract]['calls']
            top_puts = all_opt_data[contract]['puts']

            if top_calls or top_puts:
                max_call_oi = max([oi for strike, oi in top_calls]) if top_calls else 0
                max_put_oi = max([oi for strike, oi in top_puts]) if top_puts else 0

                all_strikes = set([s for s, oi in top_calls] + [s for s, oi in top_puts])
                sorted_strikes = sorted(list(all_strikes), reverse=True)

                t_rows = []
                for strike in sorted_strikes:
                    c_oi = next((oi for s, oi in top_calls if s == strike), 0)
                    p_oi = next((oi for s, oi in top_puts if s == strike), 0)

                    c_display = f"⚠️ {c_oi:,}" if c_oi == max_call_oi and c_oi > 0 else (f"{c_oi:,}" if c_oi > 0 else "-")
                    p_display = f"🛡️ {p_oi:,}" if p_oi == max_put_oi and p_oi > 0 else (f"{p_oi:,}" if p_oi > 0 else "-")

                    t_rows.append({
                        "🔴 買權 Call (OI)": c_display,
                        "🎯 履約價": f"{strike:,}",
                        "🟢 賣權 Put (OI)": p_display
                    })

                df_t = pd.DataFrame(t_rows)
                st.dataframe(df_t, hide_index=True, use_container_width=True)
else:
    st.warning("目前無法取得選擇權資料，請稍後重試。")

st.markdown("---")
if st.button("🔄 立即重新整理數據"):
    st.cache_data.clear()
    st.rerun()
