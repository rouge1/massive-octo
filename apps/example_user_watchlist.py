"""
Example script demonstrating User, Watchlist, and Alert functionality

This script shows how to:
1. Create a new user with authentication
2. Add watchlist items for that user
3. Create alerts for watchlist items
4. Query user's watchlists and alerts
"""

import getpass
import sys
from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import database models
import database as db


def setup_database_connection():
    """Setup database connection with user prompts"""
    print("\n=== Database Connection Setup ===")
    db_manager = db.DatabaseManager()
    
    # Prompt for database credentials
    db_manager.db_config = {
        'host': input("MySQL Host [localhost]: ").strip() or "localhost",
        'port': int(input("MySQL Port [3306]: ").strip() or "3306"),
        'user': input("MySQL Username: ").strip(),
        'password': getpass.getpass("MySQL Password: "),
        'database': input("Database Name: ").strip()
    }
    
    # Create engine
    encoded_password = quote_plus(db_manager.db_config['password'])
    mysql_url = (
        f"mysql+pymysql://{db_manager.db_config['user']}:{encoded_password}"
        f"@{db_manager.db_config['host']}:{db_manager.db_config['port']}"
        f"/{db_manager.db_config['database']}"
    )
    
    db_manager.engine = create_engine(
        mysql_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False
    )
    db_manager.Session = sessionmaker(bind=db_manager.engine)
    
    # Test connection
    try:
        with db_manager.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_manager._connected = True
        print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        sys.exit(1)
    
    return db_manager


def create_example_user(db_manager):
    """Create an example user"""
    session = db_manager.get_session()
    try:
        # Check if user already exists
        existing_user = session.query(db.User).filter_by(email="trader@example.com").first()
        if existing_user:
            print(f"\n✓ User already exists: {existing_user}")
            return existing_user
        
        # Create new user
        user = db.User(
            first_name="Jane",
            last_name="Trader",
            email="trader@example.com",
            phone_number="+1-555-0123",
            website_url="janetrader"
        )
        user.set_password("SecurePassword123!")  # Hash the password
        
        session.add(user)
        session.commit()
        session.refresh(user)
        
        print(f"\n✓ Created user: {user}")
        print(f"  User ID: {user.id}")
        print(f"  Email: {user.email}")
        print(f"  Created: {user.created_at}")
        
        return user
        
    except Exception as e:
        session.rollback()
        print(f"✗ Error creating user: {e}")
        raise
    finally:
        session.close()


def add_watchlist_items(db_manager, user):
    """Add example watchlist items for the user"""
    session = db_manager.get_session()
    try:
        # Check if watchlist items already exist
        existing_count = session.query(db.OptionsWatchlist).filter_by(user_id=user.id).count()
        if existing_count > 0:
            print(f"\n✓ User already has {existing_count} watchlist items")
            return
        
        # Create watchlist items
        watchlist_items = [
            db.OptionsWatchlist(
                user_id=user.id,
                ticker="AAPL",
                strike=200.0,
                put_call="call",
                expiration="2026-03-20",
                contract_symbol="AAPL260320C00200000",
                notes="Apple March calls - bullish tech play"
            ),
            db.OptionsWatchlist(
                user_id=user.id,
                ticker="TSLA",
                strike=250.0,
                put_call="put",
                expiration="2026-04-17",
                contract_symbol="TSLA260417P00250000",
                notes="Tesla puts - hedging position"
            ),
            db.OptionsWatchlist(
                user_id=user.id,
                ticker="SPY",
                strike=500.0,
                put_call="call",
                expiration="2026-06-19",
                contract_symbol="SPY260619C00500000",
                notes="S&P 500 long-term calls"
            )
        ]
        
        session.add_all(watchlist_items)
        session.commit()
        
        print(f"\n✓ Added {len(watchlist_items)} watchlist items:")
        for item in watchlist_items:
            print(f"  - {item.ticker} ${item.strike} {item.put_call.upper()} exp:{item.expiration}")
        
        return watchlist_items
        
    except Exception as e:
        session.rollback()
        print(f"✗ Error adding watchlist items: {e}")
        raise
    finally:
        session.close()


