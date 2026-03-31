"""
Schwab API client wrapper using schwab-py.

Normal operation: client_from_access_functions loads saved tokens from
GNOME Keyring; schwab-py auto-refreshes the access token on every call.

Auth flow (one-time):
  1. get_auth_url()        → open in browser
  2. complete_auth()       → paste redirect URL; exchanges code, saves tokens
  3. init()                → called automatically by complete_auth()

Tokens are stored encrypted in GNOME Keyring — never written to disk as plaintext.
"""

import json
import logging
from datetime import datetime, date

import keyring

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "options-tracker-schwab"
KEYRING_TOKEN_KEY = "oauth_token"
REDIRECT_URI = "https://127.0.0.1:9090/callback"

_client = None
_client_id = None
_client_secret = None
_auth_context = None  # stored between get_auth_url() and complete_auth()


def _read_token():
    """Read the OAuth token from GNOME Keyring."""
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
    if raw is None:
        return None
    return json.loads(raw)


def _write_token(token, **kwargs):
    """Write the OAuth token to GNOME Keyring."""
    # Log token keys (not values) to help diagnose missing refresh_token
    inner = token.get("token", token) if isinstance(token, dict) else token
    if isinstance(inner, dict):
        has_refresh = "refresh_token" in inner
        logger.info(f"Schwab token write — keys: {sorted(inner.keys())}, has_refresh_token: {has_refresh}")
    keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY, json.dumps(token))


class SchwabUnavailable(Exception):
    pass


def _handle_token_error(error):
    """If the error is a token/auth failure, disable the client to stop retrying."""
    global _client
    err_str = str(error).lower()
    if "token_invalid" in err_str or "token_expired" in err_str or "refresh_token" in err_str:
        logger.warning("Schwab token invalid — disabling client until re-authorized")
        _client = None


# ---------------------------------------------------------------------------
# Init / status
# ---------------------------------------------------------------------------

def init(client_id: str, client_secret: str) -> None:
    """
    Load Schwab client from tokens stored in GNOME Keyring.
    Sets _client to a live client on success; None if token missing or bad.
    Always safe to call — never raises.
    """
    global _client, _client_id, _client_secret
    _client_id = client_id
    _client_secret = client_secret
    try:
        import schwab
        token = _read_token()
        if token is not None:
            _client = schwab.auth.client_from_access_functions(
                client_id, client_secret, _read_token, _write_token
            )
            # Validate that the token actually works with a lightweight call
            if not _validate_client():
                logger.warning("Schwab token is expired or invalid — re-authorize via GUI")
                _client = None
            else:
                logger.info("Schwab client initialized from keyring")
        else:
            logger.info("Schwab tokens not found in keyring — use GUI to authorize")
            _client = None
    except Exception as e:
        logger.warning(f"Schwab client init failed: {e}")
        _client = None


def _validate_client() -> bool:
    """Make a lightweight API call to verify the token is still valid."""
    if _client is None:
        return False
    try:
        resp = _client.get_market_hours(
            _client.MarketHours.Market.EQUITY
        )
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"Schwab token validation failed: {e}")
        return False


def is_available() -> bool:
    """True if the Schwab client is loaded and usable."""
    return _client is not None


def disconnect():
    """Drop the active client — falls back to yfinance. Credentials stay in keyring."""
    global _client
    _client = None


def reset():
    """Clear the in-memory client after credentials are deleted."""
    global _client, _client_id, _client_secret
    _client = None
    _client_id = None
    _client_secret = None


def get_status() -> str:
    """Return 'authorized' | 'token_missing' | 'token_expired' | 'not_configured'."""
    if not _client_id:
        return "not_configured"
    if _client is not None:
        return "authorized"
    if _read_token() is not None:
        return "token_expired"
    return "token_missing"


# ---------------------------------------------------------------------------
# One-time OAuth2 flow helpers (called from GUI)
# ---------------------------------------------------------------------------

