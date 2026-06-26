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
import time
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
_last_reconnect_attempt = None  # throttle auto-reconnect to every 5 min
# True once the server has rejected our refresh token with invalid_grant. The token
# in the keyring is dead and no amount of re-init/reconnect can revive it — only a
# full re-Authorize will. This is distinct from a merely-lapsed access token, and it
# drives the GUI to reset to Step 1 instead of offering a (futile) Reconnect.
_reauth_required = False

# Short-lived cache of the full option chain per (ticker, put_call). The chain is
# the heaviest market-data call and several paths request the same ticker within
# a few seconds (QuickAddCard strikes→contracts, watcher polling several
# contracts on one ticker). Caching collapses those bursts into a single Schwab
# request, easing the ~120/min per-app rate limit. TTL is short so stored
# snapshots stay fresh — each 30s/5min poll still fetches a live chain.
_CHAIN_CACHE_TTL = 8.0  # seconds
_chain_cache = {}        # (ticker, put_call) -> (monotonic_ts, parsed_json)


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


def _is_refresh_token_dead(error) -> bool:
    """True if the error is an OAuth invalid_grant — the refresh token itself is
    revoked/expired and cannot be revived by re-init or reconnect (the keyring holds
    the same dead token). Only a full re-Authorize fixes it. Schwab phrases this as a
    400 with "Refresh token is invalid, expired or revoked"."""
    s = str(error).lower()
    return any(x in s for x in (
        "invalid_grant", "unsupported_token_type", "refresh token is invalid",
    ))


def _handle_token_error(error):
    """If the error is a token/auth failure, try to reinit from keyring (refresh token).
    Only disables the client if reinit also fails."""
    global _client, _reauth_required
    err_str = str(error).lower()

    # A dead refresh token cannot be recovered by re-init — the keyring holds the same
    # dead token. Flag re-auth as required (drives the GUI back to Step 1) and disable
    # the client immediately so we fall back to yfinance instead of retrying every cycle.
    if _is_refresh_token_dead(error):
        if not _reauth_required:
            logger.warning(
                "Schwab refresh token is invalid/expired/revoked — re-authorize from "
                "Step 1 in the GUI (Reconnect cannot revive it)"
            )
        _reauth_required = True
        _client = None
        return

    # Check for explicit token error strings
    is_token_error = any(s in err_str for s in (
        "token_invalid", "token_expired", "refresh_token", "refresh token",
        "401 unauthorized", "403 forbidden",
    ))

    # Check for httpx.HTTPStatusError with 401/403 status code
    if not is_token_error:
        resp = getattr(error, "response", None)
        if resp is not None and getattr(resp, "status_code", None) in (401, 403):
            is_token_error = True

    if is_token_error:
        logger.warning("Schwab auth failed (%s) — attempting token refresh", error)
        # Try to reinitialize — schwab-py may auto-refresh the access token
        if _client_id and _client_secret:
            _client = None
            init(_client_id, _client_secret)
            if _client is not None:
                logger.info("Schwab token refreshed successfully")
                return
        logger.warning("Schwab token refresh failed — disabling client until re-authorized")
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
    global _client, _client_id, _client_secret, _reauth_required
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
                _reauth_required = False  # a live token clears any prior revoked flag
                logger.info("Schwab client initialized from keyring")
        else:
            logger.info("Schwab tokens not found in keyring — use GUI to authorize")
            _client = None
    except Exception as e:
        logger.warning(f"Schwab client init failed: {e}")
        _client = None


def _validate_client() -> bool:
    """Make a lightweight API call to verify the token is still valid.
    Retries once after a short delay to handle transient failures."""
    import time as _time
    global _reauth_required
    if _client is None:
        return False
    for attempt in range(2):
        try:
            resp = _client.get_market_hours(
                _client.MarketHours.Market.EQUITY
            )
            if resp.status_code == 200:
                return True
            logger.debug(f"Schwab validation attempt {attempt+1} returned {resp.status_code}")
        except Exception as e:
            logger.debug(f"Schwab validation attempt {attempt+1} failed: {e}")
            # A revoked refresh token won't recover on retry — flag it and stop early
            # so the GUI routes to Step 1 and we don't burn the 3s backoff for nothing.
            if _is_refresh_token_dead(e):
                _reauth_required = True
                return False
        if attempt == 0:
            _time.sleep(3)
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
    global _client, _client_id, _client_secret, _reauth_required
    _client = None
    _client_id = None
    _client_secret = None
    _reauth_required = False
    _chain_cache.clear()


def clear_token():
    """Delete the stored OAuth token (keeping client_id/secret) and clear the revoked
    flag. Used when recovering from a revoked token: discarding the dead token moves the
    flow to 'token_missing' (Step 2 / Authorize) instead of looping back to Step 1."""
    global _client, _reauth_required
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
    except Exception:
        pass  # token already absent — nothing to delete
    _client = None
    _reauth_required = False


