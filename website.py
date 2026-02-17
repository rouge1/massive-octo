# Standard library imports
import sys
import logging
import atexit
from datetime import datetime, timezone
import threading
import subprocess
import os

# Third-party imports
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt, QObject
from PyQt5.QtWidgets import QApplication

# Local application imports
import apps.database as db
from apps.website_ui import Main_Website_Window
from apps.options_server import OptionsServer
from apps import gui_methods as gm

# Configure logger properly
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

# Create a dedicated database manager instance for website.py
db_manager = db.DatabaseManager()

# Store database credentials in memory (session-based, not persisted)
db_credentials = {
    'host': 'localhost',
    'port': 3306,
    'user': None,
    'password': None,
    'database': None
}

# Web server instance
web_server = None

# Store all modified loggers globally for cleanup
modified_loggers = []

def cleanup_logger_handlers():
    """Remove all SignalHandler instances from ALL loggers"""
    global modified_loggers
    
    # Get all loggers that might have our signal handler
    all_loggers = [logging.getLogger()]  # root logger
    for name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(name)
        if isinstance(logger, logging.Logger):
            all_loggers.append(logger)
    
    # Remove signal handler from all loggers
    for logger_inst in all_loggers:
        for handler in logger_inst.handlers[:]:  # Copy the list to avoid modification issues
            try:
                # Check if this is our SignalHandler by checking if it's in modified_loggers
                if any(handler is h for _, h in modified_loggers):
                    logger_inst.removeHandler(handler)
            except (RuntimeError, AttributeError, ValueError):
                # Handler already deleted or not in logger, skip
                pass
    
    modified_loggers.clear()