def get_auth_url(client_id: str = None, redirect_uri: str = REDIRECT_URI) -> str:
    """Return the Schwab OAuth2 authorization URL to open in a browser."""
    global _auth_context
    import schwab
    cid = client_id or _client_id
    _auth_context = schwab.auth.get_auth_context(cid, redirect_uri)
    return _auth_context.authorization_url


def complete_auth(client_id: str, client_secret: str, received_url: str,
                  redirect_uri: str = REDIRECT_URI) -> bool:
    """
    Exchange the auth code from the redirect URL for tokens.
    Uses schwab-py's client_from_received_url to save tokens and init the client.
    Returns True on success.
    """
    global _client, _auth_context
    try:
        import schwab

        if _auth_context is None:
            _auth_context = schwab.auth.get_auth_context(client_id, redirect_uri)

        _client = schwab.auth.client_from_received_url(
            client_id, client_secret, _auth_context, received_url, _write_token
        )
        logger.info("Schwab tokens saved to keyring")
        return True
    except Exception as e:
        logger.error(f"Schwab auth failed: {e}")
        _client = None
        return False


# ---------------------------------------------------------------------------
# Market data functions (match options_api.py signatures)
# ---------------------------------------------------------------------------

def get_stock_price(ticker: str) -> float:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        resp = _client.get_quote(ticker.upper())
        resp.raise_for_status()
        data = resp.json()
        quote = data[ticker.upper()].get("quote", {})
        mark = quote.get("mark") or quote.get("lastPrice") or quote.get("last")
        if mark is None:
            raise SchwabUnavailable(f"No price in Schwab response for {ticker}")
        return float(mark)
    except SchwabUnavailable:
        raise
    except Exception as e:
        raise SchwabUnavailable(f"Schwab get_stock_price: {e}") from e


def list_available_strikes(ticker: str, put_call: str) -> list:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        import schwab
        contract_type = (schwab.client.Client.Options.ContractType.CALL
                         if put_call == "call"
                         else schwab.client.Client.Options.ContractType.PUT)
        resp = _client.get_option_chain(ticker.upper(), contract_type=contract_type)
        resp.raise_for_status()
        data = resp.json()
        key = "callExpDateMap" if put_call == "call" else "putExpDateMap"
        strikes = set()
        for strike_map in data.get(key, {}).values():
            for s in strike_map:
                try:
                    strikes.add(float(s))
                except ValueError:
                    pass
        return sorted(strikes)
    except SchwabUnavailable:
        raise
    except Exception as e:
        raise SchwabUnavailable(f"Schwab list_available_strikes: {e}") from e


def list_available_contracts(ticker: str, strike: float, put_call: str) -> list:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        import schwab
        contract_type = (schwab.client.Client.Options.ContractType.CALL
                         if put_call == "call"
                         else schwab.client.Client.Options.ContractType.PUT)
        resp = _client.get_option_chain(ticker.upper(), contract_type=contract_type, strike=strike)
        resp.raise_for_status()
        data = resp.json()
        key = "callExpDateMap" if put_call == "call" else "putExpDateMap"
        today = date.today()
        result = []
        for exp_key, strike_map in data.get(key, {}).items():
            exp_str = exp_key.split(":")[0]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 0:
                continue
            for sk, contracts in strike_map.items():
                if abs(float(sk) - strike) < 0.01:
                    for c in contracts:
                        result.append({
                            "contract_symbol": c["symbol"].replace(" ", ""),
                            "expiration": exp_str,
                            "dte": dte,
                        })
        return result
    except SchwabUnavailable:
        raise
    except Exception as e:
        raise SchwabUnavailable(f"Schwab list_available_contracts: {e}") from e


