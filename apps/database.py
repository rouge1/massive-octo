"""
Database Management Module for Options Tracking System

IMPORTANT - DESIGN PATTERN:
===========================
This module uses the INSTANCE-PER-APPLICATION pattern for database connections.
Each application should create its OWN DatabaseManager instance. This allows:
  - Multiple simultaneous MySQL connections with different usernames
  - Isolated database sessions per application
  - Independent connection lifecycle management

RECOMMENDED USAGE:
==================
    # In your main application file (e.g., options_watcher.py):
    import apps.database as db
    import getpass
    from urllib.parse import quote_plus
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    
    # Create your own dedicated DatabaseManager instance
    db_manager = db.DatabaseManager()
    
    # Manually configure connection (SECURE - no plaintext password files!)
    db_manager.db_config = {
        'host': input("Host: ").strip() or "localhost",
        'port': int(input("Port: ").strip() or "3306"),
        'user': input("Username: ").strip(),
        'password': getpass.getpass("Password: "),  # Hidden input!
        'database': input("Database: ").strip()
    }
    
    # Create engine and test connection
    encoded_password = quote_plus(db_manager.db_config['password'])
    mysql_url = f"mysql+pymysql://{db_manager.db_config['user']}:{encoded_password}@..."
    db_manager.engine = create_engine(mysql_url, pool_pre_ping=True, pool_recycle=3600)
    db_manager.Session = sessionmaker(bind=db_manager.engine)
    
    with db_manager.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    db_manager._connected = True
    
    # Use the instance throughout your application
    session = db_manager.get_session()
    try:
        # ... work with session ...
    finally:
        session.close()

AVOID:
======
    # ❌ DON'T use plaintext password files - security risk!
    # All apps should use getpass.getpass() for secure password entry

PASSING TO FUNCTIONS:
=====================
    Functions that need database access should accept a db_manager parameter:
    
    def my_function(db_manager):
        session = db_manager.get_session()
        try:
            # ... work with database ...
        finally:
            session.close()

Module Exports:
===============
- DatabaseManager: Main class for managing database connections
- OptionsWatchlist, OptionSnapshot: SQLAlchemy ORM models
"""

# Standard library imports
import hashlib
import io
import logging
import os
import re
import secrets
import string
import configparser
from datetime import datetime, timezone
from urllib.parse import quote_plus

# Third-party imports
import bcrypt
from PIL import Image
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    create_engine,
    Text,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    #formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# ==============================================================================
# ==============================================================================
# PUBLIC API - Use these in your code
# ==============================================================================
__all__ = [
    # Primary API - Use these for new code
    'DatabaseManager',      # ✓ Create your own instance: db_manager = DatabaseManager()
    'User',                 # ✓ ORM model for users table
    'OptionsWatchlist',     # ✓ ORM model for options_watchlist table
    'OptionSnapshot',       # ✓ ORM model for option_snapshots table
    'Alert',                # ✓ ORM model for alerts table
]
# ==============================================================================


# Initialize SQLAlchemy Base outside of the class so models can be defined
Base = declarative_base()


# ==============================================================================
# USER AUTHENTICATION MODEL
# ==============================================================================

class User(Base):
    """User accounts with authentication"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone_number = Column(String(20), nullable=True)
    website_url = Column(String(255), unique=True, nullable=True)  # Unique URL token for user's website
    password_hash = Column(String(255), nullable=False)  # Bcrypt hash for user authentication
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True, index=True)
    
    # Relationships
    watchlists = relationship("OptionsWatchlist", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    
    def set_password(self, password: str):
        """Hash and set password using bcrypt"""
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def check_password(self, password: str) -> bool:
        """Verify password against stored hash"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, name={self.first_name} {self.last_name})>"
    
    def to_dict(self, include_sensitive=False):
        """Convert to dictionary for API responses"""
        data = {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone_number': self.phone_number,
            'website_url': self.website_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }
        if include_sensitive:
            data['password_hash'] = self.password_hash
        return data


