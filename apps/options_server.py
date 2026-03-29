"""
Options Tracker Server - FastAPI web server for options tracking

Provides:
- Frontend serving (React app from frontend/)
- REST API for watchlist CRUD operations
- SSE streams for real-time updates

Run from website.py as integrated server.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Local imports
import apps.database as db
import apps.options_api as options_api
from apps import schwab_client

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# Pydantic models for API requests/responses
class WatchlistAddRequest(BaseModel):
    ticker: str
    strike: float
    put_call: str  # 'call' or 'put'
    expiration: str  # YYYY-MM-DD
    contract_symbol: str
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    id: int
    user_id: int
    ticker: str
    strike: float
    put_call: str
    expiration: str
    contract_symbol: str
    added_at: str
    is_active: bool
    notes: Optional[str]


class SnapshotResponse(BaseModel):
    id: int
    watchlist_id: int
    timestamp: str
    stock_price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    last_price: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    implied_volatility: Optional[float]
    spread_pct: Optional[float]


class OptionsServer:
    """FastAPI-based web server for options tracking"""

    def __init__(self, db_manager, host='0.0.0.0', port=9081):
        self.db_manager = db_manager
        self.host = host
        self.port = port
        
        # Default user ID for operations (since we're skipping user auth for now)
        self.default_user_id = 1
        
        # Get project root directory (parent of apps/)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.frontend_dir = os.path.join(self.base_dir, 'frontend')
        
        # Create FastAPI app
        self.app = FastAPI(
            title="Options Tracker",
            description="Real-time options tracking with watchlist and SSE streaming"
        )
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Ensure default user exists
        self._ensure_default_user()
        
        # SSE connection tracking
        self.sse_clients = {
            'watchlist': set(),  # Clients watching full watchlist
            'options': {}  # Clients watching specific options: {watchlist_id: set()}
        }
        
        # Setup routes
        self._setup_routes()
        
        # Mount frontend static files LAST (after all API routes)
        if os.path.exists(self.frontend_dir):
            self.app.mount("/", StaticFiles(directory=self.frontend_dir, html=True), name="frontend")
            logger.info(f"Mounted frontend from: {self.frontend_dir}")
        else:
            logger.warning(f"Frontend directory not found: {self.frontend_dir}")
        
        logger.info(f"OptionsServer initialized (port: {port})")
    
    def _ensure_default_user(self):
        """Ensure a default user exists in the database for watchlist items"""
        if not self.db_manager or not self.db_manager.is_connected():
            logger.warning("Cannot create default user - database not connected")
            return
        
        try:
            session = self.db_manager.get_session()
            try:
                # Check if user with id=1 exists
                user = session.query(db.User).filter(db.User.id == self.default_user_id).first()
                if not user:
                    # Create default user
                    user = db.User(
                        id=self.default_user_id,
                        first_name="Default",
                        last_name="User",
                        email="default@localhost",
                        is_active=True
                    )
                    user.set_password("changeme")  # Default password
                    session.add(user)
                    session.commit()
                    logger.info("Created default user (id=1)")
                else:
                    logger.info(f"Default user exists: {user.email}")
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Failed to create default user: {e}")
    
    def _backfill_item(self, item_id: int):
        """Backfill historical Schwab candles for a single watchlist item."""
        session = self.db_manager.get_session()
        try:
            item = session.query(db.OptionsWatchlist).filter(
                db.OptionsWatchlist.id == item_id
            ).first()
            if not item:
                return

            dte = (datetime.strptime(item.expiration, "%Y-%m-%d").date() - datetime.now().date()).days
            label = f"{item.ticker} ${item.strike} {item.put_call} {dte}DTE"

            # Fetch stock candles
            stock_candles = {}
            try:
                raw = schwab_client.get_price_history_candles(item.ticker)
                for c in raw:
                    stock_candles[c["timestamp"]] = c["close"]
                logger.debug(f"Backfill: loaded {item.ticker} stock prices ({len(raw)} points)")
            except Exception as e:
                logger.warning(f"Backfill: {item.ticker} stock failed: {e}")

            # Fetch option candles
            schwab_symbol = schwab_client._to_schwab_option_symbol(item.contract_symbol)
            option_candles = schwab_client.get_price_history_candles(schwab_symbol)
            if not option_candles:
                logger.info(f"Backfill: {label} — 0 candles from Schwab")
                return

            existing = set(
                row[0] for row in session.query(db.OptionSnapshot.timestamp)
                .filter(db.OptionSnapshot.watchlist_id == item.id)
                .all()
            )

            inserted = 0
            skipped = 0
            for candle in option_candles:
                if candle["timestamp"] in existing:
                    skipped += 1
                    continue
                stock_price = stock_candles.get(candle["timestamp"])
                mid = candle["close"]
                spread_pct = (
                    (mid / stock_price) * 100
                    if stock_price and stock_price > 0
                    else None
                )
                snapshot = db.OptionSnapshot(
                    watchlist_id=item.id,
                    timestamp=candle["timestamp"],
                    stock_price=stock_price,
                    mid=mid,
                    last_price=mid,
                    volume=candle["volume"],
                    spread_pct=spread_pct,
                )
                session.add(snapshot)
                inserted += 1

            session.commit()
            logger.info(f"Backfill: {label} — {inserted} new from Schwab")
        except Exception as e:
            session.rollback()
            logger.error(f"Backfill failed for item {item_id}: {e}")
        finally:
            session.close()

    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        # ==================================================================
        # WATCHLIST CRUD ENDPOINTS
        # ==================================================================
        
        @self.app.get("/api/watchlist", response_model=List[WatchlistItemResponse])
        async def get_watchlist():
            """Get all watchlist items for default user"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    items = session.query(db.OptionsWatchlist).filter(
                        db.OptionsWatchlist.user_id == self.default_user_id,
                        db.OptionsWatchlist.is_active == True
                    ).all()
                    return [item.to_dict() for item in items]
                finally:
                    session.close()
            except Exception as e:
                logger.error(f"Error fetching watchlist: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/watchlist")
        async def add_to_watchlist(request: WatchlistAddRequest):
            """Add an option to the watchlist"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    # Normalize to OCC format (Schwab adds spaces, yfinance doesn't)
                    contract_symbol = request.contract_symbol.replace(" ", "")

                    # Check if already exists
                    existing = session.query(db.OptionsWatchlist).filter(
                        db.OptionsWatchlist.user_id == self.default_user_id,
                        db.OptionsWatchlist.contract_symbol == contract_symbol
                    ).first()

                    if existing:
                        if not existing.is_active:
                            # Reactivate
                            existing.is_active = True
                            session.commit()
                            return {"status": "reactivated", "item": existing.to_dict()}
                        return {"status": "already_exists", "item": existing.to_dict()}

                    # Create new item
                    item = db.OptionsWatchlist(
                        user_id=self.default_user_id,
                        ticker=request.ticker.upper(),
                        strike=request.strike,
                        put_call=request.put_call.lower(),
                        expiration=request.expiration,
                        contract_symbol=contract_symbol,
                        notes=request.notes,
                        added_at=datetime.now(timezone.utc),
                        is_active=True
                    )
                    session.add(item)
                    session.commit()

                    logger.info(f"Added to watchlist: {request.ticker} ${request.strike} {request.put_call}")
                    result = {"status": "added", "item": item.to_dict()}
                    item_id = item.id

                finally:
                    session.close()

                # Backfill historical data from Schwab
                if schwab_client.is_available():
                    try:
                        self._backfill_item(item_id)
                    except Exception as e:
                        logger.warning(f"Backfill for new item failed: {e}")

                return result
            except Exception as e:
                logger.error(f"Error adding to watchlist: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.delete("/api/watchlist/{item_id}")
        async def remove_from_watchlist(item_id: int):
            """Remove an item from the watchlist"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    item = session.query(db.OptionsWatchlist).filter(
                        db.OptionsWatchlist.id == item_id,
                        db.OptionsWatchlist.user_id == self.default_user_id
                    ).first()
                    
                    if not item:
                        raise HTTPException(status_code=404, detail="Item not found")
                    
                    # Soft delete (deactivate)
                    item.is_active = False
                    session.commit()
                    
                    logger.info(f"Removed from watchlist: {item.ticker} ${item.strike}")
                    return {"status": "removed"}
                
                finally:
                    session.close()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error removing from watchlist: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # ==================================================================
        # OPTION DATA ENDPOINTS
        # ==================================================================
        
        @self.app.get("/api/strikes/{ticker}/{put_call}")
        async def get_strikes(ticker: str, put_call: str):
            """Get available strike prices for a ticker"""
            try:
                strikes = options_api.list_available_strikes(ticker, put_call)
                stock_price = options_api.get_stock_price(ticker)
                return {
                    "ticker": ticker,
                    "put_call": put_call,
                    "strikes": strikes,
                    "stock_price": stock_price
                }
            except Exception as e:
                logger.error(f"Error fetching strikes: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/contracts/{ticker}/{strike}/{put_call}")
        async def get_contracts(ticker: str, strike: float, put_call: str):
            """Get available contracts (expirations) for a ticker/strike"""
            try:
                contracts = options_api.list_available_contracts(ticker, strike, put_call)
                return {
                    "ticker": ticker,
                    "strike": strike,
                    "put_call": put_call,
                    "contracts": contracts
                }
            except Exception as e:
                logger.error(f"Error fetching contracts: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/price/{ticker}")
        async def get_price(ticker: str):
            """Get current stock price"""
            try:
                price = options_api.get_stock_price(ticker)
                return {
                    "ticker": ticker,
                    "price": price,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            except Exception as e:
                logger.error(f"Error fetching price: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/market/status")
        async def get_market_status():
            """Check if market is open"""
            try:
                status = options_api.is_market_open()
                status["data_source"] = "schwab" if schwab_client.is_available() else "yfinance"
                return status
            except Exception as e:
                logger.error(f"Error checking market status: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # ==================================================================
        # SNAPSHOT HISTORY ENDPOINTS
        # ==================================================================
        
        @self.app.get("/api/snapshots/{watchlist_id}", response_model=List[SnapshotResponse])
        async def get_snapshots(watchlist_id: int, limit: int = 100):
            """Get snapshot history for a watchlist item"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    snapshots = session.query(db.OptionSnapshot).filter(
                        db.OptionSnapshot.watchlist_id == watchlist_id
                    ).order_by(
                        db.OptionSnapshot.timestamp.desc()
                    ).limit(limit).all()
                    
                    return [s.to_dict() for s in snapshots]
                finally:
                    session.close()
            except Exception as e:
                logger.error(f"Error fetching snapshots: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/snapshots/{watchlist_id}/latest")
        async def get_latest_snapshot(watchlist_id: int):
            """Get the most recent snapshot for a watchlist item"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    snapshot = session.query(db.OptionSnapshot).filter(
                        db.OptionSnapshot.watchlist_id == watchlist_id
                    ).order_by(
                        db.OptionSnapshot.timestamp.desc()
                    ).first()
                    
                    if not snapshot:
                        raise HTTPException(status_code=404, detail="No snapshots found")
                    
                    return snapshot.to_dict()
                finally:
                    session.close()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error fetching latest snapshot: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # Alias endpoint for compatibility with frontend
        @self.app.get("/api/watchlist/{item_id}/snapshot")
        async def get_watchlist_item_snapshot(item_id: int):
            """Get the most recent snapshot for a watchlist item (frontend-compatible format)"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")
            
            try:
                session = self.db_manager.get_session()
                try:
                    # Get the watchlist item
                    item = session.query(db.OptionsWatchlist).filter(
                        db.OptionsWatchlist.id == item_id
                    ).first()
                    
                    if not item:
                        return {"error": "Item not found"}
                    
                    # Get latest snapshot
                    snapshot = session.query(db.OptionSnapshot).filter(
                        db.OptionSnapshot.watchlist_id == item_id
                    ).order_by(
                        db.OptionSnapshot.timestamp.desc()
                    ).first()
                    
                    if not snapshot:
                        return {"error": "No snapshot data available"}
                    
                    # Format to match frontend expectations
                    return {
                        "id": str(item_id),
                        "timestamp": snapshot.timestamp.isoformat() if snapshot.timestamp else None,
                        "premium": snapshot.mid,
                        "stock_price": snapshot.stock_price,
                        "spread_pct": snapshot.spread_pct,
                        "option_data": {
                            "bid": snapshot.bid,
                            "ask": snapshot.ask,
                            "mid": snapshot.mid,
                            "last": snapshot.last_price,
                            "volume": snapshot.volume,
                            "open_interest": snapshot.open_interest,
                            "iv": snapshot.implied_volatility,
                        }
                    }
                finally:
                    session.close()
            except Exception as e:
                logger.error(f"Error fetching watchlist snapshot: {e}")
                return {"error": str(e)}
        
        # ==================================================================
        # SSE STREAMING ENDPOINTS
        # ==================================================================
        
        @self.app.get("/sse/watchlist")
        async def sse_watchlist_stream(request: Request):
            """
            SSE stream for all watchlist items.
            Pushes updates every time new snapshots are available.
            """
            async def event_generator():
                client_id = id(request)
                self.sse_clients['watchlist'].add(client_id)
                logger.info(f"SSE client connected to watchlist stream: {client_id}")
                
                try:
                    while True:
                        # Check if client disconnected
                        if await request.is_disconnected():
                            break
                        
                        # Get all active watchlist items with latest snapshots
                        if self.db_manager and self.db_manager.is_connected():
                            try:
                                session = self.db_manager.get_session()
                                try:
                                    items = session.query(db.OptionsWatchlist).filter(
                                        db.OptionsWatchlist.user_id == self.default_user_id,
                                        db.OptionsWatchlist.is_active == True
                                    ).all()
                                    
                                    # Build response with latest snapshot for each item
                                    data = []
                                    for item in items:
                                        latest = session.query(db.OptionSnapshot).filter(
                                            db.OptionSnapshot.watchlist_id == item.id
                                        ).order_by(
                                            db.OptionSnapshot.timestamp.desc()
                                        ).first()
                                        
                                        item_data = item.to_dict()
                                        item_data['latest_snapshot'] = latest.to_dict() if latest else None
                                        data.append(item_data)
                                    
                                    # Send SSE event
                                    yield f"data: {json.dumps(data)}\n\n"
                                
                                finally:
                                    session.close()
                            except Exception as e:
                                logger.error(f"Error in watchlist SSE stream: {e}")
                        
                        # Wait before next update (30 seconds)
                        await asyncio.sleep(30)
                
                finally:
                    # Client disconnected
                    self.sse_clients['watchlist'].discard(client_id)
                    logger.info(f"SSE client disconnected from watchlist stream: {client_id}")
            
            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # Disable nginx buffering
                }
            )
        
        @self.app.get("/sse/option/{watchlist_id}")
        async def sse_option_stream(request: Request, watchlist_id: int):
            """
            SSE stream for a specific option.
            Pushes detailed snapshot updates.
            """
            async def event_generator():
                client_id = id(request)
                
                # Track this client
                if watchlist_id not in self.sse_clients['options']:
                    self.sse_clients['options'][watchlist_id] = set()
                self.sse_clients['options'][watchlist_id].add(client_id)
                logger.info(f"SSE client connected to option stream: {watchlist_id}")
                
                try:
                    while True:
                        # Check if client disconnected
                        if await request.is_disconnected():
                            break
                        
                        # Get latest snapshot for this option
                        if self.db_manager and self.db_manager.is_connected():
                            try:
                                session = self.db_manager.get_session()
                                try:
                                    # Get watchlist item
                                    item = session.query(db.OptionsWatchlist).filter(
                                        db.OptionsWatchlist.id == watchlist_id
                                    ).first()
                                    
                                    if not item:
                                        yield f"data: {json.dumps({'error': 'Item not found'})}\n\n"
                                        break
                                    
                                    # Get latest snapshot
                                    snapshot = session.query(db.OptionSnapshot).filter(
                                        db.OptionSnapshot.watchlist_id == watchlist_id
                                    ).order_by(
                                        db.OptionSnapshot.timestamp.desc()
                                    ).first()
                                    
                                    # Send combined data
                                    data = {
                                        'watchlist_item': item.to_dict(),
                                        'snapshot': snapshot.to_dict() if snapshot else None
                                    }
                                    yield f"data: {json.dumps(data)}\n\n"
                                
                                finally:
                                    session.close()
                            except Exception as e:
                                logger.error(f"Error in option SSE stream: {e}")
                        
                        # Wait before next update (30 seconds)
                        await asyncio.sleep(30)
                
                finally:
                    # Client disconnected
                    if watchlist_id in self.sse_clients['options']:
                        self.sse_clients['options'][watchlist_id].discard(client_id)
                        if not self.sse_clients['options'][watchlist_id]:
                            del self.sse_clients['options'][watchlist_id]
                    logger.info(f"SSE client disconnected from option stream: {watchlist_id}")
            
            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
    
