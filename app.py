"""
Options Premium Tracker - Streamlit Dashboard

Tracks options premium in real-time, overlays stock price, and visualizes
the spread (premium as % of stock price). Polls every 30 seconds.
"""

import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from api_client import list_available_strikes, list_available_contracts, fetch_snapshot, get_stock_price


# Page config
st.set_page_config(
    page_title="Options Premium Tracker",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Options Premium Tracker")

# Initialize session state
if 'tracking' not in st.session_state:
    st.session_state.tracking = False
if 'contract' not in st.session_state:
    st.session_state.contract = None
if 'contract_info' not in st.session_state:
    st.session_state.contract_info = {}
if 'data' not in st.session_state:
    st.session_state.data = []
if 'last_fetch' not in st.session_state:
    st.session_state.last_fetch = None
if 'available_contracts' not in st.session_state:
    st.session_state.available_contracts = []
if 'search_params' not in st.session_state:
    st.session_state.search_params = {}
if 'available_strikes' not in st.session_state:
    st.session_state.available_strikes = []
if 'current_stock_price' not in st.session_state:
    st.session_state.current_stock_price = None

# Sidebar inputs
with st.sidebar:
    st.header("📋 Configuration")

    ticker = st.text_input("Ticker Symbol", value="AAPL", help="e.g., AAPL, TSLA, MSTR")
    put_call = st.selectbox("Option Type", options=["call", "put"])

    load_strikes_btn = st.button("🔍 Load Strikes", use_container_width=True)

    # Handle loading strikes
    if load_strikes_btn:
        with st.spinner("Loading strikes..."):
            try:
                stock_price = get_stock_price(ticker.upper())
                strikes = list_available_strikes(ticker.upper(), put_call)
                st.session_state.available_strikes = strikes
                st.session_state.available_contracts = []
                st.session_state.current_stock_price = stock_price
                st.session_state.search_params = {
                    'ticker': ticker.upper(),
                    'type': put_call
                }
                if not strikes:
                    st.warning("No options found for this ticker.")
            except Exception as e:
                st.error(f"Error: {str(e)}")

    # Show current price and strike selection if we have strikes
    if st.session_state.available_strikes:
        st.divider()

        # Display current stock price
        if st.session_state.current_stock_price:
            st.metric(
                f"{st.session_state.search_params['ticker']} Price",
                f"${st.session_state.current_stock_price:.2f}"
            )

        selected_strike = st.selectbox(
            "Strike Price",
            options=st.session_state.available_strikes,
            format_func=lambda x: f"${x:.2f}",
            help="Select a strike price"
        )

        search_exp_btn = st.button("🔍 Load Expirations", use_container_width=True)

        if search_exp_btn:
            with st.spinner("Loading expirations..."):
                try:
                    contracts = list_available_contracts(
                        st.session_state.search_params['ticker'],
                        selected_strike,
                        st.session_state.search_params['type']
                    )
                    st.session_state.available_contracts = contracts
                    st.session_state.search_params['strike'] = selected_strike
                    if not contracts:
                        st.warning("No expirations found for this strike.")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    # Show available expirations if we have them
    if st.session_state.available_contracts:
        st.divider()

        contract_options = {
            f"{c['expiration']} ({c['dte']} DTE)": c
            for c in st.session_state.available_contracts
        }

        selected = st.selectbox(
            "Expiration Date",
            options=list(contract_options.keys()),
            help="Choose an expiration date"
        )

        if selected:
            selected_contract = contract_options[selected]

            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                start_btn = st.button("▶️ Start", use_container_width=True, type="primary")
            with col2:
                stop_btn = st.button("⏹️ Stop", use_container_width=True)

            if start_btn:
                st.session_state.contract = selected_contract['ticker']
                st.session_state.contract_info = {
                    'ticker': st.session_state.search_params['ticker'],
                    'strike': st.session_state.search_params['strike'],
                    'type': st.session_state.search_params['type'],
                    'dte': selected_contract['dte'],
                    'expiration': selected_contract['expiration'],
                    'contract': selected_contract['ticker']
                }
                st.session_state.tracking = True
                st.session_state.data = []
                st.success(f"Tracking: {selected_contract['ticker']}")

            if stop_btn:
                st.session_state.tracking = False

    st.divider()

    if st.button("🗑️ Clear Data", use_container_width=True):
        st.session_state.data = []
        st.session_state.contract = None
        st.session_state.contract_info = {}
        st.session_state.tracking = False
        st.session_state.available_contracts = []
        st.session_state.available_strikes = []
        st.session_state.search_params = {}
        st.session_state.current_stock_price = None
        st.rerun()

# Main display
if st.session_state.contract:
    # Contract info card
    info = st.session_state.contract_info

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Underlying", info['ticker'])
    with col2:
        st.metric("Strike", f"${info['strike']:.2f}")
    with col3:
        st.metric("Type", info['type'].upper())
    with col4:
        st.metric("Expiration", info.get('expiration', 'N/A'))
    with col5:
        st.metric("DTE", info.get('dte', 'N/A'))

    st.divider()

    # Current values
    if st.session_state.data:
        latest = st.session_state.data[-1]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "Option Premium (Mid)",
                f"${latest['premium']:.2f}",
                delta=f"${latest['premium'] - st.session_state.data[-2]['premium']:.2f}" if len(st.session_state.data) > 1 else None
            )
        with col2:
            st.metric(
                "Stock Price",
                f"${latest['stock_price']:.2f}",
                delta=f"${latest['stock_price'] - st.session_state.data[-2]['stock_price']:.2f}" if len(st.session_state.data) > 1 else None
            )
        with col3:
            st.metric(
                "Spread %",
                f"{latest['spread_pct']:.2f}%",
                delta=f"{latest['spread_pct'] - st.session_state.data[-2]['spread_pct']:.2f}%" if len(st.session_state.data) > 1 else None
            )

        # Additional option data
        if latest.get('option_data'):
            od = latest['option_data']
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            with col1:
                st.metric("Bid", f"${od['bid']:.2f}" if od['bid'] else "N/A")
            with col2:
                st.metric("Ask", f"${od['ask']:.2f}" if od['ask'] else "N/A")
            with col3:
                st.metric("Last", f"${od['last']:.2f}" if od['last'] else "N/A")
            with col4:
                st.metric("IV", f"{od['iv']*100:.1f}%" if od['iv'] else "N/A")
            with col5:
                st.metric("Volume", f"{int(od['volume']):,}" if od['volume'] else "N/A")
            with col6:
                st.metric("Open Interest", f"{int(od['open_interest']):,}" if od['open_interest'] else "N/A")

        st.divider()

        # Create chart
        df = pd.DataFrame(st.session_state.data)

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            row_heights=[0.7, 0.3],
            subplot_titles=("Premium & Stock Price", "Spread %")
        )

        # Premium line (left y-axis)
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['premium'],
                name="Option Premium",
                line=dict(color='#00CC96', width=2),
                mode='lines+markers'
            ),
            row=1, col=1
        )

        # Stock price (right y-axis)
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['stock_price'],
                name="Stock Price",
                line=dict(color='#636EFA', width=2),
                mode='lines+markers',
                yaxis='y2'
            ),
            row=1, col=1
        )

        # Spread % (separate subplot)
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['spread_pct'],
                name="Spread %",
                line=dict(color='#EF553B', width=2),
                mode='lines+markers',
                fill='tozeroy',
                fillcolor='rgba(239, 85, 59, 0.2)'
            ),
            row=2, col=1
        )

        # Update layout for dual y-axis
        fig.update_layout(
            height=600,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(title="Premium ($)", side='left', showgrid=True),
            yaxis2=dict(title="Stock Price ($)", side='right', overlaying='y', showgrid=False),
            yaxis3=dict(title="Spread %"),
            xaxis2=dict(title="Time"),
            hovermode='x unified'
        )

        st.plotly_chart(fig, use_container_width=True)

        # Data table
        with st.expander("📊 Raw Data"):
            display_df = df[['timestamp', 'premium', 'stock_price', 'spread_pct']].copy()
            display_df['timestamp'] = display_df['timestamp'].dt.strftime('%H:%M:%S')
            display_df.columns = ['Time', 'Premium ($)', 'Stock ($)', 'Spread (%)']
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    else:
        st.info("Waiting for data... First fetch will happen shortly.")

else:
    st.info("👈 Configure your options parameters in the sidebar and click 'Start' to begin tracking.")

# Status indicator
if st.session_state.tracking:
    status_container = st.empty()
    status_container.success(f"🟢 Tracking active | Last update: {st.session_state.last_fetch.strftime('%H:%M:%S') if st.session_state.last_fetch else 'Pending...'}")

# Auto-refresh logic
if st.session_state.tracking:
    try:
        info = st.session_state.contract_info

        # Fetch new data
        timestamp, premium, stock_price, spread_pct, option_data = fetch_snapshot(
            info['ticker'],
            info['contract'],
            info['expiration'],
            info['strike'],
            info['type']
        )

        st.session_state.data.append({
            'timestamp': timestamp,
            'premium': premium,
            'stock_price': stock_price,
            'spread_pct': spread_pct,
            'option_data': option_data
        })

        st.session_state.last_fetch = timestamp

        # Keep only last 100 data points to prevent memory issues
        if len(st.session_state.data) > 100:
            st.session_state.data = st.session_state.data[-100:]

        # Wait and refresh
        time.sleep(30)
        st.rerun()

    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        st.session_state.tracking = False
