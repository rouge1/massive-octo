"""
FastAPI backend for Options Premium Tracker.
Provides REST endpoints for contract discovery and WebSocket for real-time streaming.
"""

import asyncio
import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Data storage directory
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Watchlist storage
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

from api_client import (
    list_available_strikes,
    list_available_contracts,
    get_stock_price,
    fetch_snapshot,
    is_market_open,
)

app = FastAPI(
    title="Options Premium Tracker API",
    description="Real-time options premium tracking with WebSocket streaming",
    version="2.0.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Response models
class StrikesResponse(BaseModel):
    ticker: str
    put_call: str
    strikes: list[float]
    stock_price: float


class ContractInfo(BaseModel):
    ticker: str
    expiration: str
    dte: int


class ContractsResponse(BaseModel):
    ticker: str
    strike: float
    put_call: str
    contracts: list[ContractInfo]


class PriceResponse(BaseModel):
    ticker: str
    price: float
    timestamp: str


class OptionData(BaseModel):
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    iv: Optional[float]


class SnapshotResponse(BaseModel):
    timestamp: str
    premium: float
    stock_price: float
    spread_pct: float
    option_data: OptionData


# Watchlist models
class WatchlistItem(BaseModel):
    id: str
    ticker: str
    strike: float
    put_call: str
    expiration: str
    contract: str
    added_at: str


class WatchlistAddRequest(BaseModel):
    ticker: str
    strike: float
    put_call: str
    expiration: str
    contract: str


# REST Endpoints
@app.get("/api/strikes/{ticker}/{put_call}", response_model=StrikesResponse)
async def get_strikes(ticker: str, put_call: str):
    """Get available strike prices for a ticker and option type."""
    ticker = ticker.upper()
    strikes = list_available_strikes(ticker, put_call)
    stock_price = get_stock_price(ticker)
    return StrikesResponse(
        ticker=ticker,
        put_call=put_call,
        strikes=strikes,
        stock_price=stock_price,
    )


@app.get("/api/contracts/{ticker}/{strike}/{put_call}", response_model=ContractsResponse)
async def get_contracts(ticker: str, strike: float, put_call: str):
    """Get available contracts for a given ticker, strike, and type."""
    ticker = ticker.upper()
    contracts = list_available_contracts(ticker, strike, put_call)
    return ContractsResponse(
        ticker=ticker,
        strike=strike,
        put_call=put_call,
        contracts=[ContractInfo(**c) for c in contracts],
    )


@app.get("/api/price/{ticker}", response_model=PriceResponse)
async def get_price(ticker: str):
    """Get current stock price."""
    ticker = ticker.upper()
    price = get_stock_price(ticker)
    return PriceResponse(
        ticker=ticker,
        price=price,
        timestamp=datetime.now().isoformat(),
    )


@app.get("/api/market/status")
async def get_market_status():
    """Get current market status (open/closed)."""
    return is_market_open()


# Data Persistence Endpoints
def get_data_file(ticker: str, strike: float, put_call: str, for_date: date = None) -> Path:
    """Get the data file path for a contract on a specific date."""
    if for_date is None:
        for_date = date.today()
    # Format strike as int if it's a whole number, otherwise use float
    strike_str = str(int(strike)) if strike == int(strike) else str(strike)
    filename = f"{ticker.upper()}_{strike_str}_{put_call}_{for_date.isoformat()}.json"
    return DATA_DIR / filename


def get_contract_pattern(ticker: str, strike: float, put_call: str) -> str:
    """Get regex pattern to match all date files for a contract."""
    strike_str = str(int(strike)) if strike == int(strike) else str(strike)
    return f"^{ticker.upper()}_{strike_str}_{put_call}_\\d{{4}}-\\d{{2}}-\\d{{2}}\\.json$"


@app.post("/api/data/save")
async def save_snapshot(snapshot: dict):
    """Save a snapshot to the date-specific data file."""
    ticker = snapshot.get("ticker", "").upper()
    strike = snapshot.get("strike", 0)
    put_call = snapshot.get("put_call", "call")

    # Extract date from snapshot timestamp
    timestamp_str = snapshot.get("timestamp", "")
    try:
        snapshot_date = datetime.fromisoformat(timestamp_str).date()
    except (ValueError, TypeError):
        snapshot_date = date.today()

    data_file = get_data_file(ticker, strike, put_call, snapshot_date)

    # Load existing data or start fresh
    if data_file.exists():
        with open(data_file, "r") as f:
            data = json.load(f)
    else:
        data = {
            "ticker": ticker,
            "strike": strike,
            "put_call": put_call,
            "date": snapshot_date.isoformat(),
            "snapshots": []
        }

    # Add new snapshot (exclude meta fields)
    snapshot_data = {k: v for k, v in snapshot.items() if k not in ("ticker", "strike", "put_call")}
    data["snapshots"].append(snapshot_data)

    # No limit - store all snapshots for the day

    # Save
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)

    return {"status": "saved", "count": len(data["snapshots"]), "date": snapshot_date.isoformat()}


