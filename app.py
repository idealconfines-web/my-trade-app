import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import datetime
import csv
from io import StringIO

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

# 最堅固的解析法：直接鎖定陣列位置，無視多餘空白
@st.cache_data(ttl=3600)
def fetch_all_active_options_data():
    url = "https://www.taifex.com.tw/cht/3/optDataDown"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        current_date = get_tw_time()
        success = False
        contracts_data = {}
        
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
                    lines = text_data.splitlines()
                    reader = csv.reader(lines)
                    header = next(reader, [])
                    
                    # 動態尋找欄位確切的索引值
                    idx_strike, idx_cp, idx_oi, idx_month = -1, -1, -1, -1
                    for i, col in enumerate(header):
                        if '履約價' in col: idx_strike = i
                        elif '買賣權' in col: idx_cp = i
                        elif '未平倉' in col: idx_oi = i
                        elif '到期' in col or '週別' in col: idx_month = i
                        
                    if idx_strike != -1 and idx_oi != -1:
                        for row in reader:
                            if len(row) <= max(idx_strike, idx_cp, idx_oi, idx_month):
                                continue
                                
                            try:
                                strike = int(float(row[idx_strike].strip()))
                                cp = row[idx_cp].strip()
                                oi_str = row[idx_oi].replace(',', '').strip()
                                oi = int(float(oi_str)) if oi_str and oi_str != '-' else 0
                                contract_month = row[idx_month].strip()
                                
                                # 🔥 只有口數大於 0 才收錄
                                if strike >= 10000 and oi > 0 and contract_month:
                                    if contract_month not in contracts_data:
                                        contracts_data[contract_month] = {'calls': {}, 'puts': {}, 'total_oi': 0}
                                        
                                    contracts_data[contract_month]['total_oi'] += oi
                                    
                                    if '買' in cp or 'Call' in cp:
                                        contracts_data[contract_month]['calls'][strike] = max(contracts_data[contract_month]['calls'].get(strike, 0), oi)
                                    elif '賣' in cp or 'Put' in cp:
                                        contracts_data[contract_month]['puts'][strike] = max(contracts_data[contract_month]['puts'].get(strike, 0), oi)
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
