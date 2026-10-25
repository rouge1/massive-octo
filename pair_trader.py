"""
Live pair trading monitor -- Phase 1 (paper trading only, no orders placed).

Runs alongside options_watcher.py.  Reuses the Schwab client + credentials
already authorized in GNOME Keyring.  No DB writes; logs go to:
  data/pair_paper_trades.json   -- one entry per ENTRY / EXIT signal
  data/pair_status.log          -- rolling status line per poll

Strategy parameters mirror the validated intraday backtest
(pair_backtest_nws_nwsa.py) -- 10-day rolling lookback, +/-2sig entry,
mean exit, +/-5sig stop, 7-day max calendar hold.

Phase 2 will add real order placement; Phase 3 adds floating quotes for
sweep capture.  Stop after Phase 1 to validate signals match backtest.

Run:
  conda activate mass
  python pair_trader.py
"""

import sys
import time
import json
import logging
from datetime import datetime, time as dtime, timedelta
from collections import deque
from pathlib import Path

import pytz

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from apps import schwab_client  # noqa: E402
from apps import gui_methods as gm  # noqa: E402


# ---- Config ----------------------------------------------------------------
PAIRS = [
    {"a": "NWS",   "b": "NWSA",  "shares": 1000},
    {"a": "GOOGL", "b": "GOOG",  "shares": 1000},
    {"a": "FOX",   "b": "FOXA",  "shares": 1000},
]

LOOKBACK_BARS = 780      # ~10 trading days of 5-min bars
ENTRY_SIGMA = 2.0
EXIT_SIGMA = 0.0
STOP_SIGMA = 5.0
MAX_HOLD_DAYS = 7        # calendar days (5 trading + 2 weekend buffer)
ALLOW_OVERNIGHT = True

POLL_INTERVAL_SEC = 30
BAR_INTERVAL_MIN = 5     # match historical bar interval

ET_TZ = pytz.timezone("US/Eastern")
TRADE_LOG_PATH = ROOT / "data" / "pair_paper_trades.json"
STATUS_LOG_PATH = ROOT / "data" / "pair_status.log"


# ---- Helpers --------------------------------------------------------------
def now_et():
    return datetime.now(ET_TZ)


def is_market_open():
    n = now_et()
    if n.weekday() >= 5:
        return False
    return dtime(9, 30) <= n.time() < dtime(16, 0)


def append_trade_log(event):
    TRADE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if TRADE_LOG_PATH.exists():
        try:
            log = json.loads(TRADE_LOG_PATH.read_text())
        except json.JSONDecodeError:
            log = []
    log.append(event)
    TRADE_LOG_PATH.write_text(json.dumps(log, indent=2, default=str))


def append_status_line(line):
    STATUS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_LOG_PATH.open("a") as f:
        f.write(line + "\n")