@app.get("/api/data/load/{ticker}/{strike}/{put_call}")
async def load_data(ticker: str, strike: float, put_call: str, date_str: Optional[str] = Query(None, alias="date")):
    """Load saved data for a contract on a specific date."""
    # Parse date or default to today
    if date_str:
        try:
            for_date = date.fromisoformat(date_str)
        except ValueError:
            for_date = date.today()
    else:
        for_date = date.today()

    data_file = get_data_file(ticker, strike, put_call, for_date)

    if not data_file.exists():
        return {
            "ticker": ticker.upper(),
            "strike": strike,
            "put_call": put_call,
            "date": for_date.isoformat(),
            "snapshots": []
        }

    with open(data_file, "r") as f:
        data = json.load(f)
        # Ensure date field is present
        data["date"] = for_date.isoformat()
        return data


@app.get("/api/data/dates/{ticker}/{strike}/{put_call}")
async def get_available_dates(ticker: str, strike: float, put_call: str):
    """Get list of available dates for a contract (newest first)."""
    pattern = get_contract_pattern(ticker, strike, put_call)
    regex = re.compile(pattern)

    dates = []
    for file in DATA_DIR.iterdir():
        if file.is_file() and regex.match(file.name):
            # Extract date from filename: TICKER_STRIKE_PUTCALL_YYYY-MM-DD.json
            date_str = file.stem.split("_")[-1]
            try:
                dates.append(date_str)
            except ValueError:
                continue

    # Sort dates newest first
    dates.sort(reverse=True)

    return {
        "ticker": ticker.upper(),
        "strike": strike,
        "put_call": put_call,
        "dates": dates
    }


@app.delete("/api/data/clear/{ticker}/{strike}/{put_call}")
async def clear_data(ticker: str, strike: float, put_call: str, date_str: Optional[str] = Query(None, alias="date")):
    """Clear saved data for a contract. If date provided, clear only that day; otherwise clear all days."""
    if date_str:
        # Clear specific date
        try:
            for_date = date.fromisoformat(date_str)
        except ValueError:
            return {"status": "invalid_date"}

        data_file = get_data_file(ticker, strike, put_call, for_date)
        if data_file.exists():
            data_file.unlink()
            return {"status": "cleared", "date": for_date.isoformat()}
        return {"status": "not_found", "date": for_date.isoformat()}
    else:
        # Clear all dates for this contract
        pattern = get_contract_pattern(ticker, strike, put_call)
        regex = re.compile(pattern)

        deleted_count = 0
        for file in list(DATA_DIR.iterdir()):
            if file.is_file() and regex.match(file.name):
                file.unlink()
                deleted_count += 1

        if deleted_count > 0:
            return {"status": "cleared", "deleted_files": deleted_count}
        return {"status": "not_found"}


# Watchlist Endpoints
def load_watchlist() -> list[dict]:
    """Load watchlist from file."""
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_watchlist(items: list[dict]):
    """Save watchlist to file."""
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(items, f, indent=2)
    except IOError as e:
        raise Exception(f"Failed to save watchlist: {e}")


@app.get("/api/watchlist")
async def get_watchlist():
    """Get all watchlist items."""
    items = load_watchlist()
    return {"items": items}


@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistAddRequest):
    """Add an item to the watchlist."""
    items = load_watchlist()
    
    # Generate unique ID
    import uuid
    new_item = {
        "id": str(uuid.uuid4()),
        "ticker": item.ticker.upper(),
        "strike": item.strike,
        "put_call": item.put_call,
        "expiration": item.expiration,
        "contract": item.contract,
        "added_at": datetime.now().isoformat()
    }
    
    items.append(new_item)
    save_watchlist(items)
    
    return {"status": "added", "item": new_item}


@app.delete("/api/watchlist/{item_id}")
async def remove_from_watchlist(item_id: str):
    """Remove an item from the watchlist."""
    items = load_watchlist()
    original_count = len(items)
    
    items = [item for item in items if item["id"] != item_id]
    
    if len(items) < original_count:
        save_watchlist(items)
        return {"status": "removed"}
    else:
        return {"status": "not_found"}


