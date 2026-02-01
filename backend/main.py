"""
FastAPI backend for Options Premium Tracker.
Provides REST endpoints for contract discovery and WebSocket for real-time streaming.
"""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api_client import (
    list_available_strikes,
    list_available_contracts,
    get_stock_price,
    fetch_snapshot,
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
                        timestamp, premium, stock_price, spread_pct, option_data = fetch_snapshot(
                            ticker, contract, expiration, strike, put_call
                        )

                        snapshot = {
                            "type": "snapshot",
                            "timestamp": timestamp.isoformat(),
                            "premium": premium,
                            "stock_price": stock_price,
                            "spread_pct": spread_pct,
                            "option_data": {
                                "bid": option_data["bid"],
                                "ask": option_data["ask"],
                                "mid": option_data["mid"],
                                "last": option_data["last"],
                                "volume": option_data["volume"],
                                "open_interest": option_data["open_interest"],
                                "iv": option_data["iv"],
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