# ---- Pair monitor ---------------------------------------------------------
class PairMonitor:
    def __init__(self, ticker_a, ticker_b, shares):
        self.a = ticker_a
        self.b = ticker_b
        self.shares = shares
        # spread_history is a deque of (timestamp, spread) tuples, one per 5-min bar
        self.spread_history = deque(maxlen=LOOKBACK_BARS + 100)
        self.last_bar_ts = None      # most recent 5-min bar timestamp added
        # Position state
        self.position = 0            # +1 long spread, -1 short, 0 flat
        self.entry_spread = 0.0
        self.entry_ts = None

    def seed_from_history(self):
        """Pull 10 days of historical 5-min candles to seed the rolling window."""
        cands_a = schwab_client.get_price_history_candles(self.a)
        cands_b = schwab_client.get_price_history_candles(self.b)
        # Align by timestamp
        map_a = {c["timestamp"]: c["close"] for c in cands_a}
        map_b = {c["timestamp"]: c["close"] for c in cands_b}
        common_ts = sorted(set(map_a) & set(map_b))
        for ts in common_ts:
            self.spread_history.append((ts, map_a[ts] - map_b[ts]))
        if self.spread_history:
            self.last_bar_ts = self.spread_history[-1][0]

    def _maybe_append_bar(self, spread, ts_naive):
        """Append a new bar if at least BAR_INTERVAL_MIN minutes have passed."""
        if self.last_bar_ts is None:
            self.spread_history.append((ts_naive, spread))
            self.last_bar_ts = ts_naive
            return
        elapsed = (ts_naive - self.last_bar_ts).total_seconds() / 60
        if elapsed >= BAR_INTERVAL_MIN:
            self.spread_history.append((ts_naive, spread))
            self.last_bar_ts = ts_naive

    def _rolling_stats(self):
        """Return (mean, stdev) over the last LOOKBACK_BARS bars in spread_history."""
        spreads = [s for _, s in list(self.spread_history)[-LOOKBACK_BARS:]]
        n = len(spreads)
        if n < LOOKBACK_BARS:
            return None, None, n
        m = sum(spreads) / n
        var = sum((s - m) ** 2 for s in spreads) / (n - 1)
        return m, var ** 0.5, n

    def update(self):
        """Fetch live quotes, update state, return (kind, payload).

        kind in: 'status' | 'warmup' | 'ENTRY' | 'EXIT' | 'error'
        """
        try:
            price_a = schwab_client.get_stock_price(self.a)
            price_b = schwab_client.get_stock_price(self.b)
        except Exception as e:
            return ("error", str(e))

        spread = price_a - price_b
        ts_et = now_et()
        ts_naive = ts_et.replace(tzinfo=None)

        self._maybe_append_bar(spread, ts_naive)
        mean, std, n = self._rolling_stats()
        if mean is None:
            return ("warmup", {"pair": f"{self.a}/{self.b}",
                               "have": n, "need": LOOKBACK_BARS})

        z = (spread - mean) / std if std and std > 0 else 0.0
        days_held = ((ts_et - self.entry_ts).total_seconds() / 86400
                     if self.position != 0 and self.entry_ts else 0.0)

        # Exit logic
        if self.position != 0:
            exit_reason = None
            if self.position == +1 and z >= EXIT_SIGMA:
                exit_reason = "mean"
            elif self.position == -1 and z <= EXIT_SIGMA:
                exit_reason = "mean"
            elif abs(z) >= STOP_SIGMA:
                exit_reason = "stop"
            elif days_held >= MAX_HOLD_DAYS:
                exit_reason = "max_hold"

            if exit_reason:
                pnl = ((spread - self.entry_spread) if self.position == +1
                       else (self.entry_spread - spread)) * self.shares
                trade = {
                    "pair": f"{self.a}/{self.b}",
                    "side": "long_spread" if self.position == +1 else "short_spread",
                    "entry_ts": self.entry_ts.isoformat(),
                    "exit_ts": ts_et.isoformat(),
                    "entry_spread": round(self.entry_spread, 4),
                    "exit_spread": round(spread, 4),
                    "shares": self.shares,
                    "gross_pnl": round(pnl, 2),
                    "exit_reason": exit_reason,
                    "z_at_exit": round(z, 2),
                    "days_held": round(days_held, 2),
                }
                self.position = 0
                self.entry_ts = None
                return ("EXIT", trade)

        # Entry logic
        if self.position == 0:
            if z <= -ENTRY_SIGMA:
                self.position = +1
                self.entry_spread = spread
                self.entry_ts = ts_et
                return ("ENTRY", {
                    "pair": f"{self.a}/{self.b}", "side": "long_spread",
                    "entry_spread": round(spread, 4), "z": round(z, 2),
                    "ts": ts_et.isoformat(), "shares": self.shares,
                })
            if z >= ENTRY_SIGMA:
                self.position = -1
                self.entry_spread = spread
                self.entry_ts = ts_et
                return ("ENTRY", {
                    "pair": f"{self.a}/{self.b}", "side": "short_spread",
                    "entry_spread": round(spread, 4), "z": round(z, 2),
                    "ts": ts_et.isoformat(), "shares": self.shares,
                })

        return ("status", {
            "pair": f"{self.a}/{self.b}",
            "spread": round(spread, 4), "mean": round(mean, 4),
            "std": round(std, 4), "z": round(z, 2),
            "position": self.position, "days_held": round(days_held, 2),
        })