@app.get("/api/watchlist/{item_id}/snapshot")
async def get_watchlist_snapshot(item_id: str):
    """Get current snapshot for a watchlist item."""
    items = load_watchlist()
    item = next((i for i in items if i["id"] == item_id), None)
    
    if not item:
        return {"error": "Item not found"}
    
    try:
        timestamp, premium, stock_price, spread_pct, option_data = fetch_snapshot(
            item["ticker"],
            item["contract"],
            item["expiration"],
            item["strike"],
            item["put_call"]
        )
        
        # Convert numpy types to native Python types
        def to_native(val):
            if val is None:
                return None
            try:
                return val.item()
            except (AttributeError, ValueError):
                return val
        
        return {
            "id": item_id,
            "timestamp": timestamp.isoformat(),
            "premium": to_native(premium),
            "stock_price": to_native(stock_price),
            "spread_pct": to_native(spread_pct),
            "option_data": {
                "bid": to_native(option_data["bid"]),
                "ask": to_native(option_data["ask"]),
                "mid": to_native(option_data["mid"]),
                "last": to_native(option_data["last"]),
                "volume": int(option_data["volume"]) if option_data["volume"] is not None else None,
                "open_interest": int(option_data["open_interest"]) if option_data["open_interest"] is not None else None,
                "iv": to_native(option_data["iv"]),
            }
        }
    except Exception as e:
        return {"error": str(e)}


# WebSocket for real-time streaming
class ConnectionManager:
    """Manages WebSocket connections and streaming tasks."""

    def __init__(self):
        self.active_connections: dict[WebSocket, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            task = self.active_connections[websocket]
            task.cancel()
            del self.active_connections[websocket]

    async def start_tracking(
        self,
        websocket: WebSocket,
        ticker: str,
        contract: str,
        expiration: str,
        strike: float,
        put_call: str,
    ):
        """Start background task to stream option data."""
        # Cancel existing task if any
        if websocket in self.active_connections:
            self.active_connections[websocket].cancel()

        async def stream_data():
            try:
                while True:
                    try:
                        # Check market status before fetching
                        market_status = is_market_open()
                        
                        if not market_status["is_open"]:
                            # Market is closed - automatically stop tracking
                            await websocket.send_json({
                                "type": "tracking_stopped",
                                "reason": "market_closed",
                                "market_status": market_status,
                                "message": f"Market is {market_status['status']}. Tracking automatically stopped."
                            })
                            break  # Exit the streaming loop to stop tracking
                        
                        timestamp, premium, stock_price, spread_pct, option_data = fetch_snapshot(
                            ticker, contract, expiration, strike, put_call
                        )

                        # Convert numpy types to native Python types for JSON serialization
                        def to_native(val):
                            if val is None:
                                return None
                            try:
                                # Handle numpy int/float types
                                return val.item()
                            except (AttributeError, ValueError):
                                return val

                        snapshot = {
                            "type": "snapshot",
                            "timestamp": timestamp.isoformat(),
                            "premium": to_native(premium),
                            "stock_price": to_native(stock_price),
                            "spread_pct": to_native(spread_pct),
                            "option_data": {
                                "bid": to_native(option_data["bid"]),
                                "ask": to_native(option_data["ask"]),
                                "mid": to_native(option_data["mid"]),
                                "last": to_native(option_data["last"]),
                                "volume": int(option_data["volume"]) if option_data["volume"] is not None else None,
                                "open_interest": int(option_data["open_interest"]) if option_data["open_interest"] is not None else None,
                                "iv": to_native(option_data["iv"]),
                            },
                        }

                        await websocket.send_json(snapshot)
                        await asyncio.sleep(30)

                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "message": str(e),
                        })
                        await asyncio.sleep(5)  # Wait before retry

            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(stream_data())
        self.active_connections[websocket] = task


manager = ConnectionManager()


@app.websocket("/ws/track")
async def websocket_track(websocket: WebSocket):
    """
    WebSocket endpoint for real-time option tracking.

    Client sends config:
    {
        "ticker": "AAPL",
        "contract": "AAPL240315C00200000",
        "expiration": "2024-03-15",
        "strike": 200.0,
        "put_call": "call"
    }

    Server pushes every 30s:
    {
        "type": "snapshot",
        "timestamp": "2024-01-15T10:30:00",
        "premium": 5.25,
        "stock_price": 185.50,
        "spread_pct": 2.83,
        "option_data": {...}
    }
    """
    await manager.connect(websocket)

    try:
        # Send connection confirmation
        await websocket.send_json({"type": "connected"})

        while True:
            # Wait for client config
            data = await websocket.receive_json()

            if data.get("action") == "start":
                await websocket.send_json({
                    "type": "tracking_started",
                    "config": data,
                })

                await manager.start_tracking(
                    websocket,
                    ticker=data["ticker"],
                    contract=data["contract"],
                    expiration=data["expiration"],
                    strike=data["strike"],
                    put_call=data["put_call"],
                )

            elif data.get("action") == "stop":
                manager.disconnect(websocket)
                await websocket.send_json({"type": "tracking_stopped"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Options Premium Tracker API",
        "version": "2.0.0",
    }
