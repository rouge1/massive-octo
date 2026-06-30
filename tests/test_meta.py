"""Meta-test: proves the verify suite is NOT vacuous — that it actually goes RED
when the code or the live responses break, instead of passing by default.

For each scenario it injects a regression (or points the suite at a broken target)
and asserts the relevant tier turns RED (exit 1), while unmutated controls stay
GREEN (exit 0). If a real bug ever stops being caught, a META check here fails.

This is heavier than `./mass.sh verify` (it runs the suite ~10x, including the
browser), so it's a separate, occasional check rather than part of routine verify.

Run:  python tests/test_meta.py         (or ./mass.sh verify-meta)
"""
import json
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(TESTS_DIR)
LOGIC = os.path.join(TESTS_DIR, "test_schwab_logic.py")
API = os.path.join(TESTS_DIR, "test_api_smoke.py")
UI = os.path.join(TESTS_DIR, "test_ui.py")

results = []


def meta(name, rc, expected):
    ok = (rc == expected)
    results.append(ok)
    want = "RED" if expected == 1 else "GREEN"
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  (want {want}, got rc={rc})")


def run(path=None, code=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    cmd = [sys.executable, "-c", code] if code is not None else [sys.executable, path]
    return subprocess.run(cmd, cwd=PROJECT, env=e, capture_output=True, text=True).returncode


def inject(snippet, target):
    """Run the real test file under a mutated module/lib (injection runs first)."""
    return (
        "import sys, runpy\n"
        f"sys.path.insert(0, {PROJECT!r})\n"
        f"{snippet}\n"
        "try:\n"
        f"    runpy.run_path({target!r}, run_name='__main__')\n"
        "    rc = 0\n"
        "except SystemExit as e:\n"
        "    rc = e.code if isinstance(e.code, int) else 1\n"
        "sys.exit(rc)\n"
    )


def have_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


print("\n=== controls (must stay GREEN) ===")
meta("logic suite, unmutated", run(path=LOGIC), 0)
meta("API suite, unmutated", run(path=API), 0)

print("\n=== harness plumbing ===")
meta("Check.that(False) -> rc 1",
     run(code=f"import sys; sys.path.insert(0, {TESTS_DIR!r}); from _harness import Check; "
              "c=Check(); c.that('x', False); sys.exit(c.report('t'))"), 1)
meta("Check.warn(False) -> rc 0 (soft)",
     run(code=f"import sys; sys.path.insert(0, {TESTS_DIR!r}); from _harness import Check; "
              "c=Check(); c.warn('x', False); sys.exit(c.report('t'))"), 0)

print("\n=== logic mutations (each must turn the suite RED) ===")
meta("break invalid_grant classifier (the original token-spam bug)",
     run(code=inject("import apps.schwab_client as sc\n"
                     "sc._is_refresh_token_dead = lambda e: False", LOGIC)), 1)
meta("break symbol padding (identity)",
     run(code=inject("import apps.schwab_client as sc\n"
                     "sc._to_schwab_option_symbol = lambda s: s", LOGIC)), 1)
meta("break get_status revoked routing -> expired",
     run(code=inject("import apps.schwab_client as sc\n"
                     "_o = sc.get_status\n"
                     "sc.get_status = lambda: ('token_expired' if _o()=='token_revoked' else _o())",
                     LOGIC)), 1)

print("\n=== API mutations (each must turn the suite RED) ===")
meta("server unreachable (bad port)",
     run(path=API, env={"VERIFY_BASE_URL": "https://localhost:9099"}), 1)
meta("drop contract_symbol from /api/contracts (the field-mapping trap)",
     run(code=inject(
         "import requests\n"
         "_real = requests.get\n"
         "def fake(url, **kw):\n"
         "    r = _real(url, **kw)\n"
         "    if '/api/contracts/' in url:\n"
         "        d = r.json()\n"
         "        for c in d.get('contracts', []): c.pop('contract_symbol', None)\n"
         "        r.json = lambda: d\n"
         "    return r\n"
         "requests.get = fake", API)), 1)

print("\n=== UI mutations (each must turn the suite RED) ===")
if not have_playwright():
    print("  SKIP  playwright not installed — UI meta-checks skipped")
else:
    meta("UI: unreachable target (white-screen / server down)",
         run(path=UI, env={"VERIFY_BASE_URL": "https://localhost:9099"}), 1)

    # Theming sabotage: if <html data-theme> can't change, the UI suite must go RED.
    with open(os.path.join(PROJECT, "config", "website_settings.json")) as f:
        srv = json.load(f)["server"]
    url = (f"{'https' if srv.get('ssl_cert') else 'http'}://"
           f"{srv.get('domain_name', 'localhost')}:{srv.get('port')}")
    sabotage = (
        "import sys, json\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as pw:\n"
        "    try: b = pw.chromium.launch(channel='chrome', headless=True)\n"
        "    except Exception: b = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)\n"
        "    pg = b.new_context(ignore_https_errors=True).new_page()\n"
        "    pg.add_init_script(\"\"\"\n"
        "        const real = Element.prototype.setAttribute;\n"
        "        Element.prototype.setAttribute = function(n, v) {\n"
        "            if (n === 'data-theme' && this === document.documentElement) return;\n"
        "            return real.call(this, n, v);\n"
        "        };\n"
        "    \"\"\")\n"
        f"    pg.goto({url!r}, wait_until='domcontentloaded', timeout=30000)\n"
        "    pg.wait_for_selector('.theme-switcher .theme-btn', timeout=30000)\n"
        "    pg.click('.theme-btn[data-theme=\"swiss\"]')\n"
        "    pg.wait_for_timeout(500)\n"
        "    attr = pg.evaluate(\"document.documentElement.getAttribute('data-theme')\")\n"
        "    b.close()\n"
        "    sys.exit(1 if attr != 'swiss' else 0)\n"  # rc 1 == sabotage took effect (test WOULD fail)
    )
    meta("UI: broken theme switch -> data-theme assertion would FAIL",
         run(code=sabotage), 1)

print("\n" + ("META: ALL PASS — the suite catches regressions"
              if all(results) else f"META: {results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