# ---- Driver ---------------------------------------------------------------
def init_schwab():
    creds = gm.get_schwab_credentials()
    if not creds.get("client_id") or not creds.get("client_secret"):
        print("ERROR: Schwab credentials not in keyring. "
              "Run options_watcher.py and authorize first.")
        sys.exit(1)
    schwab_client.init(creds["client_id"], creds["client_secret"])
    if not schwab_client.is_available():
        print("ERROR: Schwab client failed to initialize. Token expired? "
              "Re-authorize via options_watcher.py.")
        sys.exit(1)
    print("Schwab client OK.")


def main():
    print("=" * 70)
    print("Pair Trader -- Phase 1 (paper trading, no real orders)")
    print("=" * 70)
    init_schwab()

    monitors = [PairMonitor(p["a"], p["b"], p["shares"]) for p in PAIRS]
    print(f"\nSeeding {len(monitors)} pairs from 10-day history...")
    for m in monitors:
        try:
            m.seed_from_history()
            print(f"  {m.a}/{m.b}: {len(m.spread_history)} bars seeded "
                  f"(latest: {m.last_bar_ts})")
        except Exception as e:
            print(f"  {m.a}/{m.b}: SEED FAILED -- {e}")

    print(f"\nConfig: lookback={LOOKBACK_BARS}b  entry=+/-{ENTRY_SIGMA}sig  "
          f"exit={EXIT_SIGMA}sig  stop=+/-{STOP_SIGMA}sig  "
          f"max_hold={MAX_HOLD_DAYS}d  poll={POLL_INTERVAL_SEC}s")
    print(f"Trade log: {TRADE_LOG_PATH}")
    print(f"Status log: {STATUS_LOG_PATH}")
    print(f"\nMonitoring. Ctrl-C to stop.\n")

    try:
        while True:
            if not is_market_open():
                print(f"[{now_et().strftime('%Y-%m-%d %H:%M:%S')} ET] "
                      f"Market closed -- sleeping 5 min")
                time.sleep(300)
                continue

            ts_str = now_et().strftime("%H:%M:%S")
            line_chunks = [f"[{ts_str}]"]
            for m in monitors:
                kind, payload = m.update()
                if kind in ("ENTRY", "EXIT"):
                    print(f"\n  >>> {kind}: {json.dumps(payload, default=str)}\n")
                    append_trade_log({"event": kind, **payload})
                elif kind == "status":
                    pos = {0: "flat", 1: "LONG", -1: "SHORT"}[payload["position"]]
                    chunk = (f"{payload['pair']}: spr={payload['spread']:>+7.3f} "
                             f"mu={payload['mean']:>+7.3f} z={payload['z']:>+5.2f} "
                             f"[{pos}")
                    if payload["position"] != 0:
                        chunk += f" {payload['days_held']:.1f}d"
                    chunk += "]"
                    line_chunks.append(chunk)
                elif kind == "warmup":
                    line_chunks.append(
                        f"{payload['pair']}: warmup {payload['have']}/{payload['need']}")
                elif kind == "error":
                    line_chunks.append(f"{m.a}/{m.b}: ERR {payload}")
                    # If Schwab fell over, try to recover next cycle
                    schwab_client.try_reconnect()

            line = "  ".join(line_chunks)
            print(line)
            append_status_line(line)

            time.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n\nStopping.")
        # On clean shutdown, log open positions for restart context
        open_pos = [(m.a, m.b, m.position, m.entry_ts, m.entry_spread)
                    for m in monitors if m.position != 0]
        if open_pos:
            print(f"WARNING: {len(open_pos)} open paper position(s) at shutdown:")
            for a, b, pos, ts, sp in open_pos:
                side = "long_spread" if pos == +1 else "short_spread"
                print(f"  {a}/{b}  {side}  entry={sp:.3f}  ts={ts}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
