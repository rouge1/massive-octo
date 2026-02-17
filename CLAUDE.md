# Options Premium Tracker

## Project Overview
A real-time options premium tracking dashboard built with FastAPI (backend) and React (frontend). Features SSE streaming, 4 switchable aesthetic themes, and interactive Plotly charts. The watchlist is the only view — add options via the inline QuickAddCard, monitor live premiums in a sortable table.

## Environment Setup
```bash
conda activate mass
```

## Two Entry Points — Run Both

The system has two separate PyQt5 desktop apps that share the same MySQL database:

| Entry point | What it does | Run it when |
|---|---|---|
| `python options_watcher.py` | **Data collector** — polls yfinance every 30s (open) / 5min (closed), writes snapshots to MySQL | Always — this feeds the database |
| `python website.py` | **Web server panel** — starts/stops the FastAPI + React server; users browse the web UI | When you want browser access |

Both must be running for the full live experience. The watcher writes; the server reads and streams.

> ⚠️ `website_ui.py` window title still says "Audio Transcription Website Server" — leftover from when this codebase was ported from an audio project. The functionality is correct; only the title is stale.

## File Structure
```
/data/python/massive-octo/
├── options_watcher.py       # Entry point: background yfinance polling daemon
├── website.py               # Entry point: PyQt5 control panel for FastAPI server
├── apps/
│   ├── database.py          # SQLAlchemy ORM models + DatabaseManager class
│   ├── options_timer.py     # OptionsTimer: async polling loop (drives watcher)
│   ├── options_server.py    # OptionsServer: FastAPI app (REST + SSE)
│   ├── options_api.py       # yfinance wrapper: strikes, contracts, snapshots
│   ├── app_ui.py            # PyQt5 GUI for options_watcher.py
│   ├── website_ui.py        # PyQt5 GUI for website.py
│   ├── gui_methods.py       # Shared GUI utilities, settings helpers, SignalHandler
│   ├── theme.py             # apply_dark_theme() for PyQt5 windows
│   └── audio*.py            # Audio subsystem (separate concern)
├── frontend/
│   ├── index.html           # Single HTML entry point with CDN imports
│   ├── app.js               # React application (no build step)
│   └── styles/
│       ├── base.css         # Shared layout, reset, components
│       ├── theme-bloomberg.css
│       ├── theme-fintech.css
│       ├── theme-retro.css
│       └── theme-swiss.css
├── mass.sh                  # Start/stop/status script (legacy backend/)
└── CLAUDE.md                # This file
```

## Database Tables

MySQL database (default name: `options_database`). Schema managed by SQLAlchemy ORM in `apps/database.py`.

```
users
├── id, first_name, last_name, email (unique), phone_number
├── website_url          # unique token for user's personal URL
├── password_hash        # bcrypt hash — never store plaintext
├── created_at, is_active

options_watchlist
├── id, user_id (FK → users)
├── ticker, strike, put_call, expiration
├── contract_symbol      # e.g. "AAPL260417C00165000" — this is the canonical ID
├── added_at, is_active, notes

option_snapshots
├── id, watchlist_id (FK → options_watchlist)
├── timestamp
├── stock_price
├── bid, ask, mid, last_price
├── volume, open_interest
├── implied_volatility, spread_pct

alerts
├── id, user_id (FK), watchlist_id (FK, nullable)
├── alert_type           # 'price_above', 'price_below', 'spread_threshold', 'iv_change'
├── threshold_value, comparison  # 'above' / 'below' / 'equals'
├── name, description, is_active, is_triggered
├── notify_email, notify_sms, notify_browser
└── created_at, last_checked, triggered_at, last_notified
```

**Important:** `_verify_schema()` is read-only — it logs warnings for missing columns but never alters the DB. To fix schema drift, drop and recreate tables via `db_manager.drop_all_tables()` then `db_manager.init_db()`.

## Running the App

### Quick Start (Recommended)
```bash
conda activate mass
cd /data/python/massive
./mass.sh start      # Start both backend and frontend
./mass.sh status     # Check if services are running
./mass.sh stop       # Stop both services
```

Then open http://localhost:3000 in your browser.

### Manual Start
**Backend (FastAPI):**
```bash
conda activate mass
cd /data/python/massive/backend
uvicorn main:app --reload --port 8000
```

**Frontend (React via CDN):**
```bash
cd /data/python/massive/frontend
python -m http.server 3000
```

### First-Time Setup
```bash
conda activate mass
conda install -c conda-forge fastapi uvicorn websockets yfinance pytz
```

## Seeing Changes After Edits

| Change Type | How to See It |
|-------------|---------------|
| Frontend (JS/CSS/HTML) | Hard refresh browser: `Ctrl + Shift + R` |
| Backend (Python) | Auto-reloads (uvicorn `--reload` flag) |
| mass.sh script | Run `./mass.sh stop && ./mass.sh start` |

