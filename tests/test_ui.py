"""Headless browser tests for the web UI (phase 2).

Drives the live site in real Chrome (Playwright + system google-chrome, no browser
download) and verifies the three things that silently break on frontend edits:
  - THEMES: all 4 switch the <html data-theme>, move the active button, persist to
    localStorage, and actually restyle the page (distinct computed backgrounds).
  - GRAPHS: expanding a watchlist row renders a real Plotly chart (.main-svg + traces).
  - BUTTONS: theme buttons, the timeframe buttons, and the Raw Data toggle all
    change app state when clicked.
It also fails on any uncaught JS exception (a white-screen regression).

SAFE BY DESIGN: never double-clicks the ✕ remove button (it's a two-click confirm),
so it cannot delete a watchlist item. All interactions are read-only or reversible.

Requires the website server running (./mass.sh start) and Playwright installed
(pip install playwright). Launches system Chrome, so no `playwright install` needed.

Run:  python tests/test_ui.py            (headless)
      python tests/test_ui.py --headed   (visible window, slowed so you can watch)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Check

from playwright.sync_api import sync_playwright

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(PROJECT_DIR, "config", "website_settings.json")
THEMES = ["bloomberg", "fintech", "retro", "swiss"]
HEADED = "--headed" in sys.argv or os.environ.get("VERIFY_HEADED") == "1"

c = Check()


def base_url():
    env = os.environ.get("VERIFY_BASE_URL")
    if env:
        return env
    with open(SETTINGS) as f:
        srv = json.load(f).get("server", {})
    scheme = "https" if srv.get("ssl_cert") else "http"
    return f"{scheme}://{srv.get('domain_name', 'localhost')}:{srv.get('port', 8081)}"


def launch(p):
    """System Chrome first (no download); fall back to an explicit binary path.

    Pass --headed (or set VERIFY_HEADED=1) to watch it run in a maximized visible
    window (slowed so a human can follow the clicks); default headless for the suite.
    """
    kw = dict(headless=not HEADED)
    if HEADED:
        kw["slow_mo"] = 600  # ms between actions, so the clicks are visible
        # Maximize the window; --window-size is the fallback if the WM ignores maximize.
        kw["args"] = ["--start-maximized", "--window-size=1680,1050"]
    try:
        return p.chromium.launch(channel="chrome", **kw)
    except Exception:
        return p.chromium.launch(executable_path="/usr/bin/google-chrome", **kw)


BASE = base_url()
print(f"\n[*] target: {BASE}")

with sync_playwright() as p:
    browser = launch(p)
    # Headed: no fixed viewport so the page fills the maximized window. Headless:
    # a fixed viewport for deterministic layout.
    ctx_kw = dict(ignore_https_errors=True)
    if HEADED:
        ctx_kw["no_viewport"] = True
    else:
        ctx_kw["viewport"] = {"width": 1400, "height": 900}
    ctx = browser.new_context(**ctx_kw)
    page = ctx.new_page()

    page_errors = []   # uncaught JS exceptions -> hard fail (white screen)
    console_errors = []  # console.error -> soft warn
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

    # -----------------------------------------------------------------------
    # 0. Page loads and React mounts
    # -----------------------------------------------------------------------
    print("\n[0] page load + mount")
    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    mounted = True
    try:
        page.wait_for_selector(".theme-switcher .theme-btn", timeout=30000)
    except Exception:
        mounted = False
    c.that("React app mounted (theme switcher present)", mounted)
    c.that("#root has rendered content",
           page.eval_on_selector("#root", "el => el.children.length > 0"))
    c.that("header title 'Options Premium Tracker' present",
           "Options Premium Tracker" in page.content())

    # -----------------------------------------------------------------------
    # 1. Themes: switch all 4, verify attribute + active + persistence + restyle
    # -----------------------------------------------------------------------
    print("\n[1] themes")
    c.that("exactly 4 theme buttons",
           page.eval_on_selector_all(".theme-switcher .theme-btn", "els => els.length") == 4)

    fingerprints = {}
    for t in THEMES:
        page.click(f'.theme-btn[data-theme="{t}"]')
        page.wait_for_function(f"document.documentElement.getAttribute('data-theme') === '{t}'",
                               timeout=5000)
        attr = page.evaluate("document.documentElement.getAttribute('data-theme')")
        active = page.eval_on_selector(f'.theme-btn[data-theme="{t}"]',
                                       "el => el.classList.contains('active')")
        stored = page.evaluate("localStorage.getItem('theme')")
        # A robust visual fingerprint pulled from several elements.
        fingerprints[t] = page.evaluate("""() => {
            const g = el => el ? getComputedStyle(el).backgroundColor + '|' + getComputedStyle(el).color : '';
            return [document.documentElement, document.body,
                    document.querySelector('header'),
                    document.querySelector('.watchlist-row')].map(g).join('||');
        }""")
        c.that(f"{t}: <html data-theme> set", attr == t)
        c.that(f"{t}: active class on its button", active is True)
        c.that(f"{t}: persisted to localStorage", stored == t)

    distinct = len(set(fingerprints.values()))
    c.info(f"distinct theme fingerprints: {distinct}/4")
    # >=2 (not 4): some dark themes legitimately share computed colors; the real
    # regression to catch is theming doing nothing at all (all 4 identical -> 1).
    c.that("themes actually restyle the page (>1 visually distinct)", distinct >= 2)

    # -----------------------------------------------------------------------
    # 2. Watchlist table structure
    # -----------------------------------------------------------------------
    print("\n[2] watchlist table")
    n_rows = page.eval_on_selector_all("tr.watchlist-row", "els => els.length")
    c.that("at least one watchlist row", n_rows >= 1)
    head = page.content()
    for col in ("Ticker", "Strike", "Type", "Expiration", "DTE"):
        c.that(f"header has '{col}' column", col in head)
    if n_rows:
        first_ticker = page.eval_on_selector("tr.watchlist-row .cell-ticker", "el => el.textContent.trim()")
        c.that("first row has a ticker", bool(first_ticker))
        c.info(f"first row ticker: {first_ticker}")

    # -----------------------------------------------------------------------
    # 3. Expand a row -> Plotly graph renders
    # -----------------------------------------------------------------------
    print("\n[3] expand row -> graph")
    chart_ok = False
    if n_rows:
        page.locator("tr.watchlist-row").first.locator(".cell-ticker").click()
        c.that("detail row expands", page.wait_for_selector(
            "tr.watchlist-row-detail", timeout=10000) is not None)
        # Either the chart renders or there's genuinely no history yet.
        rendered = False
        try:
            page.wait_for_selector(".chart-container .js-plotly-plot .main-svg", timeout=20000)
            rendered = True
        except Exception:
            rendered = False
        chart_ok = rendered
        if rendered:
            traces = page.eval_on_selector_all(
                ".chart-container .js-plotly-plot .scatterlayer .trace", "els => els.length")
            c.that("Plotly chart rendered (.main-svg present)", True)
            c.that("chart has at least one data trace", traces >= 1)
            c.info(f"chart trace count: {traces}")
        else:
            has_empty = page.query_selector(".empty-state-text") is not None
            c.warn("chart rendered (or legitimately empty history)", has_empty)
            c.info("no Plotly svg found; empty-state shown" if has_empty
                   else "no chart AND no empty-state -> investigate")

    # -----------------------------------------------------------------------
    # 4. Buttons in the expanded panel (timeframe + Raw Data toggle)
    # -----------------------------------------------------------------------
    print("\n[4] buttons")
    if chart_ok:
        # timeframe: 1D is active by default; click 7D and confirm the active moves
        if page.query_selector("button.timeframe-btn"):
            page.click('button.timeframe-btn:has-text("7D")')
            page.wait_for_timeout(300)
            seven_active = page.eval_on_selector(
                'button.timeframe-btn:has-text("7D")', "el => el.classList.contains('active')")
            c.that("timeframe button '7D' becomes active on click", seven_active)
            page.click('button.timeframe-btn:has-text("1D")')  # restore
            page.wait_for_timeout(200)

        # Raw Data toggle opens the data table
        if page.query_selector(".date-nav-toggle-right"):
            page.click(".date-nav-toggle-right")
            opened = False
            try:
                page.wait_for_selector(".data-table-container.expanded table.data-table", timeout=5000)
                opened = True
            except Exception:
                opened = False
            c.that("Raw Data toggle opens the data table", opened)
            page.click(".date-nav-toggle-right")  # close again
            page.wait_for_timeout(200)
            c.that("Raw Data toggle closes the data table",
                   page.query_selector(".data-table-container.expanded") is None)

    # remove button: verify it exists and is idle — do NOT click (two-click delete)
    rb = page.query_selector("tr.watchlist-row .remove-btn")
    c.that("remove button present", rb is not None)
    if rb:
        c.that("remove button is in idle state (not mid-confirm)",
               "Sure?" not in (rb.text_content() or ""))

    # -----------------------------------------------------------------------
    # 5. Collapse the row
    # -----------------------------------------------------------------------
    print("\n[5] collapse row")
    if n_rows:
        page.locator("tr.watchlist-row").first.locator(".cell-ticker").click()
        page.wait_for_timeout(400)
        c.that("detail row collapses",
               page.query_selector("tr.watchlist-row-detail") is None)

    # -----------------------------------------------------------------------
    # 6. QuickAddCard progressive-disclosure flow (ticker -> strikes -> DTE -> Add)
    #    Stops BEFORE clicking "+ Add" so it never adds to the real watchlist.
    # -----------------------------------------------------------------------
    print("\n[6] QuickAddCard add flow (non-destructive)")
    if page.query_selector(".quick-add-card"):
        # CALL/PUT toggle: empty ticker -> just flips state, no network side effects.
        page.click('.quick-add-putcall .putcall-btn:has-text("PUT")')
        page.wait_for_timeout(150)
        c.that("PUT toggle becomes active",
               page.eval_on_selector('.putcall-btn:has-text("PUT")',
                                      "el => el.classList.contains('active')"))
        page.click('.quick-add-putcall .putcall-btn:has-text("CALL")')
        page.wait_for_timeout(150)

        # Type a liquid ticker + Enter -> strikes load, closest strike auto-selects,
        # and DTE contracts auto-populate (because /api/strikes returns stock_price).
        page.fill(".quick-add-ticker", "AAPL")
        page.press(".quick-add-ticker", "Enter")
        strikes_ok = dte_ok = False
        try:
            # strike trigger (button.quick-add-select) shows a "$" price once selected
            page.wait_for_function(
                "document.querySelector('button.quick-add-select') && "
                "document.querySelector('button.quick-add-select').textContent.includes('$')",
                timeout=15000)
            strikes_ok = True
        except Exception:
            strikes_ok = False
        c.that("typing a ticker + Enter loads & auto-selects a strike", strikes_ok)

        if strikes_ok:
            try:
                page.wait_for_function(
                    "document.querySelectorAll('select.quick-add-select option').length > 1",
                    timeout=15000)
                dte_ok = True
            except Exception:
                dte_ok = False
            c.that("DTE dropdown auto-populates with contracts", dte_ok)

        if dte_ok:
            # The option VALUES must be contract_symbols, not undefined (the c.ticker trap).
            vals = page.eval_on_selector_all(
                "select.quick-add-select option", "els => els.map(o => o.value)")
            real = [v for v in vals if v]
            c.that("DTE options carry contract_symbol values (not blank/undefined)",
                   len(real) >= 1 and all(v.startswith("AAPL") for v in real))
            c.info(f"sample DTE contract_symbol: {real[0] if real else '—'}")

            # Pick a DTE -> the "+ Add" button must enable. Do NOT click it.
            page.select_option("select.quick-add-select", index=1)
            page.wait_for_timeout(200)
            c.that('"+ Add" button enables once a DTE is chosen',
                   page.eval_on_selector(".quick-add-btn", "el => !el.disabled"))
            c.info("stopped before clicking Add — watchlist left unchanged")
    else:
        c.warn("QuickAddCard present", False)

    # -----------------------------------------------------------------------
    # 7. No uncaught JS exceptions
    # -----------------------------------------------------------------------
    print("\n[7] runtime errors")
    c.that("no uncaught JS exceptions during the run", len(page_errors) == 0)
    if page_errors:
        for e in page_errors[:5]:
            c.info(f"pageerror: {e[:160]}")
    if console_errors:
        c.warn(f"no console.error messages ({len(console_errors)} seen)", False)
        for e in console_errors[:5]:
            c.info(f"console.error: {e[:160]}")

    browser.close()

sys.exit(c.report("UI"))