# ==============================================================================
# OPTIONS WATCHLIST MODELS
# ==============================================================================
# These models handle options contract tracking with price history snapshots.
# ==============================================================================


class OptionsWatchlist(Base):
    """Watchlist items - contracts the user wants to track"""
    __tablename__ = 'options_watchlist'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    strike = Column(Float, nullable=False)
    put_call = Column(String(4), nullable=False)  # 'call' or 'put'
    expiration = Column(String(10), nullable=False)  # YYYY-MM-DD format
    contract_symbol = Column(String(50), nullable=False, index=True)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True, index=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="watchlists")
    snapshots = relationship("OptionSnapshot", back_populates="watchlist_item", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="watchlist_item", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<OptionsWatchlist({self.ticker} ${self.strike} {self.put_call.upper()} exp:{self.expiration})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'ticker': self.ticker,
            'strike': self.strike,
            'put_call': self.put_call,
            'expiration': self.expiration,
            'contract_symbol': self.contract_symbol,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'is_active': self.is_active,
            'notes': self.notes
        }


class OptionSnapshot(Base):
    """Price snapshot history for tracked options"""
    __tablename__ = 'option_snapshots'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(Integer, ForeignKey('options_watchlist.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Stock price at snapshot time
    stock_price = Column(Float, nullable=True)
    
    # Option pricing data
    bid = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    mid = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    
    # Volume and interest
    volume = Column(Integer, nullable=True)
    open_interest = Column(Integer, nullable=True)
    
    # Greeks / metrics
    implied_volatility = Column(Float, nullable=True)
    spread_pct = Column(Float, nullable=True)  # (mid / stock_price) * 100
    delta = Column(Float, nullable=True)
    gamma = Column(Float, nullable=True)
    theta = Column(Float, nullable=True)
    vega = Column(Float, nullable=True)
    
    # Relationship
    watchlist_item = relationship("OptionsWatchlist", back_populates="snapshots")
    
    def __repr__(self):
        return f"<OptionSnapshot(id={self.id}, mid={self.mid}, ts={self.timestamp})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'watchlist_id': self.watchlist_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'stock_price': self.stock_price,
            'bid': self.bid,
            'ask': self.ask,
            'mid': self.mid,
            'last_price': self.last_price,
            'volume': self.volume,
            'open_interest': self.open_interest,
            'implied_volatility': self.implied_volatility,
            'spread_pct': self.spread_pct,
            'delta': self.delta,
            'gamma': self.gamma,
            'theta': self.theta,
            'vega': self.vega
        }


# ==============================================================================
# ALERTS MODEL
# ==============================================================================
# Alert system for price/premium thresholds and notifications
# ==============================================================================

class Alert(Base):
    """User-configured alerts for options tracking"""
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    watchlist_id = Column(Integer, ForeignKey('options_watchlist.id', ondelete='CASCADE'), nullable=True, index=True)
    
    # Alert configuration
    alert_type = Column(String(50), nullable=False)  # 'price_above', 'price_below', 'spread_threshold', 'iv_change', etc.
    threshold_value = Column(Float, nullable=False)  # The value to trigger alert
    comparison = Column(String(10), nullable=False)  # 'above', 'below', 'equals'
    
    # Alert metadata
    name = Column(String(100), nullable=True)  # User-friendly name
    description = Column(Text, nullable=True)  # Optional description
    is_active = Column(Boolean, default=True, index=True)
    is_triggered = Column(Boolean, default=False, index=True)
    
    # Notification preferences
    notify_email = Column(Boolean, default=True)
    notify_sms = Column(Boolean, default=False)
    notify_browser = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_checked = Column(DateTime, nullable=True)
    triggered_at = Column(DateTime, nullable=True)
    last_notified = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="alerts")
    watchlist_item = relationship("OptionsWatchlist", back_populates="alerts")
    
    def __repr__(self):
        return f"<Alert(id={self.id}, type={self.alert_type}, threshold={self.threshold_value}, active={self.is_active})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'watchlist_id': self.watchlist_id,
            'alert_type': self.alert_type,
            'threshold_value': self.threshold_value,
            'comparison': self.comparison,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'is_triggered': self.is_triggered,
            'notify_email': self.notify_email,
            'notify_sms': self.notify_sms,
            'notify_browser': self.notify_browser,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'last_notified': self.last_notified.isoformat() if self.last_notified else None
        }


