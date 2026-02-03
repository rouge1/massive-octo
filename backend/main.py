"""
FastAPI backend for Options Premium Tracker.
Provides REST endpoints for contract discovery and WebSocket for real-time streaming.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Data storage directory
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

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
def get_data_file(ticker: str, strike: float, put_call: str) -> Path:
    """Get the data file path for a contract."""
    # Format strike as int if it's a whole number, otherwise use float
    strike_str = str(int(strike)) if strike == int(strike) else str(strike)
    filename = f"{ticker.upper()}_{strike_str}_{put_call}.json"
    return DATA_DIR / filename


@app.post("/api/data/save")
async def save_snapshot(snapshot: dict):
    """Save a snapshot to the data file."""
    ticker = snapshot.get("ticker", "").upper()
    strike = snapshot.get("strike", 0)
    put_call = snapshot.get("put_call", "call")

    data_file = get_data_file(ticker, strike, put_call)

    # Load existing data or start fresh
    if data_file.exists():
        with open(data_file, "r") as f:
            data = json.load(f)
    else:
        data = {"ticker": ticker, "strike": strike, "put_call": put_call, "snapshots": []}

    # Add new snapshot (exclude meta fields)
    snapshot_data = {k: v for k, v in snapshot.items() if k not in ("ticker", "strike", "put_call")}
    data["snapshots"].append(snapshot_data)

    # Keep last 500 snapshots
    data["snapshots"] = data["snapshots"][-500:]

    # Save
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)

    return {"status": "saved", "count": len(data["snapshots"])}


@app.get("/api/data/load/{ticker}/{strike}/{put_call}")
async def load_data(ticker: str, strike: float, put_call: str):
    """Load saved data for a contract."""
    data_file = get_data_file(ticker, strike, put_call)

    if not data_file.exists():
        return {"ticker": ticker.upper(), "strike": strike, "put_call": put_call, "snapshots": []}

    with open(data_file, "r") as f:
        return json.load(f)


@app.delete("/api/data/clear/{ticker}/{strike}/{put_call}")
async def clear_data(ticker: str, strike: float, put_call: str):
    """Clear saved data for a contract."""
    data_file = get_data_file(ticker, strike, put_call)

    if data_file.exists():
        data_file.unlink()
        return {"status": "cleared"}

    return {"status": "not_found"}


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
                            # Send market closed status
                            await websocket.send_json({
                                "type": "market_closed",
                                "market_status": market_status,
                                "message": f"Market is {market_status['status']}. Data collection paused."
                            })
                            # Wait longer when market is closed (5 minutes)
                            await asyncio.sleep(300)
                            continue
                        
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