**Note:** Regular refresh (`F5` or `Ctrl + R`) may serve cached files. Always use hard refresh for frontend changes.

## API Endpoints

### REST Endpoints
- `GET /api/strikes/{ticker}/{put_call}` - Get available strike prices
- `GET /api/contracts/{ticker}/{strike}/{put_call}` - Get available expirations
- `GET /api/price/{ticker}` - Get current stock price
- `GET /api/market/status` - Check if market is open/closed
- `POST /api/data/save` - Save a snapshot to date-specific persistent storage
- `GET /api/data/load/{ticker}/{strike}/{put_call}?date=YYYY-MM-DD` - Load saved snapshots (defaults to today)
- `GET /api/data/dates/{ticker}/{strike}/{put_call}` - Get list of available dates (newest first)
- `DELETE /api/data/clear/{ticker}/{strike}/{put_call}?date=YYYY-MM-DD` - Clear saved data (specific date or all)
- `GET /api/watchlist` - Get all watchlist items
- `POST /api/watchlist` - Add an item to the watchlist
- `DELETE /api/watchlist/{item_id}` - Remove an item from the watchlist
- `GET /api/watchlist/{item_id}/snapshot` - Get current snapshot for a watchlist item
- `GET /docs` - OpenAPI documentation

### WebSocket Endpoint
- `WS /ws/track` - Real-time streaming

**Client sends:**
```json
{
    "action": "start",
    "ticker": "AAPL",
    "contract": "AAPL240315C00200000",
    "expiration": "2024-03-15",
    "strike": 200.0,
    "put_call": "call"
}
```

**Server pushes every 30s:**
```json
{
    "type": "snapshot",
    "timestamp": "2024-01-15T10:30:00",
    "premium": 5.25,
    "stock_price": 185.50,
    "spread_pct": 2.83,
    "option_data": {
        "bid": 5.20,
        "ask": 5.30,
        "mid": 5.25,
        "last": 5.22,
        "volume": 1500,
        "open_interest": 12000,
        "iv": 0.25
    }
}
```

## Themes

Four switchable themes accessible via the header:

1. **Bloomberg Terminal** - Pure black, neon green accents, high density
2. **Modern Fintech** - Dark purple gradients, smooth animations
3. **Retro-Futuristic** - CRT scanlines, amber/green phosphor glow
4. **Minimal Swiss** - Stark white/black, red accent, brutalist precision

Theme preference is persisted in localStorage.

## Watchlist Feature

The watchlist is the only view. Options are added inline via the QuickAddCard at the top of the page.

### QuickAddCard (progressive disclosure)
Single horizontal row: `[ TICKER ] [ CALL | PUT ] [ Strike ▾ ] [ DTE ▾ ] [ + Add ]`
- Type a ticker → press **Enter** → strike dropdown populates
- Select a strike → DTE dropdown populates automatically
- Select a DTE → "+ Add" activates
- On success: row resets to idle, new watchlist row animates in

### Watchlist Table
- **Columns**: Ticker, Strike, Type, Expiration, DTE, Last, Bid, Ask, Remove
- **Auto-refresh**: each row re-fetches live snapshot every 60 seconds
- **Sortable**: click column headers (Ticker, Strike, Type, Expiration, DTE)
- **Remove**: click ✕ button on any row

### Watchlist Storage
- Stored in `/data/watchlist.json`
- Persists across server restarts
- Each item has unique ID, ticker, strike, type, expiration, contract_symbol, and timestamp

## Testing Parameters
- Ticker: AAPL
- Strike: 200
- Type: call

## Dependencies

### Backend
- fastapi
- uvicorn[standard]
- websockets
- yfinance
- pytz (timezone handling for market hours)

### Frontend (via CDN)
- React 18
- Plotly.js 2.27
- Google Fonts (IBM Plex Mono, DM Sans, Space Grotesk, VT323, Share Tech Mono)

## Key Features
- **Watchlist-only UI** — single view, no tab switching
- **QuickAddCard** — inline progressive-disclosure form: ticker → strike → DTE → Add
- Market status indicator (open/pre-market/after-hours/weekend) in header
- Sortable watchlist table with live bid/ask/last per row
- Row entrance animation (spring cubic-bezier, fires only on mount)
- Theme switcher in header (4 themes, persisted in localStorage)
- Watchlist persistence (stored in `/data/watchlist.json`, survives restart)