def get_option_data(ticker: str, expiration: str, strike: float, put_call: str) -> dict:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        import schwab
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        contract_type = (schwab.client.Client.Options.ContractType.CALL
                         if put_call == "call"
                         else schwab.client.Client.Options.ContractType.PUT)
        resp = _client.get_option_chain(
            ticker.upper(),
            contract_type=contract_type,
            strike=strike,
            from_date=exp_date,
            to_date=exp_date,
        )
        resp.raise_for_status()
        data = resp.json()
        key = "callExpDateMap" if put_call == "call" else "putExpDateMap"
        for exp_key, strike_map in data.get(key, {}).items():
            if exp_key.startswith(expiration):
                for sk, contracts in strike_map.items():
                    if abs(float(sk) - strike) < 0.01 and contracts:
                        c = contracts[0]
                        bid = c.get("bid")
                        ask = c.get("ask")
                        mark = c.get("mark")
                        mid = (float(mark) if mark is not None
                               else (float(bid) + float(ask)) / 2 if bid and ask else None)
                        iv_raw = c.get("volatility")
                        return {
                            "bid": float(bid) if bid is not None else None,
                            "ask": float(ask) if ask is not None else None,
                            "mid": mid,
                            "last": float(c["last"]) if c.get("last") else None,
                            "volume": int(c["totalVolume"]) if c.get("totalVolume") else None,
                            "open_interest": int(c["openInterest"]) if c.get("openInterest") else None,
                            "iv": float(iv_raw) / 100 if iv_raw else None,
                        }
        raise SchwabUnavailable(f"No data for {ticker} {expiration} {strike} {put_call}")
    except SchwabUnavailable:
        raise
    except Exception as e:
        raise SchwabUnavailable(f"Schwab get_option_data: {e}") from e


def fetch_snapshot(ticker: str, expiration: str, strike: float, put_call: str) -> dict:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    timestamp = datetime.now()
    option_data = get_option_data(ticker, expiration, strike, put_call)
    stock_price = get_stock_price(ticker)
    mid = option_data.get("mid", 0) or 0
    spread_pct = (mid / stock_price) * 100 if stock_price > 0 else 0
    return {
        "timestamp": timestamp,
        "stock_price": stock_price,
        "spread_pct": spread_pct,
        **option_data,
    }


def _to_schwab_option_symbol(contract_symbol: str) -> str:
    """Convert compact contract symbol to Schwab's padded format.

    DB stores:   'AAPL260402C00270000'  (no spaces)
    Schwab needs: 'AAPL  260402C00270000' (ticker padded to 6 chars)
    """
    # Split at the first digit — everything before is the ticker
    for i, ch in enumerate(contract_symbol):
        if ch.isdigit():
            ticker = contract_symbol[:i]
            rest = contract_symbol[i:]
            return f"{ticker:<6}{rest}"
    return contract_symbol


def get_price_history_candles(symbol: str, start_datetime: datetime = None) -> list[dict]:
    """Fetch 5-minute candle history for a symbol (stock ticker or option contract).

    Returns list of dicts: [{"timestamp": datetime, "close": float, "volume": int}, ...]
    """
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        import schwab
        PH = schwab.client.Client.PriceHistory

        kwargs = dict(
            frequency_type=PH.FrequencyType.MINUTE,
            frequency=PH.Frequency.EVERY_FIVE_MINUTES,
            need_extended_hours_data=False,
        )
        if start_datetime:
            kwargs["start_datetime"] = start_datetime
        else:
            kwargs["period_type"] = PH.PeriodType.DAY
            kwargs["period"] = PH.Period.TEN_DAYS

        resp = _client.get_price_history(symbol, **kwargs)
        resp.raise_for_status()
        candles = resp.json().get("candles", [])

        result = []
        for c in candles:
            ts = datetime.fromtimestamp(c["datetime"] / 1000)
            result.append({
                "timestamp": ts,
                "close": float(c["close"]),
                "volume": int(c["volume"]),
            })
        return result
    except SchwabUnavailable:
        raise
    except Exception as e:
        raise SchwabUnavailable(f"Schwab get_price_history_candles: {e}") from e
