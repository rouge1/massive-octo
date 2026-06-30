"""Live smoke tests against the running FastAPI server.

Hits the real REST endpoints and asserts the response SHAPES the frontend depends
on. This is where the codebase's documented field-mapping traps get caught:
  - /api/contracts returns `contract_symbol` (NOT `ticker`) as the canonical ID
  - /api/snapshots/{id}/latest carries the full bid/ask/greeks field set
  - snapshots come back newest-first (the frontend .reverse()s them)

It also reports the live data source (schwab vs yfinance) and checks snapshot
freshness against the server's own clock when the market is open.

Requires the website server to be running (./mass.sh start). Reads the host/port/
SSL config from config/website_settings.json. Self-signed cert -> verify=False.

Run:  python tests/test_api_smoke.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Check

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(PROJECT_DIR, "config", "website_settings.json")

c = Check()


def base_url():
    with open(SETTINGS) as f:
        cfg = json.load(f)
    srv = cfg.get("server", {})
    host = srv.get("domain_name", "localhost")
    port = srv.get("port", 8081)
    scheme = "https" if srv.get("ssl_cert") else "http"
    return f"{scheme}://{host}:{port}"


def get(path):
    return requests.get(BASE + path, verify=False, timeout=15)


try:
    BASE = os.environ.get("VERIFY_BASE_URL") or base_url()
except Exception as e:
    print(f"  FAIL  could not read {SETTINGS}: {e}")
    sys.exit(1)

print(f"\n[*] target: {BASE}")

# Reachability gate — if the server is down, fail fast with a clear hint.
try:
    ms = get("/api/market/status")
except Exception as e:
    print(f"  FAIL  server unreachable at {BASE} ({e})")
    print("        start it with:  ./mass.sh start")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 1. Market status
# ---------------------------------------------------------------------------
print("\n[1] /api/market/status")
c.that("HTTP 200", ms.status_code == 200)
mstat = ms.json()
c.that("has boolean is_open", isinstance(mstat.get("is_open"), bool))
c.that("has status string", isinstance(mstat.get("status"), str))
data_source = mstat.get("data_source")
c.that("has data_source", data_source in ("schwab", "yfinance"))
c.info(f"market is {mstat.get('status')}, data_source = {data_source}")
if data_source != "schwab":
    c.info("NOTE: not on Schwab right now — running on yfinance fallback")

# ---------------------------------------------------------------------------
# 2. Watchlist
# ---------------------------------------------------------------------------
print("\n[2] /api/watchlist")
wl = get("/api/watchlist")
c.that("HTTP 200", wl.status_code == 200)
items = wl.json()
c.that("returns a list", isinstance(items, list))

sample = items[0] if items else None
if sample:
    for field in ("id", "ticker", "strike", "put_call", "expiration", "contract_symbol"):
        c.that(f"item has '{field}'", field in sample)
    c.info(f"sample item: {sample['ticker']} {sample['strike']} {sample['put_call']} (id={sample['id']})")
else:
    c.warn("watchlist is non-empty (downstream item tests skipped if empty)", False)

# ---------------------------------------------------------------------------
# 3. Strikes + contracts (the contract_symbol canonical-ID trap)
# ---------------------------------------------------------------------------
if sample:
    ticker, strike, pc = sample["ticker"], sample["strike"], sample["put_call"]

    print(f"\n[3] /api/strikes/{ticker}/{pc}")
    sr = get(f"/api/strikes/{ticker}/{pc}")
    c.that("HTTP 200", sr.status_code == 200)
    strikes = sr.json().get("strikes")
    c.that("has non-empty strikes list", isinstance(strikes, list) and len(strikes) > 0)
    c.that("strikes are numbers", all(isinstance(x, (int, float)) for x in (strikes or [])))

    print(f"\n[4] /api/contracts/{ticker}/{int(strike)}/{pc}")
    cr = get(f"/api/contracts/{ticker}/{int(strike)}/{pc}")
    c.that("HTTP 200", cr.status_code == 200)
    contracts = cr.json().get("contracts")
    c.that("has contracts list", isinstance(contracts, list))
    if contracts:
        ct = contracts[0]
        c.that("contract has 'contract_symbol' (canonical ID, not 'ticker')",
               "contract_symbol" in ct and bool(ct["contract_symbol"]))
        c.that("contract has 'expiration'", "expiration" in ct)
        c.that("contract has 'dte'", "dte" in ct)

    print(f"\n[5] /api/price/{ticker}")
    pr = get(f"/api/price/{ticker}")
    c.that("HTTP 200", pr.status_code == 200)
    price = pr.json().get("price")
    c.that("price is a positive number", isinstance(price, (int, float)) and price > 0)

    # -----------------------------------------------------------------------
    # 6. Snapshot field set + ordering
    # -----------------------------------------------------------------------
    item_id = sample["id"]
    print(f"\n[6] /api/snapshots/{item_id}/latest")
    lr = get(f"/api/snapshots/{item_id}/latest")
    c.that("HTTP 200", lr.status_code == 200)
    snap = lr.json()
    snap_fields = ("timestamp", "stock_price", "bid", "ask", "mid", "last_price",
                   "volume", "open_interest", "implied_volatility", "spread_pct",
                   "delta", "gamma", "theta", "vega")
    for field in snap_fields:
        c.that(f"latest snapshot has '{field}'", field in snap)

    print(f"\n[7] /api/snapshots/{item_id}?limit=10 ordering")
    hr = get(f"/api/snapshots/{item_id}?limit=10")
    c.that("HTTP 200", hr.status_code == 200)
    hist = hr.json()
    c.that("returns a list", isinstance(hist, list))
    if isinstance(hist, list) and len(hist) >= 2:
        ts = [s["timestamp"] for s in hist]
        c.that("snapshots are newest-first (frontend .reverse()s them)",
               ts == sorted(ts, reverse=True))

    # -----------------------------------------------------------------------
    # 8. Freshness (soft) — only meaningful when the market is open
    # -----------------------------------------------------------------------
    print("\n[8] snapshot freshness")
    if mstat.get("is_open"):
        from datetime import datetime
        # Compare against the server's own ET clock to sidestep timezone drift.
        now_et = datetime.strptime(
            mstat["current_time"].rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S")
        snap_ts = datetime.fromisoformat(snap["timestamp"])
        age_min = (now_et - snap_ts).total_seconds() / 60.0
        c.info(f"latest snapshot is {age_min:.1f} min old")
        c.warn("latest snapshot < 10 min old (writer is keeping up)", age_min < 10)
    else:
        c.info("market closed — skipping freshness check")

sys.exit(c.report("API smoke"))
