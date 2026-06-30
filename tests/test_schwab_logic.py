"""Headless tests for the Schwab client state machine and symbol formatting.

These are the highest-ROI regression guards: they cover the exact logic where the
token-spam and frozen-GUI bugs lived (the invalid_grant classifier, the
token_revoked routing, the 6-char symbol padding). They make NO network calls and
NEVER write to the keyring, so they are safe to run while the watcher is live and
holding a real token.

Safety model: we monkeypatch `_read_token` so the real keyring is never read, and
stub `keyring.delete_password` for the one clear_token() case. The module globals
mutated here live in THIS process only — the running watcher has its own copy.

Run:  python tests/test_schwab_logic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import Check
import apps.schwab_client as sc

c = Check()

# The exact error Schwab returns for a dead refresh token (copied from watcher.log).
REVOKED_ERR = ('Schwab get_option_data: unsupported_token_type: 400 Bad Request: '
               '"{"error_description":"Refresh token is invalid, expired or revoked",'
               '"error":"invalid_grant"}"')


def reset_module_state():
    """Put the module globals into a known, network-free state for each block."""
    sc._client = None
    sc._client_id = None
    sc._client_secret = None
    sc._reauth_required = False
    sc._last_reconnect_attempt = None
    sc._read_token = _orig_read_token  # restore real reader between blocks if needed


_orig_read_token = sc._read_token


# ---------------------------------------------------------------------------
# 1. invalid_grant classifier — the matcher bug that caused 30s log spam
# ---------------------------------------------------------------------------
print("\n[1] _is_refresh_token_dead classifier")
c.that("catches the real invalid_grant error from the logs",
       sc._is_refresh_token_dead(Exception(REVOKED_ERR)))
c.that("catches bare 'invalid_grant'",
       sc._is_refresh_token_dead(Exception("oauth error: invalid_grant")))
c.that("catches 'unsupported_token_type'",
       sc._is_refresh_token_dead(Exception("unsupported_token_type: 400")))
c.that("catches 'refresh token is invalid' phrasing",
       sc._is_refresh_token_dead(Exception("The refresh token is invalid")))
c.that("ignores a benign network timeout",
       not sc._is_refresh_token_dead(Exception("connection timed out")))
c.that("ignores a plain 401 (lapsed access token, recoverable)",
       not sc._is_refresh_token_dead(Exception("401 Unauthorized")))

# ---------------------------------------------------------------------------
# 2. Symbol padding — silent 0-candle bug if ticker isn't padded to 6 chars
# ---------------------------------------------------------------------------
print("\n[2] _to_schwab_option_symbol padding")
c.that("AAPL -> 2 trailing spaces (6-char ticker field)",
       sc._to_schwab_option_symbol("AAPL260402C00270000") == "AAPL  260402C00270000")
c.that("MSTR (live watchlist contract) pads correctly",
       sc._to_schwab_option_symbol("MSTR260717P00100000") == "MSTR  260717P00100000")
c.that("single-letter ticker F pads to 6",
       sc._to_schwab_option_symbol("F260116C00012000") == "F     260116C00012000")
c.that("ticker field is exactly 6 chars wide",
       len(sc._to_schwab_option_symbol("STRC260717P00090000").split("2")[0]) == 6)

# ---------------------------------------------------------------------------
# 3. get_status state machine — every branch the GUI stepper routes on
# ---------------------------------------------------------------------------
print("\n[3] get_status state machine")
reset_module_state()
c.that("no client_id -> not_configured", sc.get_status() == "not_configured")

sc._client_id = "id"
sc._client_secret = "secret"
sc._read_token = lambda: {"access_token": "x"}  # pretend a token sits in the keyring

sc._client = object()  # a live client
c.that("live client -> authorized", sc.get_status() == "authorized")

sc._client = None
sc._reauth_required = True
c.that("dead refresh token -> token_revoked (NOT token_expired)",
       sc.get_status() == "token_revoked")

sc._reauth_required = False
c.that("token present, client down, not revoked -> token_expired",
       sc.get_status() == "token_expired")

sc._read_token = lambda: None
c.that("no token in keyring -> token_missing", sc.get_status() == "token_missing")

# ---------------------------------------------------------------------------
# 4. _handle_token_error — dead token disables client + flips to revoked
# ---------------------------------------------------------------------------
print("\n[4] _handle_token_error on a dead refresh token")
reset_module_state()
sc._client_id = "id"
sc._client_secret = "secret"
sc._read_token = lambda: {"access_token": "x"}
sc._client = object()
sc._reauth_required = False

sc._handle_token_error(Exception(REVOKED_ERR))
c.that("client disabled after invalid_grant", sc._client is None)
c.that("reauth_required flag set", sc._reauth_required is True)
c.that("status routes to token_revoked", sc.get_status() == "token_revoked")

# A benign error must NOT nuke a healthy client or flip the revoked flag.
reset_module_state()
sc._client_id = "id"
sc._client_secret = "secret"
sc._read_token = lambda: {"access_token": "x"}
live = object()
sc._client = live
sc._reauth_required = False
sc._handle_token_error(Exception("connection timed out"))
c.that("benign error leaves live client untouched", sc._client is live)
c.that("benign error does not set reauth_required", sc._reauth_required is False)

# ---------------------------------------------------------------------------
# 5. try_reconnect short-circuits when revoked (no futile 5x5s network loop)
# ---------------------------------------------------------------------------
print("\n[5] try_reconnect bails on a revoked token (no network)")
reset_module_state()
sc._client_id = "id"
sc._client_secret = "secret"
sc._read_token = lambda: {"access_token": "x"}
sc._client = None
sc._reauth_required = True
sc._last_reconnect_attempt = None
# If this tried the network it would import schwab and loop; the revoked guard
# returns False immediately before any of that.
c.that("try_reconnect returns False immediately when revoked",
       sc.try_reconnect() is False)

# ---------------------------------------------------------------------------
# 6. clear_token recovery — revoked -> token_missing (Step 2 / Authorize)
# ---------------------------------------------------------------------------
print("\n[6] clear_token recovery routing")
reset_module_state()
sc._client_id = "id"
sc._client_secret = "secret"
sc._client = None
sc._reauth_required = True
_deleted = {"n": 0}
sc.keyring.delete_password = lambda *a, **k: _deleted.__setitem__("n", _deleted["n"] + 1)
sc._read_token = lambda: None  # token gone after delete
sc.clear_token()
c.that("clear_token attempted a keyring delete", _deleted["n"] == 1)
c.that("reauth_required cleared", sc._reauth_required is False)
c.that("client cleared", sc._client is None)
c.that("status now token_missing -> routes to Authorize, not Step 1",
       sc.get_status() == "token_missing")

# ---------------------------------------------------------------------------
# 7. reset() fully tears down -> not_configured
# ---------------------------------------------------------------------------
print("\n[7] reset clears all state")
sc._client = object()
sc._client_id = "id"
sc._reauth_required = True
sc.reset()
c.that("reset -> not_configured", sc.get_status() == "not_configured")

sys.exit(c.report("Schwab logic"))