# ==============================================================================
# DATABASE MANAGER CLASS
# ==============================================================================

class DatabaseManager:
    """
    Database Connection Manager - Instance-per-Application Pattern
    
    DESIGN PATTERN: Each application should create its OWN DatabaseManager instance.
    This allows multiple applications to connect to MySQL with different credentials
    and maintain isolated database sessions.
    
    Usage Example:
    --------------
        # In your main application (audio_watcher.py, cli_gui.py, admin_watcher.py):
        import apps.database as db
        import getpass
        from urllib.parse import quote_plus
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        
        # Create your dedicated instance
        db_manager = db.DatabaseManager()
        
        # Manually configure connection (SECURE!)
        db_manager.db_config = {
            'host': input("Host: ").strip() or "localhost",
            'port': int(input("Port: ").strip() or "3306"),
            'user': input("Username: ").strip(),
            'password': getpass.getpass("Password: "),  # Hidden!
            'database': input("Database: ").strip()
        }
        
        # Create engine and session
        encoded_password = quote_plus(db_manager.db_config['password'])
        mysql_url = f"mysql+pymysql://{db_manager.db_config['user']}:{encoded_password}@..."
        db_manager.engine = create_engine(mysql_url, pool_pre_ping=True, pool_recycle=3600)
        db_manager.Session = sessionmaker(bind=db_manager.engine)
        
        # Test connection
        with db_manager.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_manager._connected = True
        
        # Use throughout your application
        session = db_manager.get_session()
        try:
            users = session.query(db.User).all()
            # ... work with data ...
        finally:
            session.close()
    
    Instance Methods:
    -----------------
    - get_session(): Get a new database session
    - is_connected(): Check connection status
    - check_schema(): Validate database schema
    - init_db(): Create database tables
    - drop_all_tables(): Drop all tables (destructive!)
    - get_database_stats(): Get database statistics
    - get_websites_by_price_history(): Get websites for price checking
    - get_websites_without_prices(): Get untracked websites
    
    Why Instance-per-Application?
    ------------------------------
    - Multiple simultaneous MySQL connections (different usernames)
    - Isolated sessions prevent cross-application interference
    - Independent connection lifecycle (connect/disconnect per app)
    - Better security (each app can have different privileges)
    
    Thread Safety:
    --------------
    Each instance is thread-safe within its own application, but instances
    should NOT be shared across applications or processes.
    """
    
    def __init__(self):
        """
        Initialize the DatabaseManager without establishing a connection.
        
        Manually configure db_config and create engine/session to connect.
        See class docstring for complete example.
        """
        self.engine = None
        self.Session = None
        self.db_config = None
        self._connected = False
        logger.info("DatabaseManager initialized (not connected)")
    
    def is_connected(self):
        """Check if the database is connected"""
        return self._connected and self.engine is not None
    
    def get_session(self):
        """
        Get a database session
        
        Returns:
            Session: SQLAlchemy session
            
        Raises:
            RuntimeError: If database is not connected
        """
        if not self.is_connected():
            raise RuntimeError(
                "Database is not connected. Please manually configure the connection. "
                "See module docstring or term_gui.py for examples."
            )
        return self.Session()
    
    def check_schema(self):
        """
        Check if database has the required options tables.
        
        Returns:
            dict: {
                'has_tables': bool,
                'correct_schema': bool,
                'existing_tables': list,
                'missing_tables': list,
                'schema_issues': list,
                'message': str
            }
        """
        if not self.is_connected():
            raise RuntimeError("Database is not connected.")
        
        try:
            from sqlalchemy import inspect
            
            inspector = inspect(self.engine)
            existing_tables = inspector.get_table_names()
            
            # Expected tables from our models
            expected_tables = {'users', 'options_watchlist', 'option_snapshots', 'alerts'}
            
            result = {
                'has_tables': len(existing_tables) > 0,
                'existing_tables': existing_tables,
                'missing_tables': list(expected_tables - set(existing_tables)),
                'correct_schema': False,
                'schema_issues': [],
                'message': ''
            }
            
            # No tables at all - fresh database
            if not existing_tables:
                result['message'] = 'Database is empty. Tables will be created.'
                return result
            
            # Check if we have all required tables
            if not expected_tables.issubset(set(existing_tables)):
                result['message'] = f'Missing required tables: {", ".join(result["missing_tables"])}'
                return result
            
            # All required tables exist - validate by querying
            try:
                session = self.get_session()
                try:
                    session.query(User).first()
                    session.query(OptionsWatchlist).first()
                    session.query(OptionSnapshot).first()
                    session.query(Alert).first()
                    result['correct_schema'] = True
                    result['message'] = 'Database schema is correct and compatible.'
                    logger.info("✓ Schema validation successful")
                finally:
                    session.close()
            except Exception as e:
                result['message'] = f'Schema validation query failed: {str(e)}'
                result['schema_issues'].append(f"Query test failed: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to check schema: {str(e)}")
            raise
    
    def drop_all_tables(self):
        """Drop all tables in the database (USE WITH CAUTION!)"""
        if not self.is_connected():
            raise RuntimeError("Database is not connected.")
        
        try:
            logger.warning("Dropping all tables from database")
            Base.metadata.drop_all(self.engine)
            logger.info("All tables dropped successfully")
        except Exception as e:
            logger.error(f"Failed to drop tables: {str(e)}")
            raise
    
    def init_db(self):
        """Initialize the database, creating tables if they don't exist.
        Verifies schema matches models and logs warnings for mismatches."""
        if not self.is_connected():
            raise RuntimeError("Database is not connected.")

        try:
            logger.info("Initializing database tables")
            Base.metadata.create_all(self.engine)
            self._migrate_add_columns()
            self._verify_schema()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

    def _migrate_add_columns(self):
        """Add missing columns to existing tables via ALTER TABLE.
        Idempotent: checks inspector before adding."""
        from sqlalchemy import inspect, text
        inspector = inspect(self.engine)
        existing_tables = inspector.get_table_names()

        migrations = {
            'option_snapshots': {
                'delta': 'FLOAT NULL',
                'gamma': 'FLOAT NULL',
                'theta': 'FLOAT NULL',
                'vega': 'FLOAT NULL',
            }
        }

        for table_name, columns in migrations.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {col['name'] for col in inspector.get_columns(table_name)}
            for col_name, col_type in columns.items():
                if col_name not in existing_cols:
                    logger.info(f"Migrating: adding column '{col_name}' to '{table_name}'")
                    with self.engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))

    def _verify_schema(self):
        """Compare model columns against actual DB columns and log warnings for mismatches.
        Read-only: never alters the database."""
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        existing_tables = inspector.get_table_names()
        total_missing = 0

        for table_name, table_obj in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # Table doesn't exist yet, create_all handles it

            existing_cols = {col['name'] for col in inspector.get_columns(table_name)}
            missing_cols = []
            for column in table_obj.columns:
                if column.name not in existing_cols:
                    missing_cols.append(column.name)
                    logger.warning(f"Schema mismatch: column '{column.name}' missing from table '{table_name}'")

            if missing_cols:
                total_missing += len(missing_cols)

        if total_missing:
            logger.warning(
                f"Schema mismatch: {total_missing} missing column(s) detected. "
                "Drop and recreate tables to fix."
            )

    



