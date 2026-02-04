# Options Premium Tracker

## Project Overview
A real-time options premium tracking dashboard built with FastAPI (backend) and React (frontend). Features WebSocket streaming, 4 switchable aesthetic themes, and interactive Plotly charts. Polls every 30 seconds.

## Environment Setup
```bash
conda activate mass
```

## File Structure
```
/data/python/massive/
├── backend/
│   ├── main.py              # FastAPI app with REST & WebSocket endpoints
│   ├── api_client.py        # yfinance wrapper functions
│   └── requirements.txt     # Backend dependencies
├── frontend/
│   ├── index.html           # Single HTML entry point with CDN imports
│   ├── app.js               # React application (no build step)
│   └── styles/
│       ├── base.css         # Shared layout, reset, components
│       ├── theme-bloomberg.css  # Bloomberg Terminal dark theme
│       ├── theme-fintech.css    # Modern fintech theme
│       ├── theme-retro.css      # Retro-futuristic CRT theme
│       └── theme-swiss.css      # Minimal Swiss/brutalist theme
├── config/                  # Runtime files (gitignored)
│   ├── backend.pid          # Backend process ID
│   ├── frontend.pid         # Frontend process ID
│   ├── backend.log          # Backend output log
│   └── frontend.log         # Frontend output log
├── data/                    # Persisted snapshot data (gitignored)
│   └── {TICKER}_{STRIKE}_{PUTCALL}_{YYYY-MM-DD}.json  # Per-contract per-day history
├── migrate_data.py          # One-time migration script for legacy data
├── mass.sh                  # Start/stop/status script
├── app.py                   # Legacy Streamlit dashboard (kept for reference)
├── api_client.py            # Legacy API client (kept for reference)
├── requirements.txt         # Legacy dependencies
└── CLAUDE.md                # This file
```

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
- Real-time WebSocket streaming (30s intervals when market open, 5min when closed)
- Market status detection (open/pre-market/after-hours/weekend)
- Dual y-axis chart: premium + stock price
- Option greeks display (bid, ask, IV, volume, OI)
- Theme persistence via localStorage
- Form state persistence (ticker, strike, contract survive refresh)
- Data persistence (snapshots saved to JSON files, survives restart)
- Toggleable sidebar (fixed overlay, auto-hides when tracking starts)
- Raw Data table expands as overlay with scrollable content
- Metrics grid layout (5-col design with bid/ask and last price history)
- Trend arrows on price history (up/down indicators)
- Responsive layout
- Unlimited snapshots per day in persistent storage (date-partitioned files)
- Day navigator to browse historical data

## Implementation Status
- [x] FastAPI backend with REST endpoints
- [x] WebSocket streaming endpoint
- [x] React frontend with CDN setup
- [x] Plotly chart integration
- [x] 4 theme CSS files
- [x] Theme switcher with localStorage persistence
- [x] Form state persistence (ticker, strike, contract restored on refresh)
- [x] Toggleable sidebar overlay with auto-hide on tracking
- [x] Raw Data table as expandable overlay with scroll
- [x] Market status detection (open/closed/pre-market/after-hours)
- [x] Historical data persistence (JSON files)
- [ ] Multi-contract watchlist
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

## Legacy Streamlit App
The original Streamlit app is preserved in the root directory (`app.py`, `api_client.py`). To run:
```bash
streamlit run app.py
```
