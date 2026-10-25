"""
Pair trading backtest -- intraday (5-min bars).

Strategy (per pair A/B):
  spread     = A - B
  rolling    = LOOKBACK_BARS-bar mean (mu) and stdev (sigma)
  z          = (spread - mu) / sigma

  z <= -ENTRY_SIGMA  -> long the spread  (long A, short B)
  z >= +ENTRY_SIGMA  -> short the spread (short A, long B)

Exit conditions (whichever fires first):
  1. z reverts through EXIT_SIGMA           -> "mean reversion"
  2. |z| >= STOP_SIGMA                      -> "stop loss"
  3. bars_held >= MAX_HOLD_BARS             -> "max hold"
  4. last bar of session and !ALLOW_OVERNIGHT -> "EOD"

NOT modelled: sweep-capture / price-improvement edge (needs tick data).
Treat backtested PnL as a floor; live execution adds 3-5c/sh on entries.

Run:
  conda activate mass
  python pair_backtest_nws_nwsa.py
"""

import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt


# ---- Config ----------------------------------------------------------------
PAIRS = [
    ("NWS",   "NWSA"),    # News Corp:  Class B voting / Class A non-voting
    ("GOOGL", "GOOG"),    # Alphabet:   Class A voting / Class C non-voting
    ("FOX",   "FOXA"),    # Fox Corp:   Class B voting / Class A non-voting
]

INTERVAL = "5m"
HISTORY_PERIOD = "60d"    # yfinance hard cap for 5m intraday bars

LOOKBACK_BARS = 780       # ~10 trading days (78 bars/day x 10)
ENTRY_SIGMA = 2.0
EXIT_SIGMA = 0.0          # exit when z crosses through mean
STOP_SIGMA = 5.0          # bail if z keeps blowing out
MAX_HOLD_BARS = 390       # ~5 trading days
ALLOW_OVERNIGHT = True    # if False, force-close at last bar of session

SHARES_PER_LEG = 1000
COMMISSION_PER_LEG = 0.0  # Schwab equities free
SLIPPAGE_PER_SHARE = 0.01 # 1c/sh per leg, both sides


# ---- Data -----------------------------------------------------------------
def fetch_pair(ticker_a, ticker_b):
    print(f"\nFetching {INTERVAL} bars for {ticker_a} / {ticker_b}...")
    raw = yf.download(
        [ticker_a, ticker_b],
        period=HISTORY_PERIOD,
        interval=INTERVAL,
        progress=False,
        auto_adjust=False,
        group_by="ticker",
    )
    df = pd.DataFrame({
        ticker_a: raw[ticker_a]["Close"],
        ticker_b: raw[ticker_b]["Close"],
    }).dropna()
    # yfinance returns tz-aware index; normalize to ET for session boundaries
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("US/Eastern")
    return df


def compute_spread_stats(df, ticker_a, ticker_b):
    df = df.copy()
    df["spread"] = df[ticker_a] - df[ticker_b]
    df["spread_mean"] = df["spread"].rolling(LOOKBACK_BARS).mean()
    df["spread_std"] = df["spread"].rolling(LOOKBACK_BARS).std()
    df["z"] = (df["spread"] - df["spread_mean"]) / df["spread_std"]
    df["upper_band"] = df["spread_mean"] + ENTRY_SIGMA * df["spread_std"]
    df["lower_band"] = df["spread_mean"] - ENTRY_SIGMA * df["spread_std"]
    df["session_date"] = df.index.date
    return df


# ---- Backtest -------------------------------------------------------------
def backtest(df):
    cost_per_round_trip = (
        4 * SLIPPAGE_PER_SHARE * SHARES_PER_LEG + 4 * COMMISSION_PER_LEG
    )

    position = 0          # +1 long spread, -1 short spread, 0 flat
    entry_spread = 0.0
    entry_date = None
    bars_held = 0
    trades = []

    # Pre-compute "is last bar of session" flag: today's date != next bar's date
    sessions = df["session_date"].values
    is_last_bar = [False] * len(sessions)
    for i in range(len(sessions) - 1):
        if sessions[i] != sessions[i + 1]:
            is_last_bar[i] = True
    is_last_bar[-1] = True  # final bar overall

    for i, (ts, row) in enumerate(df.iterrows()):
        if pd.isna(row["z"]):
            continue
        z = row["z"]
        spread = row["spread"]
        last_bar = is_last_bar[i]

        if position != 0:
            bars_held += 1

            exit_reason = None
            if position == +1 and z >= EXIT_SIGMA:
                exit_reason = "mean"
            elif position == -1 and z <= EXIT_SIGMA:
                exit_reason = "mean"
            elif abs(z) >= STOP_SIGMA:
                exit_reason = "stop"
            elif bars_held >= MAX_HOLD_BARS:
                exit_reason = "max_hold"
            elif last_bar and not ALLOW_OVERNIGHT:
                exit_reason = "eod"

            if exit_reason:
                if position == +1:
                    gross = (spread - entry_spread) * SHARES_PER_LEG
                else:
                    gross = (entry_spread - spread) * SHARES_PER_LEG
                trades.append({
                    "entry_ts": entry_date,
                    "exit_ts": ts,
                    "side": "long_spread" if position == +1 else "short_spread",
                    "entry": entry_spread,
                    "exit": spread,
                    "gross": gross,
                    "net": gross - cost_per_round_trip,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                })
                position = 0
                bars_held = 0

        # Entry (allow same-bar entry on opposite side after exit)
        if position == 0 and not last_bar:  # don't open on last bar
            if z <= -ENTRY_SIGMA:
                position, entry_spread, entry_date, bars_held = +1, spread, ts, 0
            elif z >= +ENTRY_SIGMA:
                position, entry_spread, entry_date, bars_held = -1, spread, ts, 0

    return pd.DataFrame(trades)


