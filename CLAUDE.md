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
├── app.py                   # Legacy Streamlit dashboard (kept for reference)
├── api_client.py            # Legacy API client (kept for reference)
├── requirements.txt         # Legacy dependencies
└── CLAUDE.md                # This file
```

## Running the App

### Backend (FastAPI)
```bash
conda activate mass
cd /data/python/massive/backend
conda install -c conda-forge fastapi uvicorn websockets yfinance
uvicorn main:app --reload --port 8000
```

### Frontend (React via CDN)
```bash
cd /data/python/massive/frontend
python -m http.server 3000
```

Then open http://localhost:3000 in your browser.

## API Endpoints

### REST Endpoints
- `GET /api/strikes/{ticker}/{put_call}` - Get available strike prices
- `GET /api/contracts/{ticker}/{strike}/{put_call}` - Get available expirations
- `GET /api/price/{ticker}` - Get current stock price
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

### Frontend (via CDN)
- React 18
- Plotly.js 2.27
- Google Fonts (IBM Plex Mono, DM Sans, Space Grotesk, VT323, Share Tech Mono)

## Key Features
- Real-time WebSocket streaming (30s intervals)
- Dual y-axis chart: premium + stock price
- Spread % subplot
- Option greeks display (bid, ask, IV, volume, OI)
- Theme persistence via localStorage
- Responsive layout
- Keeps last 100 data points

## Implementation Status
- [x] FastAPI backend with REST endpoints
- [x] WebSocket streaming endpoint
- [x] React frontend with CDN setup
- [x] Plotly chart integration
- [x] 4 theme CSS files
- [x] Theme switcher with localStorage persistence
- [ ] Multi-contract watchlist
- [ ] Browser notifications for spread alerts
- [ ] Historical data persistence
- [ ] CSV export
- [ ] Mobile responsive improvements

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

## Legacy Streamlit App
The original Streamlit app is preserved in the root directory (`app.py`, `api_client.py`). To run:
```bash
streamlit run app.py
```