def get_status() -> str:
    """Return 'authorized' | 'token_revoked' | 'token_expired' | 'token_missing' | 'not_configured'.

    token_revoked is distinct from token_expired: the refresh token itself was rejected
    (invalid_grant), so Reconnect is futile and the GUI must route to a full re-Authorize.
    """
    if not _client_id:
        return "not_configured"
    if _client is not None:
        return "authorized"
    if _reauth_required:
        return "token_revoked"
    if _read_token() is not None:
        return "token_expired"
    return "token_missing"


def try_reconnect() -> bool:
    """Attempt to reconnect if client is down but credentials exist.

    Throttled to once every 5 minutes so it doesn't spam Schwab.
    Uses more retries than _validate_client (5 attempts with 5s backoff)
    to survive transient failures at market open.

    Returns True if reconnected successfully.
    """
    global _last_reconnect_attempt, _client, _reauth_required
    import time as _time

    if _client is not None:
        return True  # already connected
    if not _client_id or not _client_secret:
        return False  # no credentials
    if _read_token() is None:
        return False  # no token to refresh
    if _reauth_required:
        return False  # refresh token revoked — only a full re-Authorize can fix it

    # Throttle: skip if we tried less than 5 min ago
    now = _time.time()
    if _last_reconnect_attempt and (now - _last_reconnect_attempt) < 300:
        return False
    _last_reconnect_attempt = now

    logger.info("Schwab auto-reconnect: attempting token refresh...")

    import schwab
    try:
        client = schwab.auth.client_from_access_functions(
            _client_id, _client_secret, _read_token, _write_token
        )
    except Exception as e:
        logger.warning(f"Schwab auto-reconnect: client creation failed: {e}")
        return False

    # Try up to 5 times with 5s gaps — enough to ride out 9:30 AM server load
    for attempt in range(5):
        try:
            resp = client.get_market_hours(client.MarketHours.Market.EQUITY)
            if resp.status_code == 200:
                _client = client
                logger.info("Schwab auto-reconnect: success — back on Schwab")
                return True
            logger.debug(f"Schwab auto-reconnect attempt {attempt+1}: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Schwab auto-reconnect attempt {attempt+1}: {e}")
            if _is_refresh_token_dead(e):
                _reauth_required = True
                logger.warning("Schwab auto-reconnect: refresh token revoked — "
                               "re-authorize from Step 1 (giving up auto-reconnect)")
                return False
        if attempt < 4:
            _time.sleep(5)

    logger.warning("Schwab auto-reconnect: failed after 5 attempts — will retry in 5 min")
    return False


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
    global _client, _auth_context, _reauth_required
    try:
        import schwab

        if _auth_context is None:
            _auth_context = schwab.auth.get_auth_context(client_id, redirect_uri)

        _client = schwab.auth.client_from_received_url(
            client_id, client_secret, _auth_context, received_url, _write_token
        )
        _reauth_required = False  # fresh token from a full re-Authorize — clear the flag
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


def _get_chain_json(ticker: str, put_call: str) -> dict:
    """Return the full (unfiltered) Schwab option chain for ticker/put_call.

    Result is cached for _CHAIN_CACHE_TTL seconds so repeated calls for the same
    ticker within a short window reuse one Schwab request. Always fetches the
    unfiltered chain so any strike/expiration query can be served from it.
    Raises SchwabUnavailable on failure.
    """
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    ticker = ticker.upper()
    cache_key = (ticker, put_call)
    cached = _chain_cache.get(cache_key)
    if cached is not None and (time.monotonic() - cached[0]) < _CHAIN_CACHE_TTL:
        return cached[1]
    import schwab
    contract_type = (schwab.client.Client.Options.ContractType.CALL
                     if put_call == "call"
                     else schwab.client.Client.Options.ContractType.PUT)
    resp = _client.get_option_chain(ticker, contract_type=contract_type)
    resp.raise_for_status()
    data = resp.json()
    _chain_cache[cache_key] = (time.monotonic(), data)
    return data


def list_available_strikes(ticker: str, put_call: str) -> list:
    if not _client:
        raise SchwabUnavailable("Schwab not available")
    try:
        data = _get_chain_json(ticker, put_call)
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
        data = _get_chain_json(ticker, put_call)
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
        data = _get_chain_json(ticker, put_call)
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
                            "delta": float(c["delta"]) if c.get("delta") is not None else None,
                            "gamma": float(c["gamma"]) if c.get("gamma") is not None else None,
                            "theta": float(c["theta"]) if c.get("theta") is not None else None,
                            "vega": float(c["vega"]) if c.get("vega") is not None else None,
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
