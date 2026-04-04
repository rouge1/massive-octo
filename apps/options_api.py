"""
Options API wrapper for yfinance.

Provides functions to fetch option contract data including:
- Available strike prices
- Available contracts/expirations
- Current stock prices
- Real-time option snapshots (bid, ask, volume, IV, etc.)
- Market hours status

Based on backend/api_client.py but adapted for desktop app use.
"""

import logging
from datetime import datetime, date, time, timedelta
from typing import Optional

import yfinance as yf
import pytz

from apps import schwab_client

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Public API — Schwab-first with yfinance fallback
# ---------------------------------------------------------------------------

def _schwab_with_fallback(schwab_fn, yf_fn, *args):
    """Try Schwab first; on failure, disable client if token error and fall back to yfinance."""
    if schwab_client.is_available():
        try:
            return schwab_fn(*args)
        except Exception as e:
            was_available = schwab_client.is_available()
            schwab_client._handle_token_error(e)
            if was_available and not schwab_client.is_available():
                logger.warning("Schwab token expired — all future requests will use yfinance until re-authorized")
            else:
                logger.warning(f"Schwab call failed, falling back to yfinance: {e}")
    return yf_fn(*args)


def list_available_strikes(ticker: str, put_call: str) -> list[float]:
    return _schwab_with_fallback(
        schwab_client.list_available_strikes, _yf_list_available_strikes,
        ticker, put_call)


def list_available_contracts(ticker: str, strike: float, put_call: str) -> list[dict]:
    return _schwab_with_fallback(
        schwab_client.list_available_contracts, _yf_list_available_contracts,
        ticker, strike, put_call)


def get_stock_price(ticker: str) -> Optional[float]:
    return _schwab_with_fallback(
        schwab_client.get_stock_price, _yf_get_stock_price,
        ticker)


def get_option_data(ticker: str, expiration: str, strike: float, put_call: str) -> Optional[dict]:
    return _schwab_with_fallback(
        schwab_client.get_option_data, _yf_get_option_data,
        ticker, expiration, strike, put_call)


def fetch_snapshot(ticker: str, expiration: str, strike: float, put_call: str) -> Optional[dict]:
    return _schwab_with_fallback(
        schwab_client.fetch_snapshot, _yf_fetch_snapshot,
        ticker, expiration, strike, put_call)


# ---------------------------------------------------------------------------
# yfinance implementations (internal)
# ---------------------------------------------------------------------------

def _yf_list_available_strikes(ticker: str, put_call: str) -> list[float]:
    """
    List all available strike prices for a ticker and option type.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL')
        put_call: 'call' or 'put'
    
    Returns:
        Sorted list of available strike prices
    """
    try:
        stock = yf.Ticker(ticker.upper())
        expirations = stock.options
        
        if not expirations:
            logger.warning(f"No options available for {ticker}")
            return []
        
        # Collect strikes from first 5 expirations for speed
        all_strikes = set()
        for exp_str in expirations[:5]:
            try:
                chain = stock.option_chain(exp_str)
                options_df = chain.calls if put_call == 'call' else chain.puts
                all_strikes.update(options_df['strike'].tolist())
            except Exception as e:
                logger.debug(f"Error getting chain for {exp_str}: {e}")
                continue
        
        return sorted(all_strikes)
    
    except Exception as e:
        logger.error(f"Error fetching strikes for {ticker}: {e}")
        raise


def _yf_list_available_contracts(ticker: str, strike: float, put_call: str) -> list[dict]:
    """
    List all available contracts for given ticker, strike, and type.
    
    Args:
        ticker: Stock ticker symbol
        strike: Strike price
        put_call: 'call' or 'put'
    
    Returns:
        List of dicts with 'contract_symbol', 'expiration', 'dte' for each contract
    """
    try:
        stock = yf.Ticker(ticker.upper())
        expirations = stock.options
        
        result = []
        today = date.today()
        
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            
            # Skip expired options
            if dte < 0:
                continue
            
            try:
                chain = stock.option_chain(exp_str)
                options_df = chain.calls if put_call == 'call' else chain.puts
                
                # Check if the strike exists in this expiration
                if strike in options_df['strike'].values:
                    row = options_df[options_df['strike'] == strike].iloc[0]
                    result.append({
                        'contract_symbol': row['contractSymbol'],
                        'expiration': exp_str,
                        'dte': dte
                    })
            except Exception as e:
                logger.debug(f"Error checking contract for {exp_str}: {e}")
                continue
        
        return result
    
    except Exception as e:
        logger.error(f"Error fetching contracts for {ticker} ${strike} {put_call}: {e}")
        raise


