"""
Yahoo Finance API wrapper functions for options premium tracking.
Uses yfinance library (free, no API key required).
"""

from datetime import datetime, date, time
import yfinance as yf
import pytz


def list_available_strikes(ticker: str, put_call: str) -> list[float]:
    """
    List all available strike prices for a ticker and option type.

    Returns:
        Sorted list of available strike prices
    """
    stock = yf.Ticker(ticker)
    expirations = stock.options

    if not expirations:
        return []

    # Collect strikes from all expirations
    all_strikes = set()
    for exp_str in expirations[:5]:  # Check first 5 expirations for speed
        try:
            chain = stock.option_chain(exp_str)
            options_df = chain.calls if put_call == 'call' else chain.puts
            all_strikes.update(options_df['strike'].tolist())
        except Exception:
            continue

    return sorted(all_strikes)


def list_available_contracts(ticker: str, strike: float, put_call: str) -> list[dict]:
    """
    List all available contracts for given ticker, strike, and type.

    Returns:
        List of dicts with 'ticker', 'expiration', 'dte' for each contract
    """
    stock = yf.Ticker(ticker)
    expirations = stock.options  # tuple of expiration date strings

    result = []
    today = date.today()

    for exp_str in expirations:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days

        # Get the option chain for this expiration to check if strike exists
        try:
            chain = stock.option_chain(exp_str)
            options_df = chain.calls if put_call == 'call' else chain.puts

            # Check if the strike exists in this expiration
            if strike in options_df['strike'].values:
                row = options_df[options_df['strike'] == strike].iloc[0]
                result.append({
                    'ticker': row['contractSymbol'],
                    'expiration': exp_str,
                    'dte': dte
                })
        except Exception:
            continue

    return result


def get_option_data(ticker: str, contract: str, expiration: str, strike: float, put_call: str) -> dict:
    """
    Get current option data including bid, ask, and mid price.

    Returns:
        Dict with bid, ask, mid price and other data
    """
    stock = yf.Ticker(ticker)

    chain = stock.option_chain(expiration)
    options_df = chain.calls if put_call == 'call' else chain.puts

    row = options_df[options_df['strike'] == strike].iloc[0]

    bid = row.get('bid', 0) or 0
    ask = row.get('ask', 0) or 0
    mid = (bid + ask) / 2 if bid and ask else row.get('lastPrice', 0)

    return {
        'bid': bid,
        'ask': ask,
        'mid': mid,
        'last': row.get('lastPrice'),
        'volume': row.get('volume'),
        'open_interest': row.get('openInterest'),
        'iv': row.get('impliedVolatility'),
    }


def get_stock_price(ticker: str) -> float:
    """
    Get the current stock price.

    Returns:
        Current stock price
    """
    stock = yf.Ticker(ticker)
    # Use fast_info for quick price lookup
    return stock.fast_info['lastPrice']


def fetch_snapshot(ticker: str, contract: str, expiration: str, strike: float, put_call: str) -> tuple:
    """
    Fetch a complete snapshot of option and stock data.

    Returns:
        Tuple of (timestamp, premium, stock_price, spread_pct, option_data)
    """
    timestamp = datetime.now()

    option_data = get_option_data(ticker, contract, expiration, strike, put_call)
    premium = option_data['mid']

    stock_price = get_stock_price(ticker)

    spread_pct = (premium / stock_price) * 100 if stock_price > 0 else 0

    return timestamp, premium, stock_price, spread_pct, option_data


def is_market_open() -> dict:
    """
    Check if US stock market is currently open.
    
    Returns:
        Dict with 'is_open', 'current_time', 'market_open', 'market_close', 'status'
    """
    # US Eastern Time
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    
    # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
    market_open_time = time(9, 30)
    market_close_time = time(16, 0)
    
    # Check if it's a weekday
    is_weekday = now_et.weekday() < 5  # 0=Monday, 4=Friday
    
    # Check if within market hours
    current_time = now_et.time()
    is_open = is_weekday and market_open_time <= current_time < market_close_time
    
    # Determine status
    if not is_weekday:
        status = "closed_weekend"
    elif current_time < market_open_time:
        status = "pre_market"
    elif current_time >= market_close_time:
        status = "after_market"
    else:
        status = "open"
    
    return {
        "is_open": is_open,
        "current_time": now_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "market_open": "09:30 ET",
        "market_close": "16:00 ET",
        "status": status,
        "day_of_week": now_et.strftime("%A")
    }

