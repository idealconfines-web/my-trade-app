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

# 核心修正：讀取 CSV 後，自動找出「主力合約」並抓取前 5 大
@st.cache_data(ttl=3600)
def fetch_top5_options_data():
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
                    reader = csv.DictReader(StringIO(text_data))
                    for row in reader:
                        try:
                            strike = int(float(row.get('履約價', 0)))
                            cp = row.get('買賣權', '').strip()
                            oi_str = row.get('未平倉量', '0').replace(',', '').strip()
                            oi = int(float(oi_str)) if oi_str and oi_str != '-' else 0
                            contract_month = row.get('到期月份(週別)', '').strip()
                            
                            # 過濾有效口數與合約
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
            # 自動鎖定總未平倉量最大的「主力合約」
            active_contract = max(contracts_data.keys(), key=lambda k: contracts_data[k]['total_oi'])
            
            calls = list(contracts_data[active_contract]['calls'].items())
            puts = list(contracts_data[active_contract]['puts'].items())
            
            # 取出前 5 大 OI (排序邏輯：數值由大到小排序，取前 5 筆)
            top_calls = sorted(calls, key=lambda x: x[1], reverse=True)[:5]
            top_puts = sorted(puts, key=lambda x: x[1], reverse=True)[:5]
            
            # 為了表格好閱讀，最後依照「履約價」由高到低排好
            top_calls = sorted(top_calls, key=lambda x: x[0], reverse=True)
            top_puts = sorted(top_puts, key=lambda x: x[0], reverse=True)
            
            return active_contract, top_calls, top_puts
            
        return "", [], []
    except Exception as e:
        return "", [], []

with st.spinner("正在自動同步期交所最新籌碼數據..."):
    futures_records = fetch_5d_futures_data()
    opt_result = fetch_top5_options_data()
    if len(opt_result) == 3:
        active_contract, top_calls, top_puts = opt_result
    else:
        active_contract, top_calls, top_puts = "", [], []

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

# --- 區塊二：選擇權支撐壓力表 ---
st.subheader(f"🎯 選擇權主力合約支撐壓力 ({active_contract} 前五大 OI)")

if top_calls and top_puts:
    # 找出最大值用來標記
    max_call_oi = max([oi for strike, oi in top_calls])
    max_put_oi = max([oi for strike, oi in top_puts])

    call_rows = []
    for strike, oi in top_calls:
        tag = "⚠️ 最大壓力" if oi == max_call_oi else "上檔壓力"
        call_rows.append({"位置": tag, "履約價": f"{strike:,}", "未平倉口數": f"{oi:,}"})
        
    put_rows = []
    for strike, oi in top_puts:
        tag = "🛡️ LL 防守" if oi == max_put_oi else "下檔支撐"
        put_rows.append({"位置": tag, "履約價": f"{strike:,}", "未平倉口數": f"{oi:,}"})

    df_c = pd.DataFrame(call_rows)
    df_p = pd.DataFrame(put_rows)

    col_left, col_right = st.columns(2)
    with col_left:
        st.caption("🔴 買權 Call")
        st.dataframe(df_c, hide_index=True, use_container_width=True)
        
    with col_right:
        st.caption("🟢 賣權 Put")
        st.dataframe(df_p, hide_index=True, use_container_width=True)

else:
    st.warning("目前無法取得選擇權資料，請稍後重試。")

st.markdown("---")
if st.button("🔄 立即重新整理數據"):
    st.cache_data.clear()
    st.rerun()
