"""
Options Timer - Background polling service for options watchlist.

Polls yfinance API at configurable intervals to fetch snapshots
for all active watchlist items and stores them in MySQL.

Polling intervals:
- Market open: 30 seconds
- Market closed: 5 minutes (reduced API calls)
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import yfinance as yf

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


class OptionsTimer:
    """
    Background timer for polling options data.
    
    Usage:
        timer = OptionsTimer(db_manager)
        await timer.run()  # Starts infinite polling loop
    """
    
    def __init__(self, db_manager=None):
        """
        Initialize the options timer.
        
        Args:
            db_manager: DatabaseManager instance for storing snapshots
        """
        self.db_manager = db_manager
        self.poll_interval_market_open = 30      # 30 seconds when market is open
        self.poll_interval_market_closed = 300   # 5 minutes when closed
        self.check_interval_no_db = 30           # Check for DB connection every 30s
        
        self._db_not_connected_logged = False
        self._no_watchlist_logged = False
        self._backfill_done = False
        
        logger.info(f"OptionsTimer initialized (db_manager: {id(self.db_manager) if self.db_manager else None})")
    
    def set_db_manager(self, db_manager):
        """Set or update the database manager."""
        self.db_manager = db_manager
        logger.info(f"OptionsTimer db_manager updated: {id(db_manager)}")
    
    async def run(self):
        """
        Main polling loop - runs indefinitely.
        
        Fetches snapshots for all active watchlist items and stores in DB.
        Adjusts polling rate based on market hours.
        """
        loop_iteration = 0
        
        while True:
            try:
                loop_iteration += 1
                
                # Check database connection
                if not self.db_manager or not self.db_manager.is_connected():
                    if not self._db_not_connected_logged:
                        logger.info("Database not connected - waiting for connection")
                        self._db_not_connected_logged = True
                    await asyncio.sleep(self.check_interval_no_db)
                    continue
                
                # Reset connection flag
                if self._db_not_connected_logged:
                    logger.info("Database connection detected - starting options polling")
                    self._db_not_connected_logged = False

                    # One-time backfill from Schwab history
                    if not self._backfill_done and schwab_client.is_available():
                        await self._backfill_from_schwab()
                        self._backfill_done = True

                    # Fill any stock price gaps (runs after Schwab backfill)
                    await self._fill_stock_gaps()

                # Get active watchlist items
                session = self.db_manager.get_session()
                try:
                    watchlist_items = session.query(db.OptionsWatchlist).filter(
                        db.OptionsWatchlist.is_active == True
                    ).all()
                    
                    if not watchlist_items:
                        if not self._no_watchlist_logged:
                            logger.info("No active watchlist items - waiting for items to be added")
                            self._no_watchlist_logged = True
                        await asyncio.sleep(self.check_interval_no_db)
                        continue
                    
                    # Reset flag
                    if self._no_watchlist_logged:
                        logger.info(f"Found {len(watchlist_items)} active watchlist items")
                        self._no_watchlist_logged = False
                    
                    # Auto-reconnect Schwab if it went down (throttled to every 5 min)
                    if not schwab_client.is_available():
                        schwab_client.try_reconnect()

                    # Check market status
                    market_status = options_api.is_market_open()

                    # Write active data source to shared settings so the web UI stays current
                    try:
                        import json, os
                        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'website_settings.json')
                        if os.path.exists(settings_path):
                            with open(settings_path, 'r') as f:
                                ws = json.load(f)
                            ws['data_source'] = 'schwab' if schwab_client.is_available() else 'yfinance'
                            with open(settings_path, 'w') as f:
                                json.dump(ws, f, indent=2)
                    except Exception:
                        pass

                    if not market_status['is_open']:
                        secs_to_open = options_api.seconds_until_market_open()
                        sleep_secs = min(self.poll_interval_market_closed, secs_to_open) if secs_to_open > 0 else self.poll_interval_market_closed
                        logger.debug(f"Market closed ({market_status['status']}) - sleeping {sleep_secs:.0f}s (open in {secs_to_open:.0f}s)")
                        await asyncio.sleep(sleep_secs)
                        continue

                    # Fetch and store snapshots for each item
                    success_count = 0
                    error_count = 0
                    
                    for item in watchlist_items:
                        try:
                            snapshot_data = options_api.fetch_snapshot(
                                ticker=item.ticker,
                                expiration=item.expiration,
                                strike=item.strike,
                                put_call=item.put_call
                            )
                            
                            if snapshot_data:
                                # Create snapshot record
                                snapshot = db.OptionSnapshot(
                                    watchlist_id=item.id,
                                    timestamp=snapshot_data['timestamp'],
                                    stock_price=snapshot_data['stock_price'],
                                    bid=snapshot_data['bid'],
                                    ask=snapshot_data['ask'],
                                    mid=snapshot_data['mid'],
                                    last_price=snapshot_data['last'],
                                    volume=snapshot_data['volume'],
                                    open_interest=snapshot_data['open_interest'],
                                    implied_volatility=snapshot_data['iv'],
                                    spread_pct=snapshot_data['spread_pct'],
                                    delta=snapshot_data.get('delta'),
                                    gamma=snapshot_data.get('gamma'),
                                    theta=snapshot_data.get('theta'),
                                    vega=snapshot_data.get('vega')
                                )
                                session.add(snapshot)
                                success_count += 1
                            else:
                                error_count += 1
                                logger.warning(f"No data for {item.ticker} ${item.strike} {item.put_call}")
                        
                        except Exception as e:
                            error_count += 1
                            logger.error(f"Error fetching {item.ticker}: {e}")
                    
                    # Commit all snapshots
                    session.commit()
                    
                    if success_count > 0:
                        logger.info(f"Stored {success_count} snapshots ({error_count} errors) - Market: {market_status['status']}")


                finally:
                    session.close()
                
                # Determine sleep interval based on market status
                if market_status['is_open']:
                    await asyncio.sleep(self.poll_interval_market_open)
                else:
                    await asyncio.sleep(self.poll_interval_market_closed)
            
            except Exception as e:
                logger.error(f"Error in options timer loop: {e}")
                await asyncio.sleep(30)  # Wait before retrying on error
    
    async def _fill_stock_gaps(self):
        """Scan today's snapshots for gaps > 2min and fill with yfinance stock prices."""
        market = options_api.is_market_open()
        if not market["is_open"]:
            return

        session = self.db_manager.get_session()
        try:
            items = session.query(db.OptionsWatchlist).filter(
                db.OptionsWatchlist.is_active == True
            ).all()
            if not items:
                return

            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            # Group by ticker — fetch yfinance once per underlying
            ticker_items = {}
            for item in items:
                ticker_items.setdefault(item.ticker, []).append(item)

            total_inserted = 0
            for ticker, group in ticker_items.items():
                # Collect today's timestamps across all items for this ticker
                # to find gaps in coverage
                all_timestamps = set()
                for item in group:
                    rows = session.query(db.OptionSnapshot.timestamp).filter(
                        db.OptionSnapshot.watchlist_id == item.id,
                        db.OptionSnapshot.timestamp >= today_start,
                    ).all()
                    for row in rows:
                        all_timestamps.add(row[0])

                if len(all_timestamps) < 2:
                    continue

                # Sort and find gaps > 2 minutes (internal + trailing)
                sorted_ts = sorted(all_timestamps)
                gap_ranges = []
                for i in range(1, len(sorted_ts)):
                    delta = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds() / 60
                    if delta > 2:
                        gap_ranges.append((sorted_ts[i - 1], sorted_ts[i], delta))

                # Also check trailing gap (last snapshot → now)
                trailing = (datetime.now() - sorted_ts[-1]).total_seconds() / 60
                if trailing > 2:
                    gap_ranges.append((sorted_ts[-1], datetime.now(), trailing))

                if not gap_ranges:
                    continue

                # Fetch yfinance 1-min stock candles for today
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="1d", interval="1m")
                    if hist.empty:
                        continue
                    # Strip timezone for comparison
                    hist.index = hist.index.tz_localize(None)
                except Exception as e:
                    logger.warning(f"Gap-fill: yfinance failed for {ticker}: {e}")
                    continue

                # For each gap, find yfinance candles that fall within it
                for gap_start, gap_end, gap_min in gap_ranges:
                    candles_in_gap = hist[
                        (hist.index > gap_start) & (hist.index < gap_end)
                    ]
                    if candles_in_gap.empty:
                        continue

                    for item in group:
                        existing = set(
                            row[0] for row in session.query(db.OptionSnapshot.timestamp)
                            .filter(
                                db.OptionSnapshot.watchlist_id == item.id,
                                db.OptionSnapshot.timestamp > gap_start,
                                db.OptionSnapshot.timestamp < gap_end,
                            ).all()
                        )

                        inserted = 0
                        for ts, row in candles_in_gap.iterrows():
                            candle_ts = ts.to_pydatetime().replace(tzinfo=None)
                            if candle_ts in existing:
                                continue
                            snapshot = db.OptionSnapshot(
                                watchlist_id=item.id,
                                timestamp=candle_ts,
                                stock_price=float(row["Close"]),
                            )
                            session.add(snapshot)
                            inserted += 1

                        total_inserted += inserted

                    logger.info(
                        f"Gap-fill: {ticker} {gap_start.strftime('%H:%M')}-"
                        f"{gap_end.strftime('%H:%M')} ({gap_min:.0f}min) — "
                        f"{len(candles_in_gap)} stock candles"
                    )

            session.commit()
            if total_inserted:
                logger.info(f"Gap-fill complete: {total_inserted} stock-price snapshots inserted")
            else:
                logger.info("Gap-fill: no gaps found")

        except Exception as e:
            session.rollback()
            logger.error(f"Gap-fill failed: {e}")
        finally:
            session.close()

    async def _backfill_from_schwab(self):
        """Pull historical 5-min candles from Schwab for all active watchlist items."""
        session = self.db_manager.get_session()
        try:
            items = session.query(db.OptionsWatchlist).filter(
                db.OptionsWatchlist.is_active == True
            ).all()
            if not items:
                logger.info("Backfill: no active watchlist items")
                return
            self._backfill_items(session, items)
        except Exception as e:
            session.rollback()
            logger.error(f"Backfill failed: {e}")
        finally:
            session.close()

    def backfill_single_item(self, item_id: int):
        """Backfill historical data for a single newly-added watchlist item."""
        if not schwab_client.is_available():
            return
        session = self.db_manager.get_session()
        try:
            item = session.query(db.OptionsWatchlist).filter(
                db.OptionsWatchlist.id == item_id
            ).first()
            if item:
                self._backfill_items(session, [item])
        except Exception as e:
            session.rollback()
            logger.error(f"Backfill single item failed: {e}")
        finally:
            session.close()

    def _backfill_items(self, session, items):
        """Core backfill logic — fetch Schwab candles and insert missing snapshots."""
        total_inserted = 0

        # Group by ticker so we fetch stock candles once per underlying
        ticker_items = {}
        for item in items:
            ticker_items.setdefault(item.ticker, []).append(item)

        for ticker, group in ticker_items.items():
            # Fetch stock price candles for the underlying ticker
            stock_candles = {}
            try:
                raw = schwab_client.get_price_history_candles(ticker)
                for c in raw:
                    stock_candles[c["timestamp"]] = c["close"]
                logger.debug(f"Backfill: loaded {ticker} stock prices ({len(raw)} points)")
            except Exception as e:
                logger.warning(f"Backfill: failed stock history for {ticker}: {e}")

            # Fetch option candles per contract and insert
            for item in group:
                dte = options_api.calculate_dte(item.expiration)
                label = f"{item.ticker} ${item.strike} {item.put_call} {dte}DTE"

                try:
                    schwab_symbol = schwab_client._to_schwab_option_symbol(
                        item.contract_symbol
                    )
                    option_candles = schwab_client.get_price_history_candles(
                        schwab_symbol
                    )
                except Exception as e:
                    logger.warning(f"Backfill: {label} — failed: {e}")
                    continue

                if not option_candles:
                    logger.info(f"Backfill: {label} — 0 candles from Schwab")
                    continue

                # Load existing timestamps to avoid duplicates
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

                logger.info(f"Backfill: {label} — {inserted} new from Schwab")
                total_inserted += inserted

        session.commit()
        logger.info(f"Backfill complete: {total_inserted} snapshots inserted")

    def get_watchlist(self) -> list[dict]:
        """
        Get all watchlist items.
        
        Returns:
            List of watchlist item dicts
        """
        if not self.db_manager or not self.db_manager.is_connected():
            return []
        
        session = self.db_manager.get_session()
        try:
            items = session.query(db.OptionsWatchlist).all()
            return [item.to_dict() for item in items]
        finally:
            session.close()
    
    def add_to_watchlist(self, ticker: str, strike: float, put_call: str, 
                         expiration: str, contract_symbol: str, notes: str = None) -> dict:
        """
        Add an item to the watchlist.
        
        Args:
            ticker: Stock ticker symbol
            strike: Strike price
            put_call: 'call' or 'put'
            expiration: Expiration date (YYYY-MM-DD)
            contract_symbol: Full contract symbol
            notes: Optional notes
        
        Returns:
            Dict with status and item data
        """
        if not self.db_manager or not self.db_manager.is_connected():
            return {'error': 'Database not connected'}
        
        session = self.db_manager.get_session()
        try:
            # Check if already exists
            existing = session.query(db.OptionsWatchlist).filter(
                db.OptionsWatchlist.contract_symbol == contract_symbol
            ).first()
            
            if existing:
                # Reactivate if inactive
                if not existing.is_active:
                    existing.is_active = True
                    session.commit()
                    return {'status': 'reactivated', 'item': existing.to_dict()}
                return {'status': 'already_exists', 'item': existing.to_dict()}
            
            # Create new item
            item = db.OptionsWatchlist(
                ticker=ticker.upper(),
                strike=strike,
                put_call=put_call.lower(),
                expiration=expiration,
                contract_symbol=contract_symbol,
                notes=notes,
                added_at=datetime.now(timezone.utc),
                is_active=True
            )
            session.add(item)
            session.commit()
            
            logger.info(f"Added to watchlist: {ticker} ${strike} {put_call} exp:{expiration}")
            result = {'status': 'added', 'item': item.to_dict()}
            item_id = item.id

        except Exception as e:
            session.rollback()
            logger.error(f"Error adding to watchlist: {e}")
            return {'error': str(e)}
        finally:
            session.close()

        # Backfill historical data for the newly added item
        self.backfill_single_item(item_id)
        return result
    
    def remove_from_watchlist(self, item_id: int = None, contract_symbol: str = None, 
                               hard_delete: bool = False) -> dict:
        """
        Remove an item from the watchlist.
        
        Args:
            item_id: ID of item to remove (or use contract_symbol)
            contract_symbol: Contract symbol to remove (alternative to item_id)
            hard_delete: If True, permanently delete; if False, just deactivate
        
        Returns:
            Dict with status
        """
        if not self.db_manager or not self.db_manager.is_connected():
            return {'error': 'Database not connected'}
        
        session = self.db_manager.get_session()
        try:
            # Find item
            if item_id:
                item = session.query(db.OptionsWatchlist).filter(
                    db.OptionsWatchlist.id == item_id
                ).first()
            elif contract_symbol:
                item = session.query(db.OptionsWatchlist).filter(
                    db.OptionsWatchlist.contract_symbol == contract_symbol
                ).first()
            else:
                return {'error': 'Must provide item_id or contract_symbol'}
            
            if not item:
                return {'status': 'not_found'}
            
            if hard_delete:
                session.delete(item)
                session.commit()
                logger.info(f"Deleted from watchlist: {item.ticker} ${item.strike}")
                return {'status': 'deleted'}
            else:
                item.is_active = False
                session.commit()
                logger.info(f"Deactivated from watchlist: {item.ticker} ${item.strike}")
                return {'status': 'deactivated'}
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error removing from watchlist: {e}")
            return {'error': str(e)}
        finally:
            session.close()
    
    def get_snapshots(self, watchlist_id: int, limit: int = 100) -> list[dict]:
        """
        Get recent snapshots for a watchlist item.
        
        Args:
            watchlist_id: ID of watchlist item
            limit: Maximum number of snapshots to return
        
        Returns:
            List of snapshot dicts (newest first)
        """
        if not self.db_manager or not self.db_manager.is_connected():
            return []
        
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
    
    def get_latest_snapshot(self, watchlist_id: int) -> dict:
        """
        Get the most recent snapshot for a watchlist item.
        
        Args:
            watchlist_id: ID of watchlist item
        
        Returns:
            Latest snapshot dict or None
        """
        if not self.db_manager or not self.db_manager.is_connected():
            return None
        
        session = self.db_manager.get_session()
        try:
            snapshot = session.query(db.OptionSnapshot).filter(
                db.OptionSnapshot.watchlist_id == watchlist_id
            ).order_by(
                db.OptionSnapshot.timestamp.desc()
            ).first()
            
            return snapshot.to_dict() if snapshot else None
        finally:
            session.close()
