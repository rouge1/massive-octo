# Options Premium Tracker

A real-time options premium tracking dashboard with WebSocket streaming and 4 switchable aesthetic themes.

## Features

- **Real-time streaming** - WebSocket updates every 30 seconds
- **Dual-axis charts** - Option premium and stock price overlaid with Plotly
- **Spread visualization** - Premium as % of stock price in separate subplot
- **Option data display** - Bid, ask, IV, volume, open interest
- **4 aesthetic themes**:
  - Bloomberg Terminal (dark, neon green)
  - Modern Fintech (purple gradients)
  - Retro-Futuristic (CRT scanlines, amber glow)
  - Minimal Swiss (brutalist black/white/red)
- **Theme persistence** - Saves preference to localStorage
- **No build step** - React via CDN, pure CSS themes

## Quick Start

### 1. Install dependencies

```bash
conda activate mass
cd backend
conda install -c conda-forge fastapi uvicorn websockets yfinance
```

### 2. Start the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. Start the frontend

```bash
cd frontend
python -m http.server 3000
```

### 4. Open the app

Navigate to http://localhost:3000

## Usage

1. Enter a ticker symbol (e.g., AAPL)
2. Select option type (call/put)
3. Click "Load Strikes" to fetch available strikes
4. Select a strike price
5. Click "Load Expirations" to fetch available contracts
6. Select an expiration date
7. Click "Start" to begin tracking

Use the theme buttons in the header to switch between visual styles.

## Tech Stack

**Backend:**
- FastAPI
- WebSockets
- yfinance

**Frontend:**
- React 18 (via CDN)
- Plotly.js
- Pure CSS with CSS variables

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/strikes/{ticker}/{put_call}` | Available strike prices |
| `GET /api/contracts/{ticker}/{strike}/{put_call}` | Available expirations |
| `GET /api/price/{ticker}` | Current stock price |
| `WS /ws/track` | Real-time streaming |
| `GET /docs` | OpenAPI documentation |

## License

MIT