def _yf_get_stock_price(ticker: str) -> Optional[float]:
    """
    Get the current stock price.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        Current stock price or None on error
    """
    try:
        stock = yf.Ticker(ticker.upper())
        price = stock.fast_info.get('lastPrice')
        return float(price) if price else None
    except Exception as e:
        logger.error(f"Error fetching price for {ticker}: {e}")
        return None


def _yf_get_option_data(ticker: str, expiration: str, strike: float, put_call: str) -> Optional[dict]:
    """
    Get current option data including bid, ask, and mid price.
    
    Args:
        ticker: Stock ticker symbol
        expiration: Expiration date string (YYYY-MM-DD)
        strike: Strike price
        put_call: 'call' or 'put'
    
    Returns:
        Dict with bid, ask, mid, last, volume, open_interest, iv
        or None on error
    """
    try:
        stock = yf.Ticker(ticker.upper())
        chain = stock.option_chain(expiration)
        options_df = chain.calls if put_call == 'call' else chain.puts
        
        row = options_df[options_df['strike'] == strike].iloc[0]
        
        bid = row.get('bid', 0) or 0
        ask = row.get('ask', 0) or 0
        mid = (bid + ask) / 2 if bid and ask else row.get('lastPrice', 0)
        
        import pandas as pd
        return {
            'bid': float(bid) if bid else None,
            'ask': float(ask) if ask else None,
            'mid': float(mid) if mid else None,
            'last': float(row.get('lastPrice')) if row.get('lastPrice') else None,
            'volume': int(row.get('volume')) if row.get('volume') else None,
            'open_interest': int(row.get('openInterest')) if row.get('openInterest') else None,
            'iv': float(row.get('impliedVolatility')) if row.get('impliedVolatility') else None,
            'delta': float(row['delta']) if pd.notna(row.get('delta')) else None,
            'gamma': float(row['gamma']) if pd.notna(row.get('gamma')) else None,
            'theta': float(row['theta']) if pd.notna(row.get('theta')) else None,
            'vega': float(row['vega']) if pd.notna(row.get('vega')) else None,
        }
    
    except Exception as e:
        logger.error(f"Error fetching option data for {ticker} ${strike} {put_call} exp:{expiration}: {e}")
        return None


def _yf_fetch_snapshot(ticker: str, expiration: str, strike: float, put_call: str) -> Optional[dict]:
    """
    Fetch a complete snapshot of option and stock data.

    Args:
        ticker: Stock ticker symbol
        expiration: Expiration date string (YYYY-MM-DD)
        strike: Strike price
        put_call: 'call' or 'put'

    Returns:
        Dict with timestamp, stock_price, and all option data
        or None on error
    """
    try:
        timestamp = datetime.now()

        option_data = _yf_get_option_data(ticker, expiration, strike, put_call)
        if option_data is None:
            return None

        stock_price = _yf_get_stock_price(ticker)
        if stock_price is None:
            return None
        
        mid = option_data.get('mid', 0) or 0
        spread_pct = (mid / stock_price) * 100 if stock_price > 0 else 0
        
        return {
            'timestamp': timestamp,
            'stock_price': stock_price,
            'spread_pct': spread_pct,
            **option_data
        }
    
    except Exception as e:
        logger.error(f"Error fetching snapshot for {ticker} ${strike} {put_call}: {e}")
        return None


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


def seconds_until_market_open() -> float:
    """
    Return seconds until the next regular market open (9:30 AM ET, weekdays only).
    Returns 0 if the market is currently open.
    """
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    # Start from today's 9:30 AM ET
    candidate = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

    # If we're at or past 9:30 today, aim for tomorrow
    if now_et.time() >= time(9, 30):
        candidate += timedelta(days=1)

    # Skip weekends (Saturday=5, Sunday=6)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    delta = (candidate - now_et).total_seconds()
    return max(0.0, delta)


def calculate_dte(expiration: str) -> int:
    """
    Calculate days to expiration.
    
    Args:
        expiration: Expiration date string (YYYY-MM-DD)
    
    Returns:
        Number of days until expiration
    """
    try:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        today = date.today()
        return (exp_date - today).days
    except Exception:
        return 0