## Implementation Status
- [x] FastAPI backend with REST endpoints
- [x] SSE streaming (watchlist updates + per-option snapshots)
- [x] React frontend with CDN setup (no build step)
- [x] 4 theme CSS files + theme switcher with localStorage persistence
- [x] Market status detection (open/closed/pre-market/after-hours)
- [x] Watchlist CRUD endpoints
- [x] QuickAddCard inline add flow (progressive disclosure)
- [x] Row entrance animation (spring cubic-bezier)
- [x] Watchlist persistence (JSON file)
- [ ] Browser notifications for spread alerts
- [ ] CSV export

## Common Pitfalls & Solutions

### yfinance + JSON Serialization
yfinance returns numpy types (`int64`, `float64`) that aren't JSON serializable. Always convert before sending over WebSocket:
```python
def to_native(val):
    if val is None:
        return None
    try:
        return val.item()  # numpy -> Python native
    except (AttributeError, ValueError):
        return val
```

### Dropdown Styling Across Themes
Browser `<option>` elements ignore parent CSS. Must explicitly style:
```css
[data-theme="mytheme"] .form-select option {
    background: var(--bg-card);
    color: var(--text-primary);
}
```

### Plotly Chart Theming
Plotly tooltips need explicit `hoverlabel` config per theme:
```javascript
hoverlabel: { bgcolor: '#111111', font: { color: '#ffffff' } }
```

### Responsive Design
Never use `display: none` on critical UI (sidebar). Reflow layout instead:
```css
@media (max-width: 1024px) {
    .sidebar {
        border-bottom: 1px solid var(--border-color);
        max-height: 400px;
    }
}
```

### Overlay Pattern for Expandable Panels
To make a component expand as an overlay covering its sibling (e.g., data table covering chart):

1. Wrap siblings in a relative container:
```css
.wrapper {
    position: relative;
    flex: 1;
}
```

2. Use absolute positioning when expanded:
```css
.panel.expanded {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 10;
    display: flex;
    flex-direction: column;
}

.panel.expanded .scrollable-content {
    flex: 1;
    overflow-y: auto;
}
```

3. Toggle class in React:
```javascript
<div className={`panel ${isOpen ? 'expanded' : ''}`}>
```

### localStorage Restore with useEffect Race Condition
When restoring state from localStorage on mount, a save `useEffect` can overwrite saved data before restoration completes:

**Problem:**
```javascript
// This runs immediately on mount with null values, wiping saved state
useEffect(() => {
    saveFormState({ ticker, strike: selectedStrike }); // selectedStrike is null!
}, [ticker, selectedStrike]);
```

**Solution:** Skip the first render using a ref:
```javascript
const hasMountedRef = useRef(false);
useEffect(() => {
    if (!hasMountedRef.current) {
        hasMountedRef.current = true;
        return; // Skip first render
    }
    saveFormState({ ticker, strike: selectedStrike });
}, [ticker, selectedStrike]);
```

### localStorage Keys
The app uses these localStorage keys:
- `theme` - Selected theme name (bloomberg, fintech, retro, swiss)
- `optionsTrackerFormState` - Form state JSON (ticker, putCall, strike, contract)

### Fixed Overlay Sidebar Pattern
For a sidebar that overlays content instead of taking grid space:
```css
.sidebar {
    position: fixed;
    top: 60px;      /* Below header */
    left: 0;
    bottom: 0;
    width: 320px;
    z-index: 100;
    box-shadow: var(--shadow-lg);
}
```
Control visibility with conditional rendering (`if (!visible) return null;`) rather than CSS display property.

### Hard-Coded Colors for Semantic Meaning
Theme CSS variables may not cascade properly to all elements (especially nested grids, dynamically created elements). For colors with strong semantic meaning (green=positive, red=negative), use hard-coded hex values with `!important`:
```css
.metric-delta.positive {
    color: #00dd00 !important;  /* Always green */
}
.metric-delta.negative {
    color: #ff3333 !important;  /* Always red */
}
```
This ensures consistent meaning across all four themes without relying on `--accent-success`/`--accent-danger` variables.

### Market Hours API with pytz
When checking US market hours, always use `pytz` for proper timezone handling:
```python
import pytz
from datetime import datetime, time

et_tz = pytz.timezone('US/Eastern')
now_et = datetime.now(et_tz)

market_open = time(9, 30)   # 9:30 AM ET
market_close = time(16, 0)  # 4:00 PM ET
is_weekday = now_et.weekday() < 5

is_open = is_weekday and market_open <= now_et.time() < market_close
```
Note: This doesn't account for market holidays. Consider using a calendar API for production.

### Data Persistence File Naming
Data is stored in date-partitioned files for each contract:
```python
filename = f"{ticker.upper()}_{strike}_{put_call}_{for_date.isoformat()}.json"
# Examples: AAPL_200_call_2026-02-04.json, MSTR_100_put_2026-02-03.json
```
Format strike as int if it's a whole number to avoid `.0` in filenames.

