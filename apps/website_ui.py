from datetime import datetime
from PIL import Image, ImageEnhance
import logging
import json
import io

from PyQt5.QtCore import QThread, pyqtSignal, QPoint, Qt, QSize, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QStatusBar, QPushButton,
                             QGroupBox, QApplication, QDialog, QFormLayout,
                             QLineEdit, QSpinBox, QMessageBox, QCheckBox)

from apps.theme import apply_dark_theme
from apps import gui_methods as gm

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class Main_Website_Window(QMainWindow):
    """Main application window for Website Server"""
    
    # ============================================================================
    # INITIALIZATION
    # ============================================================================
    
    def __init__(self, worker, db_manager=None):
        super().__init__()
        self.worker = worker
        self.db_manager = db_manager
        
        # Card visibility flags
        self.db_card_visible = False
        
        # Window setup
        self.setWindowTitle("Option Website Server")
        
        # Load window position from settings (silently, before UI is ready)
        settings = gm.get_website_settings()
        window_pos = settings.get('window_position', {})
        
        # Set window size
        self.resize(
            window_pos.get('width', 800),
            window_pos.get('height', 600)
        )
        
        # Set window position (use move() instead of setGeometry() to properly handle frame)
        self.move(
            window_pos.get('x', 100),
            window_pos.get('y', 100)
        )
        
        # Set window icon
        self.setWindowIcon(QIcon('icons/main_icon.png'))
        
        # Setup UI
        self._setup_ui()
        
        # Connect worker signals (use Qt.QueuedConnection for cross-thread safety)
        if self.worker:
            self.worker.update_signal.connect(self.update_status, Qt.QueuedConnection)
            self.worker.server_started_signal.connect(self.on_server_started, Qt.QueuedConnection)
            self.worker.server_failed_signal.connect(self.on_server_failed, Qt.QueuedConnection)
            self.worker.server_stopped_signal.connect(self.on_server_stopped, Qt.QueuedConnection)
        
        # Log configuration after signals are connected (so logs appear in UI)
        logger.info(f"Configuration loaded:")
        logger.info(f"Window positioned at: x={window_pos.get('x')}, y={window_pos.get('y')}, {window_pos.get('width')}x{window_pos.get('height')}")
        logger.info("Audio Transcription Website Server window initialized")
    
    def _setup_ui(self):
        """Initialize the user interface"""
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Create database connection card
        self.create_database_card(main_layout)
        
        # Create server control card
        self.create_server_control_card(main_layout)
        
        # Create status log
        status_group = QGroupBox("Server Status Log")
        status_group.setFont(QFont("Arial", 14))
        status_group.setStyleSheet("QGroupBox { border: 2px solid #5c5c5c; border-radius: 8px; margin-top: 10px; padding-top: 15px; background-color: transparent; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; }")
        status_layout = QVBoxLayout()
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setFont(QFont("Consolas", 12))
        status_layout.addWidget(self.status_text)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group, stretch=1)
        
        # Apply dark theme
        apply_dark_theme(self)
        
    # ============================================================================
    # STATUS LOG METHODS
    # ============================================================================

    def update_status(self, message):
        """Update the status text display"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Parse log level from message if present
        if ' INFO: ' in message or ' ERROR: ' in message or ' WARNING: ' in message or ' DEBUG: ' in message:
            formatted_message = message
        else:
            formatted_message = f"{timestamp} INFO: {message}"
        
        self.status_text.append(formatted_message)
        self.scroll_status_to_bottom()
    
    def scroll_status_to_bottom(self):
        """Scroll the status text to the bottom"""
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ============================================================================
    # DATABASE CARD UI CREATION
    # ============================================================================

    def create_database_card(self, parent_layout):
        """Create the database connection card with settings button"""
        # Create card container
        db_card = QGroupBox("Database Connection")
        db_card.setFont(QFont("Arial", 14))
        db_card.setStyleSheet("QGroupBox { border: 2px solid #5c5c5c; border-radius: 8px; margin-top: 10px; padding-top: 15px; background-color: transparent; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; }")
        
        # Create main vertical layout for the card
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(10, 0, 10, 10)  # Reduced top margin
        
        # Top section: Settings button in top right corner and info label
        top_layout = QHBoxLayout()
        top_layout.setSpacing(2)  # Reduce spacing between orb and text
        top_layout.setContentsMargins(0, 0, 0, 5)  # Minimal margins
        
        # Status indicator (modern orb)
        self.db_status_indicator = QLabel("●")
        self.db_status_indicator.setFont(QFont("Arial", 28))  # Larger
        self.db_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; margin-top: 3px; margin-right: -2px; }")  # Move up 3px and closer to text
        self.db_status_indicator.setFixedWidth(28)
        self.db_status_indicator.setAlignment(Qt.AlignVCenter | Qt.AlignRight)  # Align to right to get closer
        top_layout.addWidget(self.db_status_indicator)
        
        # Database info label - closer spacing
        self.db_info_label = QLabel("Not connected to database")
        self.db_info_label.setStyleSheet("QLabel { background-color: transparent; color: #cccccc; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
        self.db_info_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_layout.addWidget(self.db_info_label)
        
        top_layout.addStretch()
        
        # Settings button
        self.db_settings_btn = QPushButton()
        icon_path = "icons/settings.png"
        # Process image with PIL
        img = Image.open(icon_path)
        img = img.convert("RGBA")
        
        # Add brightness enhancement
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.2)
        
        datas = img.getdata()
        new_data = []
        threshold = 100
        
        for item in datas:
            if item[0] >= threshold and item[1] >= threshold and item[2] >= threshold:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        
        img.putdata(new_data)
        
        # Convert PIL image to QPixmap
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        
        icon = QIcon(pixmap)
        self.db_settings_btn.setIcon(icon)
        self.db_settings_btn.setIconSize(QSize(40, 40)) 
        self.db_settings_btn.setFixedSize(50, 50)  
        self.db_settings_btn.setStyleSheet("QPushButton { background-color: transparent; border: none; outline: none; } QPushButton:focus { outline: none; }")
        self.db_settings_btn.setToolTip("Configure Database Connection")
        self.db_settings_btn.clicked.connect(self.toggle_database_card)
        
        top_layout.addWidget(self.db_settings_btn, alignment=Qt.AlignTop)  # Align to top
        card_layout.addLayout(top_layout)
        
        # Create collapsible form container
        self.db_card = QWidget()
        form_container_layout = QVBoxLayout()
        form_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Database connection form
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.setSpacing(8)
        
        # Create input fields, pre-filling user/database from last successful login
        saved_db = gm.get_website_settings().get('database', {})

        self.host_field = QLineEdit("localhost")
        self.host_field.setFont(QFont("Arial", 12))

        self.port_field = QSpinBox()
        self.port_field.setFont(QFont("Arial", 12))
        self.port_field.setRange(1, 65535)
        self.port_field.setValue(3306)

        self.user_field = QLineEdit(saved_db.get('user', '') or '')
        self.user_field.setFont(QFont("Arial", 12))

        self.password_field = QLineEdit()
        self.password_field.setFont(QFont("Arial", 12))
        self.password_field.setEchoMode(QLineEdit.Password)
        # Connect Enter key to trigger connect action
        self.password_field.returnPressed.connect(self.db_action_clicked)

        self.database_field = QLineEdit(saved_db.get('name', '') or '')
        self.database_field.setFont(QFont("Arial", 12))
        
        # Add fields to form in order: Host, Port, Database, Username, Password
        host_label = QLabel("Host:")
        host_label.setFont(QFont("Arial", 12))
        host_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(host_label, self.host_field)
        
        port_label = QLabel("Port:")
        port_label.setFont(QFont("Arial", 12))
        port_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(port_label, self.port_field)
        
        db_label = QLabel("Database:")
        db_label.setFont(QFont("Arial", 12))
        db_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(db_label, self.database_field)
        
        user_label = QLabel("Username:")
        user_label.setFont(QFont("Arial", 12))
        user_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(user_label, self.user_field)
        
        password_label = QLabel("Password:")
        password_label.setFont(QFont("Arial", 12))
        password_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        
        # Password field with connect button
        password_row_layout = QHBoxLayout()
        password_row_layout.setSpacing(10)
        password_row_layout.addWidget(self.password_field, 1)
        
        # Connect/Disconnect button
        self.db_action_btn = QPushButton("Connect")
        self.db_action_btn.setFont(QFont("Arial", 12))
        self.db_action_btn.setMinimumWidth(100)
        self.db_action_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        self.db_action_btn.clicked.connect(self.db_action_clicked)
        password_row_layout.addWidget(self.db_action_btn)
        
        form_layout.addRow(password_label, password_row_layout)
        
        form_container_layout.addLayout(form_layout)
        self.db_card.setLayout(form_container_layout)
        
        # Initially hide the form and set max height to 0
        self.db_card.setMaximumHeight(0)
        self.db_card.hide()
        
        card_layout.addWidget(self.db_card)
        
        db_card.setLayout(card_layout)
        parent_layout.addWidget(db_card)
        
        # Update initial status
        self.update_db_status()

    def create_server_control_card(self, parent_layout):
        """Create the server control card"""
        server_card = QGroupBox("Web Server")
        server_card.setFont(QFont("Arial", 14))
        server_card.setStyleSheet("QGroupBox { border: 2px solid #5c5c5c; border-radius: 8px; margin-top: 10px; padding-top: 15px; background-color: transparent; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; }")
        
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(10, 5, 10, 10)  # Match database card margins
        
        # Top section with status indicator and control button
        top_layout = QHBoxLayout()
        top_layout.setSpacing(2)
        top_layout.setContentsMargins(0, 0, 0, 5)
        
        # Status indicator orb (same as database)
        self.server_status_indicator = QLabel("●")
        self.server_status_indicator.setFont(QFont("Arial", 28))
        self.server_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; margin-top: 3px; margin-right: -2px; }")
        self.server_status_indicator.setFixedWidth(28)
        self.server_status_indicator.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        top_layout.addWidget(self.server_status_indicator)
        
        # Server info label
        self.server_info_label = QLabel("Server not running")
        self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #999999; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
        self.server_info_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_layout.addWidget(self.server_info_label)
        
        top_layout.addStretch()
        
        # Single toggle button for Start/Stop
        self.server_toggle_btn = QPushButton("Start Server")
        self.server_toggle_btn.setFont(QFont("Consolas", 12))
        self.server_toggle_btn.setMinimumHeight(40)
        self.server_toggle_btn.setMinimumWidth(120)  # Fixed width so it doesn't resize
        self.server_toggle_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green for start
        self.server_toggle_btn.clicked.connect(self.toggle_server)
        self.server_toggle_btn.setEnabled(False)  # Disabled until DB connected
        top_layout.addWidget(self.server_toggle_btn)
        
        card_layout.addLayout(top_layout)
        
        server_card.setLayout(card_layout)
        parent_layout.addWidget(server_card)

    # ============================================================================
    # DATABASE CONNECTION METHODS
    # ============================================================================
    
    def db_action_clicked(self):
        """Handle database connect/disconnect button click"""
        if self.db_manager and self.db_manager.is_connected():
            # Disconnect
            self.disconnect_database()
        else:
            # Connect
            self.connect_database()
    
    def connect_database(self):
        """Connect to database with provided credentials"""
        from urllib.parse import quote_plus
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        
        host = self.host_field.text().strip()
        port = self.port_field.value()
        user = self.user_field.text().strip()
        password = self.password_field.text()
        database = self.database_field.text().strip()
        
        if not all([host, user, password, database]):
            QMessageBox.warning(self, "Missing Information", "Please fill in all fields")
            return
        
        try:
            # Store credentials
            self.db_manager.db_config = {
                'host': host,
                'port': port,
                'user': user,
                'password': password,
                'database': database
            }
            
            # Create engine
            encoded_password = quote_plus(password)
            mysql_url = f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}"
            self.db_manager.engine = create_engine(mysql_url, pool_pre_ping=True, pool_recycle=3600)
            self.db_manager.Session = sessionmaker(bind=self.db_manager.engine)
            
            # Test connection
            with self.db_manager.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.db_manager._connected = True

            logger.info(f"Successfully connected to database '{database}' at {host}:{port}")
            self.update_db_status()

            # Save last successful DB credentials to settings
            gm.save_website_settings(db_user=user, db_name=database)

            # Save window position when connecting to database
            gm.save_website_settings(
                x=self.pos().x(),
                y=self.pos().y(),
                width=self.width(),
                height=self.height()
            )
            
            # Update button
            self.db_action_btn.setText("Disconnect")
            self.db_action_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; }")
            
            # Enable server toggle button
            self.server_toggle_btn.setEnabled(True)
            
            # Check server status and start if not running
            if self.worker and not self.worker.is_server_running():
                logger.info("Server is not running, starting automatically...")
                self.start_server()
            
            # Hide the database connection form on successful connection
            if self.db_card_visible:
                self.toggle_database_card()
            
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            # Error is already logged, no need for dialog box

    
    def disconnect_database(self):
        """Disconnect from database"""
        try:
            if self.db_manager and self.db_manager.is_connected():
                if self.db_manager.engine:
                    self.db_manager.engine.dispose()
                self.db_manager.engine = None
                self.db_manager.Session = None
                self.db_manager._connected = False
                self.db_manager.db_config = None
                
                logger.info("Database disconnected")
                
                # Update button
                self.db_action_btn.setText("Connect")
                self.db_action_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
                
                # Update status
                self.update_db_status()
                
                # Disable server toggle button
                self.server_toggle_btn.setEnabled(False)
        except Exception as e:
            logger.error(f"Error during disconnection: {str(e)}")
    
    def update_db_status(self):
        """Update database status display"""
        if self.db_manager and self.db_manager.is_connected():
            config = self.db_manager.db_config
            if config:
                self.db_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #00ff88; margin-top: 3px; margin-right: -2px; }")  # Bright green
                self.db_info_label.setText(
                    f"Connected as {config.get('user', 'unknown')} to {config.get('database', 'unknown')} at "
                    f"{config.get('host', 'unknown')}:{config.get('port', 3306)}"
                )
                self.db_info_label.setStyleSheet("QLabel { background-color: transparent; color: #cccccc; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
        else:
            self.db_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; margin-top: 3px; margin-right: -2px; }")  # Bright red
            self.db_info_label.setText("Not connected to database")
            self.db_info_label.setStyleSheet("QLabel { background-color: transparent; color: #999999; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")  # Dimmer gray


    # ============================================================================
    # DATABASE CARD ANIMATION & TOGGLE
    # ============================================================================

    def toggle_database_card(self):
        """Toggle the database connection card with animation"""
        
        # Save window position when settings gear is clicked
        gm.save_website_settings(
            x=self.pos().x(),
            y=self.pos().y(),
            width=self.width(),
            height=self.height()
        )
        
        if self.db_card_visible:
            # Slide out (collapse) database card
            self.animate_card(self.db_card, 0)
            self.db_card_visible = False
        else:
            # Show and slide in (expand) database card
            self.db_card.show()
            # Force layout update to get correct size
            self.db_card.setMaximumHeight(16777215)
            self.db_card.adjustSize()
            QApplication.processEvents()  # Process pending events to update layout
            target_height = self.db_card.sizeHint().height()
            # Start from 0 height
            self.db_card.setMaximumHeight(0)
            # Animate to target height
            self.animate_card(self.db_card, target_height)
            self.db_card_visible = True
    
    def animate_card(self, card, target_height):
        """Animate a card to the target height"""
        # Clear old animations for this card
        if hasattr(self, '_animations'):
            for anim in self._animations[:]:
                if anim.targetObject() == card:
                    anim.stop()
                    self._animations.remove(anim)
        
        animation = QPropertyAnimation(card, b"maximumHeight")
        animation.setDuration(250)  # Slightly faster
        animation.setStartValue(card.maximumHeight())
        animation.setEndValue(target_height)
        animation.setEasingCurve(QEasingCurve.OutCubic)  # Smoother easing
        
        # Store reference to prevent garbage collection
        if not hasattr(self, '_animations'):
            self._animations = []
        self._animations.append(animation)
        
        # Hide the card when animation finishes if collapsing
        if target_height == 0:
            animation.finished.connect(card.hide)
        
        # Start animation
        animation.start()

    # ============================================================================
    # SERVER CONTROL METHODS
    # ============================================================================
    
    def toggle_server(self):
        """Toggle server between start and stop"""
        # Check current state by button text
        if self.server_toggle_btn.text() == "Start Server":
            self.start_server()
        else:
            self.stop_server()
    
    def start_server(self):
        """Start the web server"""
        if self.worker:
            self.worker.start_server_requested.emit()
            # Update toggle button immediately
            self.server_toggle_btn.setText("Stop Server")
            self.server_toggle_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; }")  # Red for stop
            # Show "Starting..." status
            self.server_info_label.setText("Server starting...")
            self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #ffaa00; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
            logger.info("Starting web server...")
    
    def on_server_started(self, server_url):
        """Handle server started signal with actual URL"""
        logger.debug(f"on_server_started called with URL: {server_url}")
        # Update status indicator to green
        self.server_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #00ff88; margin-top: 3px; margin-right: -2px; }")  # Green
        # Update server info with actual URL
        self.server_info_label.setText(f"Server running @ {server_url}")
        self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #cccccc; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
        logger.info(f"GUI updated: Server running @ {server_url}")
    
    def on_server_failed(self, error_message):
        """Handle server failed signal - revert GUI to stopped state"""
        # Revert toggle button to Start state
        self.server_toggle_btn.setText("Start Server")
        self.server_toggle_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green for start
        # Update status indicator to red
        self.server_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; margin-top: 3px; margin-right: -2px; }")  # Red
        # Show error in server info
        self.server_info_label.setText("Server failed to start")
        self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
    
    def on_server_stopped(self):
        """Handle server stopped signal - update GUI to show server is stopped"""
        logger.debug("on_server_stopped called")
        # Update status indicator to red
        self.server_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ff4444; margin-top: 3px; margin-right: -2px; }")  # Red
        # Update server info
        self.server_info_label.setText("Server not running")
        self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #999999; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
        logger.info("GUI updated: Server stopped")
    
    def stop_server(self):
        """Stop the web server"""
        if self.worker:
            # Show "Shutting down..." status immediately
            self.server_info_label.setText("Shutting down...")
            self.server_info_label.setStyleSheet("QLabel { background-color: transparent; color: #ffaa00; font-family: 'Consolas'; font-size: 12px; margin-left: 0px; }")
            # Update status indicator to orange
            self.server_status_indicator.setStyleSheet("QLabel { background-color: transparent; color: #ffaa00; margin-top: 3px; margin-right: -2px; }")  # Orange
            logger.info("Stopping web server...")
            
            # Emit stop signal
            self.worker.stop_server_requested.emit()
            
            # Update toggle button
            self.server_toggle_btn.setText("Start Server")
            self.server_toggle_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green for start
    
    
    # ============================================================================
    # WINDOW EVENT HANDLERS
    # ============================================================================
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Save window position
        gm.save_website_settings(
            x=self.pos().x(),
            y=self.pos().y(),
            width=self.width(),
            height=self.height()
        )
        
        # Stop server if running
        if self.server_toggle_btn.text() == "Stop Server":
            self.stop_server()
        
        event.accept()