# ---- Reporting ------------------------------------------------------------
def summary(label, trades, df):
    print(f"\n=== {label} -- {INTERVAL} bars "
          f"({df.index[0].date()} to {df.index[-1].date()}) ===")
    print(f"Lookback: {LOOKBACK_BARS} bars  |  "
          f"Entry: +/-{ENTRY_SIGMA}sig  |  Exit: {EXIT_SIGMA}sig  |  "
          f"Stop: +/-{STOP_SIGMA}sig  |  Max-hold: {MAX_HOLD_BARS} bars  |  "
          f"Overnight: {ALLOW_OVERNIGHT}")
    print(f"Spread: mean=${df['spread'].mean():.3f}  "
          f"stdev=${df['spread'].std():.3f}  "
          f"min=${df['spread'].min():.3f}  max=${df['spread'].max():.3f}")
    if trades.empty:
        print("\nNo trades.")
        return
    wins = (trades["net"] > 0).sum()
    print(f"\nTrades:      {len(trades)}  ({wins}W / {len(trades)-wins}L, "
          f"{wins/len(trades)*100:.0f}% WR)")
    print(f"Gross PnL:   ${trades['gross'].sum():>10,.2f}")
    print(f"Net PnL:     ${trades['net'].sum():>10,.2f}")
    print(f"Avg trade:   ${trades['net'].mean():>10,.2f}")
    print(f"Best:        ${trades['net'].max():>10,.2f}")
    print(f"Worst:       ${trades['net'].min():>10,.2f}")
    avg_hold_min = trades["bars_held"].mean() * 5
    print(f"Avg hold:    {avg_hold_min:.0f} min  "
          f"({trades['bars_held'].mean():.1f} bars)")
    # Exit reason breakdown
    rs = trades["exit_reason"].value_counts()
    print("Exit reasons:")
    for reason, count in rs.items():
        bucket = trades[trades["exit_reason"] == reason]
        print(f"  {reason:9s}  {count:3d}  net=${bucket['net'].sum():>9,.2f}  "
              f"avg=${bucket['net'].mean():>7,.2f}")


def plot(label, df, trades, outfile):
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(14, 10), sharex=True,
        gridspec_kw={"height_ratios": [3, 1.5, 1.5]},
    )

    ax1.plot(df.index, df["spread"], color="black", lw=0.5, label="Spread")
    ax1.plot(df.index, df["spread_mean"], color="steelblue", lw=0.8,
             label=f"{LOOKBACK_BARS}-bar mean")
    ax1.fill_between(df.index, df["lower_band"], df["upper_band"],
                     color="steelblue", alpha=0.12,
                     label=f"+/-{ENTRY_SIGMA}sig band")

    if not trades.empty:
        for _, t in trades.iterrows():
            color = "green" if t["net"] > 0 else "red"
            ax1.plot([t["entry_ts"], t["exit_ts"]],
                     [t["entry"], t["exit"]],
                     color=color, lw=0.8, alpha=0.5)
            ax1.scatter(t["entry_ts"], t["entry"],
                        color=color, s=10, marker="^", zorder=5)
            ax1.scatter(t["exit_ts"], t["exit"],
                        color=color, s=10, marker="v", zorder=5)

    ax1.set_ylabel("Spread ($)")
    ax1.set_title(f"{label} -- {INTERVAL} spread + trades")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.plot(df.index, df["z"], color="black", lw=0.4)
    ax2.axhline(+ENTRY_SIGMA, color="red", ls="--", lw=0.5)
    ax2.axhline(-ENTRY_SIGMA, color="red", ls="--", lw=0.5)
    ax2.axhline(+STOP_SIGMA, color="purple", ls=":", lw=0.5)
    ax2.axhline(-STOP_SIGMA, color="purple", ls=":", lw=0.5)
    ax2.axhline(0, color="gray", lw=0.5)
    ax2.set_ylabel("Z-score")
    ax2.grid(alpha=0.3)

    if not trades.empty:
        cum = trades.set_index("exit_ts")["net"].cumsum()
        ax3.plot(cum.index, cum.values, color="black", lw=1)
        ax3.fill_between(cum.index, 0, cum.values,
                         where=cum.values >= 0, color="green", alpha=0.2)
        ax3.fill_between(cum.index, 0, cum.values,
                         where=cum.values < 0, color="red", alpha=0.2)
    ax3.axhline(0, color="gray", lw=0.5)
    ax3.set_ylabel("Cum. Net PnL ($)")
    ax3.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(outfile, dpi=100)
    print(f"Chart saved: {outfile}")
    plt.close(fig)


# ---- Driver ---------------------------------------------------------------
def run_pair(ticker_a, ticker_b):
    df = fetch_pair(ticker_a, ticker_b)
    print(f"  {len(df)} bars ({df.index[0]} -> {df.index[-1]})")
    df = compute_spread_stats(df, ticker_a, ticker_b)
    trades = backtest(df)
    label = f"{ticker_a}/{ticker_b}"
    summary(label, trades, df)
    plot(label, df, trades,
         outfile=f"pair_backtest_{ticker_a}_{ticker_b}.png".lower())


if __name__ == "__main__":
    for a, b in PAIRS:
        run_pair(a, b)