### Migrating Legacy Data
If you have legacy files without dates in the filename, run the migration script:
```bash
python migrate_data.py
```
This groups snapshots by date, creates new date-specific files, and renames legacy files to `.json.bak`.

### WebSocket Polling Rate Based on Market Status
Adjust polling intervals based on market hours to reduce unnecessary API calls:
```python
if not market_status["is_open"]:
    await asyncio.sleep(300)  # 5 minutes when closed
else:
    await asyncio.sleep(30)   # 30 seconds when open
```

### API Returns `contract_symbol`, Not `ticker`
`GET /api/contracts/{ticker}/{strike}/{put_call}` returns objects with a `contract_symbol` field (e.g. `"AAPL260417C00165000"`). An older bug used `c.ticker` instead, which silently returned `undefined` and broke the DTE dropdown. Always use `c.contract_symbol`:
```javascript
// dropdown value / key
value={selectedContract ? selectedContract.contract_symbol : ''}
onChange={e => {
    const c = contracts.find(c => c.contract_symbol === e.target.value);
    setSelectedContract(c);
}}

// POST body
body: JSON.stringify({ contract_symbol: contract.contract_symbol, ... })
```

### Flex Selects That Don't Resize When Options Load
HTML `<select>` elements use the widest `<option>` text as their intrinsic min-content width. In a flex row, adding options via JS re-triggers size calculation and shifts surrounding elements.

**Fix:** set `flex-basis: 0` so the browser starts from zero and distributes space without consulting content:
```css
.stable-select {
    flex: 1 1 0px;  /* flex-basis: 0 — ignores option text width entirely */
    width: 0;       /* belt-and-suspenders for older Safari */
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}
```
Both selects grow equally from 0 to fill available space. Populating `<option>` elements cannot influence the layout.

### QuickAddCard Progressive Disclosure Pattern
When building a multi-step inline form where each step unlocks the next, use a single `status` string as a state machine rather than multiple booleans:
```javascript
// States: idle | loading-strikes | strikes | loading-contracts | contracts | adding
const [status, setStatus] = useState('idle');
const isLoading = status === 'loading-strikes' || status === 'loading-contracts' || status === 'adding';

// Fields are disabled based on state, not boolean flags
disabled={isLoading || strikes.length === 0}   // strike select
disabled={isLoading || contracts.length === 0}  // DTE select
disabled={isLoading || !selectedContract}        // Add button
```
On success: reset all state to idle and call `onAdded()` so parent re-fetches. On error: revert to the previous stable state (e.g. `'contracts'`), keeping user's selections intact.

### Instance-per-Application DatabaseManager
Never use a singleton or shared `DatabaseManager`. Each entry-point creates its own:
```python
# In options_watcher.py
db_manager = db.DatabaseManager()

# In website.py
db_manager = db.DatabaseManager()   # completely separate connection
```
This allows different MySQL credentials per app, isolated sessions, and independent connect/disconnect lifecycles. Pass `db_manager` as a parameter to any function that needs DB access.

### PyQt5 + asyncio Threading Pattern
To run async code in a `QThread`, create a fresh event loop inside `run()`:
```python
class BackgroundWorker(QThread):
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_main())
        finally:
            loop.close()
```
Never share an event loop across threads. Each `QThread` that needs async must create its own.

### Uvicorn Graceful Shutdown from a Thread
When running uvicorn inside a non-main thread (as in `website.py`), use a `threading.Event` to signal shutdown:
```python
shutdown_event = threading.Event()

async def run_with_shutdown_check():
    task = asyncio.create_task(server.serve())
    while not task.done() and not shutdown_event.is_set():
        await asyncio.sleep(0.1)
    if shutdown_event.is_set():
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5.0)

# To stop: shutdown_event.set(); thread.join(timeout=10)
```
`server.should_exit = True` is the correct uvicorn kill switch; do not use `SIGINT` from a thread.

### SignalHandler Cleanup at Exit
`gm.SignalHandler` bridges Python logging → PyQt5 `pyqtSignal`. It must be removed from all loggers before app exit or Python's logging shutdown will attempt to write to a deleted Qt object, raising `RuntimeError`. Always register cleanup:
```python
atexit.register(cleanup_logger_handlers)
app.aboutToQuit.connect(cleanup_logger_handlers)
```
And set `signal_handler.flushOnClose = False` to prevent a double-close crash.

### `contract_symbol` Is the Canonical Option ID
Throughout the codebase, `contract_symbol` (e.g. `"AAPL260417C00165000"`) is the unique identifier for an options contract. The field name `ticker` on a contract object refers to something different. Any code that uses `c.ticker` when it means the contract symbol will silently get `undefined`/`None` and break downstream logic (dropdown population, POST bodies, DB writes).