def create_example_alerts(db_manager, user):
    """Create example alerts for user's watchlist items"""
    session = db_manager.get_session()
    try:
        # Get user's watchlist items
        watchlist_items = session.query(db.OptionsWatchlist).filter_by(
            user_id=user.id
        ).all()
        
        if not watchlist_items:
            print("\n⚠ No watchlist items found to create alerts for")
            return
        
        # Check if alerts already exist
        existing_count = session.query(db.Alert).filter_by(user_id=user.id).count()
        if existing_count > 0:
            print(f"\n✓ User already has {existing_count} alerts")
            return
        
        # Create alerts
        alerts = []
        for item in watchlist_items[:2]:  # Create alerts for first 2 items
            # Price threshold alert
            alert = db.Alert(
                user_id=user.id,
                watchlist_id=item.id,
                alert_type="premium_above",
                threshold_value=10.0,
                comparison="above",
                name=f"{item.ticker} Premium Alert",
                description=f"Alert when {item.ticker} option premium goes above $10",
                notify_email=True,
                notify_browser=True
            )
            alerts.append(alert)
        
        session.add_all(alerts)
        session.commit()
        
        print(f"\n✓ Created {len(alerts)} alerts:")
        for alert in alerts:
            print(f"  - {alert.name}: {alert.alert_type} {alert.threshold_value}")
        
        return alerts
        
    except Exception as e:
        session.rollback()
        print(f"✗ Error creating alerts: {e}")
        raise
    finally:
        session.close()


def query_user_data(db_manager, user):
    """Query and display user's watchlists and alerts"""
    session = db_manager.get_session()
    try:
        # Get user with relationships
        user = session.query(db.User).filter_by(id=user.id).first()
        
        print("\n=== User Data Summary ===")
        print(f"User: {user.first_name} {user.last_name} ({user.email})")
        print(f"\nWatchlist Items ({len(user.watchlists)}):")
        for item in user.watchlists:
            print(f"  {item.id}. {item.ticker} ${item.strike} {item.put_call.upper()} "
                  f"exp:{item.expiration}")
            print(f"     Contract: {item.contract_symbol}")
            print(f"     Added: {item.added_at.strftime('%Y-%m-%d %H:%M')}")
            if item.notes:
                print(f"     Notes: {item.notes}")
        
        print(f"\nAlerts ({len(user.alerts)}):")
        for alert in user.alerts:
            status = "🔔 ACTIVE" if alert.is_active else "🔕 INACTIVE"
            triggered = "⚠️  TRIGGERED" if alert.is_triggered else ""
            print(f"  {alert.id}. {alert.name} {status} {triggered}")
            print(f"     Type: {alert.alert_type}, Threshold: {alert.threshold_value}")
            if alert.description:
                print(f"     Description: {alert.description}")
        
    except Exception as e:
        print(f"✗ Error querying user data: {e}")
        raise
    finally:
        session.close()


def main():
    """Main execution"""
    print("\n" + "="*60)
    print("User Watchlist & Alerts Example")
    print("="*60)
    
    # Setup database
    db_manager = setup_database_connection()
    
    # Initialize database tables
    print("\n=== Initializing Database Tables ===")
    try:
        db_manager.init_db()
        print("✓ Database tables initialized")
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        sys.exit(1)
    
    # Create example user
    user = create_example_user(db_manager)
    
    # Add watchlist items
    add_watchlist_items(db_manager, user)
    
    # Create alerts
    create_example_alerts(db_manager, user)
    
    # Query and display all data
    query_user_data(db_manager, user)
    
    print("\n" + "="*60)
    print("✓ Example completed successfully!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
