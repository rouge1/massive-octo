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
from datetime import datetime, timezone

import apps.database as db
import apps.options_api as options_api

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
                    
                    # Check market status
                    market_status = options_api.is_market_open()

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
                                    spread_pct=snapshot_data['spread_pct']
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
            return {'status': 'added', 'item': item.to_dict()}
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error adding to watchlist: {e}")
            return {'error': str(e)}
        finally:
            session.close()
    
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
