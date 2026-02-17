# Standard library imports
import asyncio
import logging
import sys
import time
import atexit
from datetime import datetime, timezone

# Third-party imports
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt, QObject
from PyQt5.QtWidgets import QApplication

# Local application imports
import apps.database as db
import apps.options_timer as ot
import apps.gui_methods as gm
import apps.app_ui as app_ui

# Configure logger properly
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Console handler (keep existing functionality)
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

# Create a dedicated database manager instance for options_watcher.py
# Each application should have its own DatabaseManager instance
# This allows multiple simultaneous MySQL connections with different users
db_manager = db.DatabaseManager()

# Store database credentials in memory (session-based, not persisted)
db_credentials = {
    'host': 'localhost',
    'port': 3306,
    'user': None,
    'password': None,
    'database': 'options_database'
}

# Store all modified loggers globally for cleanup
modified_loggers = []

def cleanup_logger_handlers():
    """Remove all SignalHandler instances from loggers"""
    global modified_loggers
    try:
        for logger_inst, handlers in modified_loggers:
            for handler in list(logger_inst.handlers):
                if isinstance(handler, gm.SignalHandler):
                    try:
                        logger_inst.removeHandler(handler)
                        # Explicitly close the handler if it has a close method
                        if hasattr(handler, 'close'):
                            handler.close()
                    except (RuntimeError, AttributeError):
                        # Handler already deleted or not accessible
                        pass
        modified_loggers.clear()
    except Exception as e:
        # Silently ignore errors during cleanup to prevent atexit exceptions
        pass

# Register cleanup function to run before Python's logging shutdown
atexit.register(cleanup_logger_handlers)

class BackgroundWorker(QThread):
    """Worker thread for handling async operations"""
    update_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.options_timer = None  # Will be set after DB connection
        
        # Create and configure the signal handler
        self.signal_handler = gm.SignalHandler()
        self.signal_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.signal_handler.log_signal.connect(self.update_signal.emit)
        
        # Add the signal handler to all relevant loggers for Activity Log
        self._add_signal_handler_to_logger(logger)
        self._add_signal_handler_to_logger(logging.getLogger('apps.app_ui'))
        self._add_signal_handler_to_logger(logging.getLogger('apps.options_ui'))
        self._add_signal_handler_to_logger(logging.getLogger('apps.options_timer'))
        self._add_signal_handler_to_logger(logging.getLogger('apps.options_api'))
        self._add_signal_handler_to_logger(logging.getLogger('apps.database'))
        self._add_signal_handler_to_logger(logging.getLogger('apps.gui_methods'))
        
        logger.info("BackgroundWorker initialized")
    
    def _add_signal_handler_to_logger(self, logger_instance):
        """Add signal handler to logger and track it for cleanup"""
        # Save original handlers
        original_handlers = list(logger_instance.handlers)
        
        # Add our signal handler
        logger_instance.addHandler(self.signal_handler)
        
        # Track globally for cleanup
        global modified_loggers
        modified_loggers.append((logger_instance, original_handlers))
    
    def run(self):
        """Run async tasks in background thread"""
        try:
            logger.info("Starting background worker thread")
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the async main function
            loop.run_until_complete(self.async_main())
        except Exception as e:
            logger.error(f"Error in background worker: {e}")
        finally:
            loop.close()
            logger.info("Background worker thread finished")
    
    async def async_main(self):
        """Main async function that runs options polling service"""
        try:
            # Initialize database (but allow startup without connection)
            try:
                logger.info("Checking database connection")
                if db_manager.is_connected():
                    db_manager.init_db()
                    logger.info("Database initialized")
                else:
                    logger.info("Database not connected - use Database button to connect")
            except Exception as e:
                logger.warning(f"Database initialization skipped: {e}")
                logger.info("Database not connected - use Database button to connect")
            
            # Create and run options polling timer
            logger.info("Starting options watchlist polling service")
            self.options_timer = ot.OptionsTimer(db_manager)
            await self.options_timer.run()
            
        except Exception as e:
            logger.error(f"Error in async_main: {e}")
    
    def stop(self):
        """Stop the worker thread and clean up resources"""
        self.running = False
        
        logger.info("Shutting down background worker")
        
        # Clean up signal handler before thread exits
        try:
            if hasattr(self, 'signal_handler') and self.signal_handler:
                # Remove signal handler from all loggers
                for logger_inst, _ in modified_loggers:
                    try:
                        if self.signal_handler in logger_inst.handlers:
                            logger_inst.removeHandler(self.signal_handler)
                    except (RuntimeError, AttributeError):
                        # Handler already deleted or not accessible
                        pass
                
                # Close the signal handler
                if hasattr(self.signal_handler, 'close'):
                    try:
                        self.signal_handler.close()
                    except (RuntimeError, AttributeError):
                        pass
                        
                self.signal_handler = None
        except Exception:
            # Silently ignore cleanup errors
            pass

if __name__ == "__main__":
    logger.info("Starting Options Watchlist application")
    
    # Record start time in settings file
    start_time_iso = datetime.now(timezone.utc).isoformat()
    gm.save_settings(start_time=start_time_iso)
    logger.info(f"Recorded start time: {start_time_iso}")
    
    app = QApplication(sys.argv)
    
    # Create worker first, then pass it and db_manager to App
    worker = BackgroundWorker()
    window = app_ui.Main_App_Window(worker, db_manager)
    
    window.show()
    
    try:
        exit_code = app.exec_()
    finally:
        # Clean up worker before exit
        if worker:
            worker.stop()
            if worker.isRunning():
                worker.wait(3000)  # Wait up to 3 seconds for thread to finish
        
        # Clean up logger handlers
        cleanup_logger_handlers()
    
    sys.exit(exit_code)

