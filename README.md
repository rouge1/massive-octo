# Options Premium Tracker

A real-time options watchlist dashboard with SSE streaming, MySQL persistence, and 4 switchable aesthetic themes. Two PyQt5 desktop apps share a MySQL database — one collects data, one serves the web UI.

## Features

- **Watchlist-only UI** — add options inline via QuickAddCard, monitor live premiums in a sortable table
- **Expandable rows** — click any row to reveal an inline Plotly chart + raw data table
- **Date navigation** — ←/→ step through historical days; chart x-axis pinned to market hours
- **SSE streaming** — live bid/ask/last updates every 30s (open) / 5min (closed)
- **4 aesthetic themes**: Bloomberg Terminal · Modern Fintech · Retro-Futuristic · Minimal Swiss
- **Theme persistence** — saves to localStorage
- **MySQL persistence** — watchlist and snapshots survive restarts
- **No build step** — React via CDN, pure CSS themes

## Setup

### 1. Create the conda environment

```bash
conda create -n mass python=3.11 -y
conda activate mass
pip install -r requirements.txt
```

### 2. Configure MySQL

Create a database (e.g. `options_database`) and a user with full access to it. You'll enter credentials in the PyQt5 GUI on first launch — they're saved for subsequent runs.

### 3. Run both apps

```bash
conda activate mass
cd /data/python/massive-octo

python options_watcher.py   # Data collector — polls yfinance, writes to MySQL
python website.py           # Web server panel — starts/stops FastAPI + React server
```

Or use the shell script:

```bash
./mass.sh start    # start both
./mass.sh status
./mass.sh stop
```

### 4. Open the app

Navigate to the URL shown in the website.py window (default **http://localhost:8081**).

## Usage

1. Type a ticker in the QuickAddCard and press **Enter** — strikes load
2. Select a strike — expirations load
3. Select an expiration — **+ Add** activates
4. Click **+ Add** — new row appears in the watchlist
5. Click any row to expand inline chart + data table
6. Use ←/→ in the Raw Data header to browse historical days
7. Click the theme buttons in the header to switch visual styles

## Tech Stack

**Backend:**
- FastAPI + SSE (Server-Sent Events)
- SQLAlchemy 2.x + PyMySQL (MySQL)
- yfinance (market data)
- PyQt5 (desktop control panels)

**Frontend:**
- React 18 (via CDN, no build step)
- Plotly.js
- Pure CSS with CSS variables (4 themes)

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/strikes/{ticker}/{put_call}` | Available strike prices |
| `GET /api/contracts/{ticker}/{strike}/{put_call}` | Available expirations |
| `GET /api/price/{ticker}` | Current stock price |
| `GET /api/market/status` | Market open/closed/pre/after-hours |
| `GET /api/watchlist` | All watchlist items |
| `POST /api/watchlist` | Add item to watchlist |
| `DELETE /api/watchlist/{item_id}` | Remove item |
| `GET /api/watchlist/{item_id}/snapshot` | Current live snapshot |
| `GET /api/snapshots/{watchlist_id}?limit=N` | Full snapshot history |
| `GET /sse/watchlist` | SSE stream: watchlist-level updates |
| `GET /sse/option/{watchlist_id}` | SSE stream: per-option snapshots |
| `GET /docs` | OpenAPI documentation |