class BackgroundWorker(QThread):
    """Worker thread for handling web server operations"""
    update_signal = pyqtSignal(str)
    server_started_signal = pyqtSignal(str)  # Emits actual server URL after successful start
    server_failed_signal = pyqtSignal(str)  # Emits error message when server fails to start
    server_stopped_signal = pyqtSignal()  # Emits when server has stopped completely
    start_server_requested = pyqtSignal()
    stop_server_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.server_thread = None
        self.web_server = None
        self.shutdown_event = threading.Event()  # Event to signal server shutdown
        
        # Add signal handler to this module's logger
        self.signal_handler = gm.SignalHandler()
        self.signal_handler.log_signal.connect(self.update_signal.emit)
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
        self.signal_handler.setFormatter(formatter)
        
        # Prevent logging system from trying to close this handler during shutdown
        self.signal_handler.flushOnClose = False
        
        # Add to root logger to catch all logs
        root_logger = logging.getLogger()
        if self.signal_handler not in root_logger.handlers:
            root_logger.addHandler(self.signal_handler)
            modified_loggers.append((root_logger, self.signal_handler))
        
        # Set root logger level to INFO to ensure all logs are captured
        root_logger.setLevel(logging.INFO)
        
        # Remove ALL console handlers from ALL loggers to prevent duplicates
        all_loggers = [logging.getLogger()]  # root logger
        for name in logging.Logger.manager.loggerDict:
            logger_obj = logging.getLogger(name)
            if isinstance(logger_obj, logging.Logger):
                all_loggers.append(logger_obj)
        
        for logger_inst in all_loggers:
            for handler in logger_inst.handlers[:]:
                if isinstance(handler, logging.StreamHandler):
                    logger_inst.removeHandler(handler)
        
        # Connect server control signals
        self.start_server_requested.connect(self._start_server)
        self.stop_server_requested.connect(self._stop_server)
    
    def _add_signal_handler_to_logger(self, logger_instance):
        """Add signal handler to a specific logger"""
        if self.signal_handler not in logger_instance.handlers:
            logger_instance.addHandler(self.signal_handler)
            modified_loggers.append((logger_instance, self.signal_handler))
    
    def run(self):
        """Main worker thread loop"""
        logger.info("Background worker started")
        
        # Keep thread alive to handle signals
        while self.running:
            self.msleep(100)  # Sleep for 100ms
        
        logger.info("Background worker stopped")
    
    def is_server_running(self):
        """Check if the server is currently running"""
        return (self.server_thread is not None and 
                self.server_thread.is_alive() and 
                self.web_server is not None)
    
    def _start_server(self):
        """Start the web server using FastAPI/Uvicorn"""
        if self.server_thread and self.server_thread.is_alive():
            logger.warning("Server is already running")
            return

        try:
            # Clear any previous shutdown signal
            self.shutdown_event.clear()

            # Reload server settings from website_settings.json each time we start
            logger.info("Loading server settings from website_settings.json...")
            host = '0.0.0.0'  # Listen on all interfaces
            port = gm.get_website_port()
            domain = gm.get_website_domain()
            ssl_cert = gm.get_website_ssl_cert()
            ssl_key = gm.get_website_ssl_key()
            protocol = gm.get_website_protocol()

            logger.info(f"Server settings loaded - Port: {port}, Domain: {domain}, Protocol: {protocol}")

            # Import here to avoid circular imports
            from apps.options_server import OptionsServer

            # Create options server instance
            self.web_server = OptionsServer(
                db_manager=db_manager,
                host=host,
                port=port
            )
            
            # Start server in separate thread using asyncio
            import asyncio
            import threading
            
            def run_server():
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Configure uvicorn loggers to use project format instead of uvicorn defaults
                    # This prevents the padded "INFO:     " from uvicorn's %(levelprefix)s
                    project_formatter = logging.Formatter(
                        '%(asctime)s %(levelname)s: %(message)s',
                        datefmt='%Y-%m-%d [%H:%M:%S]'
                    )
                    
                    # Console handler for terminal output (use sys.__stdout__ to bypass any redirects)
                    terminal_handler = logging.StreamHandler(sys.__stdout__)
                    terminal_handler.setFormatter(project_formatter)
                    
                    for uv_name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
                        uv_logger = logging.getLogger(uv_name)
                        uv_logger.handlers.clear()
                        uv_logger.addHandler(terminal_handler)
                        # Also add signal handler for GUI output
                        uv_logger.addHandler(self.signal_handler)
                        uv_logger.setLevel(logging.INFO)
                        uv_logger.propagate = False  # Prevent double logging via root logger
                    
                    import uvicorn

                    # Build uvicorn config
                    uvicorn_kwargs = {
                        'host': host,
                        'port': port,
                        'log_level': 'info',
                        'access_log': True,
                        'log_config': None,  # Use our logging config instead of uvicorn defaults
                    }

                    # Add SSL if cert and key are both configured and the files exist
                    if ssl_cert and ssl_key:
                        if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
                            uvicorn_kwargs['ssl_certfile'] = ssl_cert
                            uvicorn_kwargs['ssl_keyfile'] = ssl_key
                            logger.info(f"SSL enabled: cert={ssl_cert}, key={ssl_key}")
                        else:
                            logger.warning(f"SSL files not found (cert={ssl_cert}, key={ssl_key}), falling back to HTTP")

                    config = uvicorn.Config(self.web_server.app, **uvicorn_kwargs)
                    
                    server = uvicorn.Server(config)
                    
                    async def run_with_shutdown_check():
                        # Start the server
                        task = asyncio.create_task(server.serve())

                        # Check for shutdown event periodically
                        while not task.done() and not self.shutdown_event.is_set():
                            await asyncio.sleep(0.1)

                        # If shutdown was requested, stop the server
                        if self.shutdown_event.is_set() and not task.done():
                            server.should_exit = True
                            try:
                                await asyncio.wait_for(task, timeout=5.0)
                            except asyncio.TimeoutError:
                                task.cancel()

                        return task.result() if task.done() else None
                    
                    loop.run_until_complete(run_with_shutdown_check())
                    
                except Exception as server_error:
                    logger.error(f"Server thread failed to start: {str(server_error)}")
                    # Emit error signal to GUI
                    self.update_signal.emit(f"ERROR: Server failed to start: {str(server_error)}")
                    raise  # Re-raise to ensure thread exits
                
                finally:
                    loop.close()
            
            # Start server in separate thread
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            # Give the server thread a moment to start and check for immediate failures
            import time
            time.sleep(0.5)  # Wait 500ms for thread to initialize
            
            if not self.server_thread.is_alive():
                # Thread died immediately - likely a startup error
                error_msg = "Server thread failed to start - check logs above for details"
                logger.error(error_msg)
                self.server_thread = None
                self.web_server = None
                self.server_failed_signal.emit(error_msg)
                return  # Don't raise, just return and let GUI handle the failure
            
            actual_url = f"{protocol}://{domain}:{port}"
            logger.info(f"Options Tracker server started at {actual_url}")
            
            # Emit signal with actual server URL for GUI to update
            logger.debug(f"Emitting server_started_signal with URL: {actual_url}")
            self.server_started_signal.emit(actual_url)
            logger.debug("server_started_signal emitted successfully")
            
        except Exception as e:
            error_msg = f"Failed to start server: {str(e)}"
            logger.error(error_msg)
            # Emit failure signal so GUI can revert status
            self.server_failed_signal.emit(error_msg)
    
    def _stop_server(self):
        """Stop the web server"""
        if self.server_thread and self.server_thread.is_alive():
            try:
                logger.info("Stopping web server...")
                # Signal the server thread to shutdown
                self.shutdown_event.set()
                
                # Wait for the thread to finish (with timeout)
                self.server_thread.join(timeout=10.0)  # Wait up to 10 seconds
                
                if self.server_thread.is_alive():
                    logger.warning("Server thread did not stop gracefully, it will be terminated when app closes")
                else:
                    logger.info("Web server stopped successfully")
                    logger.info("Settings will be reloaded from website_settings.json on next server start")
                
                self.server_thread = None
                self.web_server = None
                # Reset the shutdown event for next start
                self.shutdown_event.clear()
                
                # Emit signal that server has stopped
                self.server_stopped_signal.emit()
                
            except Exception as e:
                logger.error(f"Error stopping server: {str(e)}")
                # Still emit stopped signal even if there was an error
                self.server_stopped_signal.emit()
        else:
            logger.warning("No server thread to stop")
            # Emit stopped signal since there's nothing running
            self.server_stopped_signal.emit()
    
    def stop(self):
        """Stop the worker thread"""
        self.running = False
        
        # Stop server if running
        if self.web_server:
            self._stop_server()
        
        # Remove signal handler from root logger
        try:
            root_logger = logging.getLogger()
            if self.signal_handler in root_logger.handlers:
                root_logger.removeHandler(self.signal_handler)
        except (RuntimeError, AttributeError):
            # Handler already deleted, skip
            pass


if __name__ == "__main__":
    logger.info("Starting Options Tracker application")
    
    # Record start time in settings file
    start_time_iso = datetime.now(timezone.utc).isoformat()
    gm.save_website_settings(start_time=start_time_iso)
    logger.info(f"Recorded start time: {start_time_iso}")
    
    app = QApplication(sys.argv)
    
    # Create worker first, then pass it and db_manager to Window
    worker = BackgroundWorker()
    window = Main_Website_Window(worker, db_manager)
    
    # Connect cleanup to run before PyQt cleanup
    app.aboutToQuit.connect(cleanup_logger_handlers)
    
    # Start worker thread
    worker.start()
    
    window.show()
    
    # Run the application
    exit_code = app.exec_()
    
    logger.info("Application shutting down...")
    worker.stop()
    worker.wait()  # Wait for thread to finish
    
    sys.exit(exit_code)
