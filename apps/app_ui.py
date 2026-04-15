import logging
import sys
import os
import json
import webbrowser
from datetime import datetime
from PIL import Image, ImageEnhance
import io

from PyQt5.QtCore import QThread, pyqtSignal, QPoint, Qt, QSize, QPropertyAnimation, QEasingCurve, QTimer
from PyQt5.QtGui import QFont, QIcon, QPixmap, QTextCharFormat, QTextCursor, QColor
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QStatusBar, QPushButton,
                             QGroupBox, QApplication, QDialog, QFormLayout,
                             QLineEdit, QSpinBox, QMessageBox, QCheckBox, QFileDialog,
                             QComboBox, QGraphicsOpacityEffect, QInputDialog)

from apps.theme import apply_dark_theme
from apps import gui_methods as gm
from apps import schwab_client

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class Main_App_Window(QMainWindow):
    """Main application window for Options Watchlist Tracker"""
    
    # ============================================================================
    # INITIALIZATION
    # ============================================================================
    
    def __init__(self, worker, db_manager=None):
        super().__init__()
        logger.info("Initializing Options Watchlist Tracker")
        self.setWindowTitle("Options Watchlist Tracker")
        
        # Store reference to the db_manager from watcher
        self.db_manager = db_manager
        
        # Set initial size (will be overridden by load_window_position if settings exist)
        self.setGeometry(100, 100, 600, 400)
        
        # Apply dark theme
        apply_dark_theme(self)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Top layout for title and settings button
        top_layout = QHBoxLayout()
        
        # Activity Log title
        title_label = QLabel("Status Log")
        title_label.setFont(QFont("Arial", 21))
        top_layout.addWidget(title_label)
        
        top_layout.addStretch()  # Push settings button to the right
        
        # Create settings button
        settings_btn = QPushButton()
        icon_path = "icons/settings.png"
        # Process image with PIL
        img = Image.open(icon_path)
        img = img.convert("RGBA")
        
        # Add brightness enhancement
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.2)  # Adjust this value to make it brighter/darker
        
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
        settings_btn.setIcon(icon)
        settings_btn.setFixedSize(40, 40)
        settings_btn.setIconSize(QSize(40, 40))
        settings_btn.setStyleSheet("QPushButton { background-color: transparent; border: none; outline: none; } QPushButton:focus { outline: none; }")
        settings_btn.clicked.connect(self.toggle_database_card)
        top_layout.addWidget(settings_btn)
        
        main_layout.addLayout(top_layout)
        
        # Create a container for status text with search bar overlay
        self.status_container = QWidget()
        status_container_layout = QVBoxLayout(self.status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setSpacing(0)
        
        # Text widget for status messages
        self.status_text = QTextEdit()
        self.status_text.setFont(QFont("Consolas", 12))
        self.status_text.setReadOnly(True)
        self.status_text.setMinimumHeight(125)
        
        status_container_layout.addWidget(self.status_text)
        main_layout.addWidget(self.status_container)
        
        # Create search bar as floating overlay (initially hidden)
        self.search_bar_visible = False
        self.create_search_bar_overlay()
        
        # Create database connection card
        self.db_card_visible = False
        self.create_database_card(main_layout)

        # Create Schwab API card
        self.create_schwab_card(main_layout)


        # Load window position and size from settings
        self.load_window_position()
        
        # Set the worker and connect signals
        self.worker = worker
        self.worker.update_signal.connect(self.update_status)
        logger.info("Starting Main Window worker thread")
        self.worker.start()

    # ============================================================================
    # STATUS LOG METHODS
    # ============================================================================

    def update_status(self, message):
        """Update the status display with a new message
        
        Message comes pre-formatted from SignalHandler as 'LEVEL: message'
        We just add a timestamp prefix.
        """
        logger.debug(f"Status update: {message}")
        
        # Add timestamped message to log
        # Message is already formatted by SignalHandler as "LEVEL: message"
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.status_text.append(formatted_message)
        
        # Auto-scroll to bottom to show newest message
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def scroll_status_to_bottom(self):
        """Scroll the status log to the bottom"""
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ============================================================================
    # DATABASE CARD UI CREATION
    # ============================================================================

    def create_database_card(self, parent_layout):
        """Create the database connection card"""
        # Import here to avoid circular import
        from options_watcher import db_credentials
        
        # Database card
        self.db_card = QGroupBox("Database Connection")
        self.db_card.setFont(QFont("Arial", 14))
        db_layout = QVBoxLayout(self.db_card)
        db_layout.setContentsMargins(15, 15, 15, 15)
        
        # Create form layout for database fields
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.setSpacing(8)
        
        # Create input fields with current values if available
        current = db_credentials or {}
        saved_db = gm.get_settings().get('database', {})

        self.host_field = QLineEdit(current.get('host', 'localhost'))
        self.host_field.setFont(QFont("Arial", 12))
        self.port_field = QSpinBox()
        self.port_field.setRange(1, 65535)
        self.port_field.setValue(current.get('port', 3306))
        self.port_field.setFont(QFont("Arial", 12))

        self.database_field = QLineEdit(current.get('database', '') or saved_db.get('name', '') or '')
        self.database_field.setFont(QFont("Arial", 12))
        self.username_field = QLineEdit(current.get('user', '') or saved_db.get('user', '') or '')
        self.username_field.setFont(QFont("Arial", 12))
        self.password_field = QLineEdit(current.get('password', ''))
        self.password_field.setEchoMode(QLineEdit.Password)
        self.password_field.setFont(QFont("Arial", 12))
        # Connect Enter key to trigger connect action
        self.password_field.returnPressed.connect(self.db_action_clicked)
        
        # Add fields to form
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
        form_layout.addRow(user_label, self.username_field)
        
        # Password row with button
        pass_label = QLabel("Password:")
        pass_label.setFont(QFont("Arial", 12))
        pass_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        
        # Create horizontal layout for password field and button
        password_row_layout = QHBoxLayout()
        password_row_layout.setSpacing(10)
        password_row_layout.addWidget(self.password_field, 1)  # Stretch to fill available space
        
        # Database action button
        self.db_action_btn = QPushButton()
        self.db_action_btn.setFont(QFont("Arial", 12))
        self.db_action_btn.setMinimumWidth(100)
        self.db_action_btn.clicked.connect(self.db_action_clicked)
        self.update_db_button_text()
        password_row_layout.addWidget(self.db_action_btn)
        
        form_layout.addRow(pass_label, password_row_layout)
        
        db_layout.addLayout(form_layout)
        
        # Initially hide the card and set max height to 0
        self.db_card.setMaximumHeight(0)
        self.db_card.hide()
        
        parent_layout.addWidget(self.db_card)



    # ============================================================================
    # SCHWAB CARD UI
    # ============================================================================

    def create_schwab_card(self, parent_layout):
        """Create the Schwab API card below the database card."""
        self.schwab_card = QGroupBox("Schwab API")
        self.schwab_card.setFont(QFont("Arial", 14))
        schwab_layout = QVBoxLayout(self.schwab_card)
        schwab_layout.setContentsMargins(15, 15, 15, 15)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.setSpacing(8)

        # Load saved credentials
        creds = gm.get_schwab_credentials()

        self.schwab_id_field = QLineEdit(creds.get('client_id') or '')
        self.schwab_id_field.setFont(QFont("Arial", 12))
        self.schwab_id_field.setEchoMode(QLineEdit.Password)
        self.schwab_id_field.setPlaceholderText("Put your Charles Schwab App Key here")

        self.schwab_secret_field = QLineEdit(creds.get('client_secret') or '')
        self.schwab_secret_field.setFont(QFont("Arial", 12))
        self.schwab_secret_field.setEchoMode(QLineEdit.Password)
        self.schwab_secret_field.setPlaceholderText("Put your Charles Schwab Secret here")

        saved_callback = gm.get_settings().get('schwab', {}).get('callback_url', '')
        self.schwab_auth_url_field = QLineEdit(saved_callback)
        self.schwab_auth_url_field.setFont(QFont("Arial", 12))
        self.schwab_auth_url_field.setPlaceholderText("Put your redirected Charles Schwab URL here (i.e. https://127.0.0.1:9090/callback?code=...)")

        id_label = QLabel("Client ID:")
        id_label.setFont(QFont("Arial", 12))
        id_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(id_label, self.schwab_id_field)

        secret_label = QLabel("Client Secret:")
        secret_label.setFont(QFont("Arial", 12))
        secret_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(secret_label, self.schwab_secret_field)

        auth_url_label = QLabel("Auth URL:")
        auth_url_label.setFont(QFont("Arial", 12))
        auth_url_label.setStyleSheet("QLabel { background-color: transparent; margin-top: -8px; }")
        form_layout.addRow(auth_url_label, self.schwab_auth_url_field)

        schwab_layout.addLayout(form_layout)

        # Status row
        status_row = QHBoxLayout()
        self.schwab_orb = QLabel()
        self.schwab_orb.setFixedSize(12, 12)
        self.schwab_orb.setStyleSheet("QLabel { border-radius: 6px; background-color: #888888; }")
        self.schwab_status_label = QLabel("Not configured")
        self.schwab_status_label.setFont(QFont("Arial", 11))
        self.schwab_status_label.setStyleSheet("QLabel { background-color: transparent; }")
        status_row.addWidget(self.schwab_orb)
        status_row.addWidget(self.schwab_status_label)
        status_row.addStretch()

        # Info button — tucked into the action row
        info_btn = QPushButton("ⓘ")
        info_btn.setFont(QFont("Arial", 13))
        info_btn.setFlat(True)
        info_btn.setFixedSize(24, 28)
        info_btn.setToolTip("How Schwab credentials work")
        info_btn.setStyleSheet("QPushButton { color: #2196F3; background: transparent; border: none; }")
        info_btn.clicked.connect(self.schwab_info_clicked)
        status_row.addWidget(info_btn)

        # Authorize button (blue) — opens Schwab dev portal or OAuth page
        self.schwab_auth_btn = QPushButton("Authorize")
        self.schwab_auth_btn.setFont(QFont("Arial", 12))
        self.schwab_auth_btn.setMinimumWidth(100)
        self.schwab_auth_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        self.schwab_auth_btn.clicked.connect(self._do_schwab_authorize)

        # Connect/Disconnect button (orange/green)
        self.schwab_disconnect_btn = QPushButton("Disconnect")
        self.schwab_disconnect_btn.setFont(QFont("Arial", 12))
        self.schwab_disconnect_btn.setMinimumWidth(100)
        self.schwab_disconnect_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
        self.schwab_disconnect_btn.clicked.connect(self.schwab_disconnect_clicked)

        # Save button (green) — saves credentials to keyring
        self.schwab_save_btn = QPushButton("Save")
        self.schwab_save_btn.setFont(QFont("Arial", 12))
        self.schwab_save_btn.setMinimumWidth(80)
        self.schwab_save_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        self.schwab_save_btn.clicked.connect(self._do_schwab_save)

        # Delete button (red)
        self.schwab_delete_btn = QPushButton("Delete")
        self.schwab_delete_btn.setFont(QFont("Arial", 12))
        self.schwab_delete_btn.setMinimumWidth(80)
        self.schwab_delete_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; }")
        self.schwab_delete_btn.clicked.connect(self.schwab_delete_clicked)

        status_row.addWidget(self.schwab_auth_btn)
        status_row.addWidget(self.schwab_disconnect_btn)
        status_row.addWidget(self.schwab_save_btn)
        status_row.addWidget(self.schwab_delete_btn)

        schwab_layout.addLayout(status_row)

        self.schwab_card.setMaximumHeight(0)
        self.schwab_card.hide()
        parent_layout.addWidget(self.schwab_card)

        # Track previous status for transition detection
        self._prev_schwab_status = None

        # Reflect current status
        self.update_schwab_status()

        # Periodically refresh Schwab status (catches mid-session token expiry)
        self._schwab_status_timer = QTimer(self)
        self._schwab_status_timer.timeout.connect(self.update_schwab_status)
        self._schwab_status_timer.start(60_000)  # every 60 seconds

    def update_schwab_status(self):
        """Update the Schwab status orb, label, and buttons based on client state."""
        status = schwab_client.get_status()

        # Detect status transitions and log them
        prev = self._prev_schwab_status
        if prev is not None and status != prev:
            if prev == "authorized" and status == "token_expired":
                logger.warning("Schwab token expired — falling back to yfinance")
            elif prev == "authorized" and status == "not_configured":
                logger.warning("Schwab credentials removed — falling back to yfinance")
            elif status == "authorized" and prev != "authorized":
                logger.info("Schwab API connected — using Schwab for data")
            elif status == "token_expired":
                logger.warning("Schwab token expired — click Authorize to reconnect")
            self._write_data_source()
        self._prev_schwab_status = status

        # Orb + label
        if status == "authorized":
            self.schwab_orb.setStyleSheet("QLabel { border-radius: 6px; background-color: #4CAF50; }")
            self.schwab_status_label.setText("Authorized")
        elif status == "token_expired":
            self.schwab_orb.setStyleSheet("QLabel { border-radius: 6px; background-color: #FF9800; }")
            self.schwab_status_label.setText("Token expired — click Authorize")
        elif status == "token_missing":
            self.schwab_orb.setStyleSheet("QLabel { border-radius: 6px; background-color: #FF9800; }")
            self.schwab_status_label.setText("Credentials saved — click Authorize")
        else:
            self.schwab_orb.setStyleSheet("QLabel { border-radius: 6px; background-color: #888888; }")
            self.schwab_status_label.setText("Not configured")

        # Authorize button — always enabled (opens dev portal or OAuth page)
        if status == "authorized":
            self.schwab_auth_btn.setEnabled(False)
            self.schwab_auth_btn.setStyleSheet(
                "QPushButton { background-color: #555555; color: #999999; }")
        else:
            self.schwab_auth_btn.setEnabled(True)
            self.schwab_auth_btn.setStyleSheet(
                "QPushButton { background-color: #2196F3; color: white; }")

        # Connect/Disconnect button
        if status == "authorized":
            self.schwab_disconnect_btn.setText("Disconnect")
            self.schwab_disconnect_btn.setEnabled(True)
            self.schwab_disconnect_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
            try:
                self.schwab_disconnect_btn.clicked.disconnect()
            except TypeError:
                pass
            self.schwab_disconnect_btn.clicked.connect(self.schwab_disconnect_clicked)
        elif status == "token_expired":
            self.schwab_disconnect_btn.setText("Reconnect")
            self.schwab_disconnect_btn.setEnabled(True)
            self.schwab_disconnect_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
            try:
                self.schwab_disconnect_btn.clicked.disconnect()
            except TypeError:
                pass
            self.schwab_disconnect_btn.clicked.connect(self.schwab_reconnect_clicked)
        else:
            self.schwab_disconnect_btn.setText("Disconnect")
            self.schwab_disconnect_btn.setEnabled(False)
            self.schwab_disconnect_btn.setStyleSheet("QPushButton { background-color: #555555; color: #999999; }")

        # Save button — enabled when credentials are entered but not yet saved, or to update
        has_fields = bool(self.schwab_id_field.text().strip() and self.schwab_secret_field.text().strip())
        self.schwab_save_btn.setEnabled(has_fields and status != "authorized")
        if has_fields and status != "authorized":
            self.schwab_save_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        else:
            self.schwab_save_btn.setStyleSheet("QPushButton { background-color: #555555; color: #999999; }")

        # Delete button: enabled unless nothing is configured
        self.schwab_delete_btn.setEnabled(status != "not_configured")

        # Auth URL field — show saved callback URL; read-only when authorized
        if status == "authorized":
            self.schwab_auth_url_field.setReadOnly(True)
        else:
            self.schwab_auth_url_field.setReadOnly(False)

    def schwab_info_clicked(self):
        """Show info dialog explaining Schwab credential setup."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Schwab API — How It Works")
        msg.setIcon(QMessageBox.Information)
        msg.setText(
            "<b>Two sets of credentials are required:</b><br><br>"

            "<b>1. App Key &amp; Secret</b> (from developer.schwab.com)<br>"
            "Schwab calls these <i>App Key</i> and <i>Secret</i> in their portal — "
            "enter them in the Client ID and Client Secret fields here. "
            "These identify your registered application and are stored encrypted "
            "in your system keychain. They are needed on every startup so the app "
            "can silently refresh your trading session every 30 minutes.<br><br>"

            "<b>2. Trading Account Login</b> (your normal schwab.com login)<br>"
            "Click <b>Authorize</b> to open a Schwab login page in your browser. "
            "Sign in with your Schwab brokerage credentials (the same ones you use "
            "at schwab.com). Schwab will redirect your browser to a URL starting "
            "with <tt>https://127.0.0.1:9090/callback?code=...</tt> — copy that "
            "full URL from the browser address bar, paste it into the <b>Auth URL</b> "
            "field, then click <b>Authorize</b> again. This one-time step creates an "
            "OAuth token stored encrypted in your keychain. The token auto-renews "
            "and you will not need to log in again unless the app is offline for "
            "more than 7 days."
        )
        msg.setTextFormat(Qt.RichText)
        msg.exec_()

    def _do_schwab_save(self):
        """Save Schwab credentials to keyring."""
        client_id = self.schwab_id_field.text().strip()
        client_secret = self.schwab_secret_field.text().strip()
        if not client_id or not client_secret:
            logger.warning("Schwab: Client ID and Client Secret are required")
            return
        gm.save_schwab_credentials(client_id, client_secret)
        schwab_client.init(client_id, client_secret)
        self.update_schwab_status()
        logger.info("Schwab credentials saved")

    def _do_schwab_authorize(self):
        """Open Schwab dev portal (if no credentials) or OAuth page, or complete auth."""
        status = schwab_client.get_status()

        # No credentials — open the developer portal
        if status == "not_configured":
            webbrowser.open("https://developer.schwab.com")
            logger.info("Opened Schwab developer portal — copy your Client ID and Client Secret, paste them here, then click Save")
            return

        client_id = self.schwab_id_field.text().strip()
        client_secret = self.schwab_secret_field.text().strip()
        if not client_id or not client_secret:
            webbrowser.open("https://developer.schwab.com")
            logger.info("Opened Schwab developer portal — copy your Client ID and Client Secret")
            return

        # Check if callback URL is pasted — if so, complete auth
        received_url = self.schwab_auth_url_field.text().strip()
        if received_url:
            success = schwab_client.complete_auth(client_id, client_secret, received_url)
            self._write_data_source()
            self.update_schwab_status()
            if success:
                gm.save_settings(schwab_callback_url=received_url)
                logger.info("Schwab authorization complete")
            else:
                logger.error("Schwab authorization failed — check logs for details")
            return

        # No callback URL yet — open browser with OAuth page
        schwab_client.init(client_id, client_secret)
        auth_url = schwab_client.get_auth_url(client_id)
        webbrowser.open(auth_url)
        logger.info("Schwab browser opened for authorization — paste callback URL and click Authorize again")

    def _write_data_source(self):
        """Write current data source to website_settings.json so the web server can read it."""
        try:
            import json, os
            settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'website_settings.json')
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    ws = json.load(f)
                ws['data_source'] = 'schwab' if schwab_client.is_available() else 'yfinance'
                with open(settings_path, 'w') as f:
                    json.dump(ws, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write data_source: {e}")

    def schwab_disconnect_clicked(self):
        """Drop the in-memory Schwab client — falls back to yfinance without deleting credentials."""
        schwab_client.disconnect()
        self._write_data_source()
        self.update_schwab_status()
        logger.info("Schwab disconnected — falling back to yfinance")

    def schwab_reconnect_clicked(self):
        """Re-initialize Schwab client from keyring credentials."""
        creds = gm.get_schwab_credentials()
        if creds and creds.get('client_id') and creds.get('client_secret'):
            schwab_client.init(creds['client_id'], creds['client_secret'])
            self._write_data_source()
            self.update_schwab_status()
            if schwab_client.is_available():
                logger.info("Schwab reconnected")
            else:
                logger.warning("Schwab reconnect failed — token may be expired")
        else:
            logger.warning("No Schwab credentials found in keyring")

    def schwab_delete_clicked(self):
        """Confirm and delete all Schwab credentials, resetting to not_configured."""
        reply = QMessageBox.question(
            self, "Delete Schwab Credentials",
            "This will remove all saved Schwab credentials and tokens.\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        gm.delete_schwab_credentials()
        schwab_client.reset()
        self._write_data_source()
        self.schwab_id_field.clear()
        self.schwab_secret_field.clear()
        self.schwab_auth_url_field.clear()
        self.update_schwab_status()
        logger.info("Schwab credentials deleted")

    def create_search_bar_overlay(self):
        """Create the search bar widget as a floating overlay - VS Code style"""
        from PyQt5.QtWidgets import QHBoxLayout, QLabel
        
        # Search bar container with dark background - floating overlay
        self.search_bar = QWidget(self.status_container)
        self.search_bar.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border: 1px solid #454545;
                border-radius: 4px;
            }
        """)
        search_layout = QHBoxLayout(self.search_bar)
        search_layout.setContentsMargins(8, 4, 8, 4)
        search_layout.setSpacing(6)
        
        # Search input field with placeholder
        self.search_field = QLineEdit()
        self.search_field.setFont(QFont("Consolas", 11))
        self.search_field.setPlaceholderText("Search (press Enter ⏎)")
        self.search_field.setMinimumWidth(200)
        self.search_field.setMaximumWidth(300)
        self.search_field.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                border: 1px solid #3c3c3c;
                border-radius: 3px;
                padding: 4px 6px;
                color: #cccccc;
                selection-background-color: #0e639c;
            }
            QLineEdit:focus {
                border: 1px solid #0e639c;
            }
        """)
        self.search_field.returnPressed.connect(self.perform_search)
        
        # Counter label (x of y)
        self.search_counter = QLabel("0 of 0")
        self.search_counter.setFont(QFont("Consolas", 11))
        self.search_counter.setMinimumWidth(45)
        self.search_counter.setStyleSheet("QLabel { color: #cccccc; background-color: transparent; border: none; padding-bottom: 6px; }")
        
        # Previous match button (up arrow)
        self.search_prev_btn = QLabel()
        self.search_prev_btn.setPixmap(QPixmap("icons/uparrow.png").scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.search_prev_btn.setFixedSize(20, 20)
        self.search_prev_btn.setAlignment(Qt.AlignCenter)
        self.search_prev_btn.setStyleSheet("""
            QLabel {
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QLabel:hover {
                background-color: #3e3e3e;
            }
        """)
        self.search_prev_btn.setToolTip("Previous match (Shift+F3)")
        self.search_prev_btn.setCursor(Qt.PointingHandCursor)
        self.search_prev_btn.mousePressEvent = lambda event: self.previous_search_match()
        
        # Next match button (down arrow)
        self.search_next_btn = QLabel()
        self.search_next_btn.setPixmap(QPixmap("icons/downarrow.png").scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.search_next_btn.setFixedSize(20, 20)
        self.search_next_btn.setAlignment(Qt.AlignCenter)
        self.search_next_btn.setStyleSheet("""
            QLabel {
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QLabel:hover {
                background-color: #3e3e3e;
            }
        """)
        self.search_next_btn.setToolTip("Next match (F3)")
        self.search_next_btn.setCursor(Qt.PointingHandCursor)
        self.search_next_btn.mousePressEvent = lambda event: self.next_search_match()
        
        # Close button (X icon)
        self.search_close_btn = QLabel()
        self.search_close_btn.setPixmap(QPixmap("icons/close.png").scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.search_close_btn.setFixedSize(20, 20)
        self.search_close_btn.setAlignment(Qt.AlignCenter)
        self.search_close_btn.setStyleSheet("""
            QLabel {
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QLabel:hover {
                background-color: #3e3e3e;
            }
        """)
        self.search_close_btn.setToolTip("Close search (Esc)")
        self.search_close_btn.setCursor(Qt.PointingHandCursor)
        self.search_close_btn.mousePressEvent = lambda event: self.toggle_search_bar()
        
        # Add widgets to layout
        search_layout.addWidget(self.search_field)
        search_layout.addWidget(self.search_counter)
        search_layout.addWidget(self.search_prev_btn)
        search_layout.addWidget(self.search_next_btn)
        search_layout.addWidget(self.search_close_btn)
        
        # Size and position the search bar
        self.search_bar.adjustSize()
        self.search_bar.hide()
        
        # Position it in top-right corner when shown
        self.position_search_bar()
    
    def position_search_bar(self):
        """Position the search bar in the top-right corner of the status container"""
        if not hasattr(self, 'search_bar') or not self.status_container:
            return
        
        # Get container dimensions
        container_width = self.status_container.width()
        
        # Size search bar to be about 1/3 of container width (adjust as needed)
        search_bar_width = min(400, int(container_width * 0.4))
        self.search_bar.setFixedWidth(search_bar_width)
        
        # Position in top-right corner with some padding
        x_pos = container_width - search_bar_width - 10  # 10px padding from right
        y_pos = 10  # 10px padding from top
        
        self.search_bar.move(x_pos, y_pos)
    
    def resizeEvent(self, event):
        """Handle window resize to reposition search bar"""
        super().resizeEvent(event)
        if hasattr(self, 'search_bar') and self.search_bar_visible:
            self.position_search_bar()

    # ============================================================================
    # DATABASE CARD ANIMATION & TOGGLE
    # ============================================================================

    def toggle_database_card(self):
        """Toggle the database connection card and Schwab card together."""

        # Save window position and size when settings gear is clicked
        self.save_window_position()

        if self.db_card_visible:
            self.animate_card(self.db_card, 0)
            self.animate_card(self.schwab_card, 0)
            self.db_card_visible = False
        else:
            self.db_card.show()
            self.schwab_card.show()
            self.animate_card(self.db_card, self.db_card.sizeHint().height())
            self.animate_card(self.schwab_card, self.schwab_card.sizeHint().height())
            self.db_card_visible = True
    
    def animate_card(self, card, target_height):
        """Animate a card to the target height"""
        animation = QPropertyAnimation(card, b"maximumHeight")
        animation.setDuration(300)
        animation.setStartValue(card.maximumHeight())
        animation.setEndValue(target_height)
        animation.setEasingCurve(QEasingCurve.InOutQuad)
        animation.start()
        
        # Store reference to prevent garbage collection
        if not hasattr(self, '_animations'):
            self._animations = []
        self._animations.append(animation)
        
        # Hide the card when animation finishes if collapsing
        if target_height == 0:
            animation.finished.connect(card.hide)
        
        # Scroll to bottom after animation completes
        animation.finished.connect(self.scroll_status_to_bottom)
    

    
    # ============================================================================
    # DATABASE STATUS INDICATORS
    # ============================================================================
    
    def update_db_button_text(self):
        """Update the database button text and color based on connection status"""
        try:
            if self.db_manager and self.db_manager.is_connected():
                self.db_action_btn.setText("Disconnect")
                self.db_action_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; }")  # Red
            else:
                self.db_action_btn.setText("Connect")
                self.db_action_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green
        except Exception as e:
            logger.debug(f"Error updating button text: {e}")
            self.db_action_btn.setText("Connect")
            self.db_action_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green
    
    # ============================================================================
    # DATABASE ACTION HANDLERS
    # ============================================================================
    
    def db_action_clicked(self):
        """Handle database connect/disconnect button click"""
        try:
            if self.db_manager and self.db_manager.is_connected():
                # Disconnect
                self.disconnect_database()
            else:
                # Connect
                credentials = self.get_credentials()
                self.connect_database(credentials)
        except Exception as e:
            logger.debug(f"Error in db_action_clicked: {e}")
            # Fallback to connect if we can't determine status
            credentials = self.get_credentials()
            self.connect_database(credentials)
        
        # Update button text after action
        self.update_db_button_text()
    
    def get_credentials(self):
        """Return the entered credentials"""
        return {
            'host': self.host_field.text().strip(),
            'port': self.port_field.value(),
            'database': self.database_field.text().strip(),
            'user': self.username_field.text().strip(),
            'password': self.password_field.text().strip()
        }

    # ============================================================================
    # DATABASE CONNECTION METHODS
    # ============================================================================
    
    def connect_database(self, credentials):
        """Connect to database with provided credentials"""
        try:
            # Use the db_manager instance from watcher (passed via __init__)
            # Import db_credentials to update them
            from options_watcher import db_credentials
            from urllib.parse import quote_plus
            from sqlalchemy import create_engine, text
            from sqlalchemy.orm import sessionmaker
            
            if self.db_manager is None:
                logger.error("No db_manager instance available")
                return
            
            # Store credentials
            db_credentials.update(credentials)
            
            # Set up database manager config
            self.db_manager.db_config = credentials
            
            # Create connection URL
            encoded_password = quote_plus(credentials['password'])
            mysql_url = f"mysql+pymysql://{credentials['user']}:{encoded_password}@{credentials['host']}:{credentials['port']}/{credentials['database']}"
            
            # Create engine and test connection
            self.db_manager.engine = create_engine(
                mysql_url,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            
            # Initialize session
            self.db_manager.Session = sessionmaker(bind=self.db_manager.engine)
            
            # Test the connection
            with self.db_manager.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.db_manager._connected = True
            logger.info(f"✓ Database connection established successfully (db_manager: {id(self.db_manager)})")

            # Save last successful DB credentials to settings
            gm.save_settings(db_user=credentials['user'], db_name=credentials['database'])

            # Save window position when connecting to database
            self.save_window_position()
            
            # Check and initialize schema if needed
            schema_check = self.db_manager.check_schema()
            if not schema_check['has_tables']:
                logger.info("Empty database detected - creating tables")
                self.db_manager.init_db()
                logger.info("Database connected and tables created successfully")
            else:
                logger.info("Database schema verified - tables exist")
            
        except Exception as e:
            error_msg = f"Failed to connect to database: {str(e)}"
            logger.error(error_msg)
    
    def disconnect_database(self):
        """Disconnect from database"""
        try:
            # Import db_credentials to clear them
            from options_watcher import db_credentials
            
            if self.db_manager and self.db_manager.is_connected():
                if self.db_manager.engine:
                    self.db_manager.engine.dispose()
                self.db_manager.engine = None
                self.db_manager.Session = None
                self.db_manager._connected = False
                self.db_manager.db_config = None
                
                # Clear stored credentials
                db_credentials.update({
                    'host': 'localhost',
                    'port': 3306,
                    'user': None,
                    'password': None,
                    'database': None
                })
                
                logger.info("Database disconnected")
            else:
                logger.info("Database is not currently connected.")
                
        except Exception as e:
            error_msg = f"Error during disconnection: {str(e)}"
            logger.error(error_msg)

    # ============================================================================
    # WINDOW POSITION & SIZE MANAGEMENT
    # ============================================================================

    def center_window(self):
        """Center the window on the screen taking up about 1/2 of screen size"""
        # Get the screen geometry
        screen = QApplication.primaryScreen().geometry()
        
        # Set window size to about half the screen
        window_width = int(screen.width() * 0.5)
        window_height = int(screen.height() * 0.5)
        
        # Ensure minimum size
        window_width = max(window_width, 800)
        window_height = max(window_height, 600)
        
        # Resize the window
        self.resize(window_width, window_height)
        
        # Calculate center position
        window_geometry = self.frameGeometry()
        center_point = screen.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())
        
    def save_window_position(self):
        """Save the current window position and size to settings file"""
        try:
            gm.save_settings(
                x=self.pos().x(),
                y=self.pos().y(),
                width=self.width(),
                height=self.height()
            )
            logger.debug(f"Window position saved: x={self.pos().x()}, y={self.pos().y()}, w={self.width()}, h={self.height()}")
        except Exception as e:
            logger.error(f"Error saving window position: {e}")
            
    def load_window_position(self):
        """Load the saved window position and size from settings file or center if none exists"""
        try:
            settings = gm.get_settings()
            position = settings.get('window_position', {})
            screen = QApplication.primaryScreen().geometry()
            
            # Restore size if saved and valid
            width = position.get('width', 800)
            height = position.get('height', 600)
            # Ensure size is within reasonable bounds
            width = min(max(width, 600), screen.width())
            height = min(max(height, 400), screen.height())
            self.resize(width, height)
            
            # Restore position if valid (check after resize to use correct dimensions)
            x = position.get('x', 100)
            y = position.get('y', 100)
            if (0 <= x <= screen.width() - self.width() and 
                0 <= y <= screen.height() - self.height()):
                self.move(QPoint(x, y))
                logger.debug(f"Window position restored: {position}")
            else:
                logger.debug("Saved position is off-screen, centering window")
                self.center_window()
        except Exception as e:
            logger.error(f"Error loading window position: {e}")
            self.center_window()
    
    # ============================================================================
    # WINDOW EVENT HANDLERS
    # ============================================================================
            
    def closeEvent(self, event):
        """Handle application closing"""
        logger.info("Application closing - cleaning up")
        
        # Save window position before closing
        self.save_window_position()
        
        if hasattr(self, 'worker'):
            logger.info("Terminating background worker")
            self.worker.stop()
            self.worker.wait(5000)  # Wait up to 5 seconds for thread to finish
        logger.info("Application closed")
        event.accept()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            # Ctrl+F - toggle search bar
            self.toggle_search_bar()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            if self.search_bar_visible:
                # First Escape - close search bar
                self.toggle_search_bar()
            elif self.db_card_visible:
                # Second Escape - close settings cards
                self.toggle_database_card()
            event.accept()
        elif event.key() == Qt.Key_F3 and self.search_bar_visible:
            # F3 - next search match
            if event.modifiers() == Qt.ShiftModifier:
                self.previous_search_match()
            else:
                self.next_search_match()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ============================================================================
    # SEARCH BAR METHODS
    # ============================================================================
    
    def toggle_search_bar(self):
        """Toggle the search bar visibility with slide animation"""
        if self.search_bar_visible:
            # Clear search highlighting first
            self.clear_search_highlights()
            self.search_field.clear()
            # Reset search counter
            self.update_search_counter(0, 0)
            # Animate sliding up (out)
            self.animate_search_bar(slide_in=False)
            self.search_bar_visible = False
        else:
            # Show search bar first (but position it off-screen)
            self.search_bar.show()
            # Animate sliding down (in)
            self.animate_search_bar(slide_in=True)
            self.search_bar_visible = True
            # Focus on search field after animation starts
            self.search_field.setFocus()
    
    def animate_search_bar(self, slide_in=True):
        """Animate the search bar sliding in or out from the top"""
        from PyQt5.QtCore import QPropertyAnimation
        
        # Get the final position
        container_width = self.status_container.width()
        search_bar_width = min(400, int(container_width * 0.4))
        self.search_bar.setFixedWidth(search_bar_width)
        
        final_x = container_width - search_bar_width - 25
        final_y = 5
        
        if slide_in:
            # Start above the visible area
            start_y = -self.search_bar.height() - 10
            end_y = final_y
            # Set initial position before animating
            self.search_bar.move(final_x, start_y)
        else:
            # End above the visible area
            start_y = final_y
            end_y = -self.search_bar.height() - 10
        
        # Create animation
        self.search_animation = QPropertyAnimation(self.search_bar, b"pos")
        self.search_animation.setDuration(250)
        self.search_animation.setStartValue(QPoint(final_x, start_y))
        self.search_animation.setEndValue(QPoint(final_x, end_y))
        self.search_animation.setEasingCurve(QEasingCurve.OutCubic if slide_in else QEasingCurve.InCubic)
        
        # Hide the search bar when animation finishes (if sliding out)
        if not slide_in:
            self.search_animation.finished.connect(self.search_bar.hide)
        
        self.search_animation.start()
    
    def perform_search(self):
        """Perform search and update highlights"""
        search_text = self.search_field.text()
        
        if not search_text:
            self.clear_search_highlights()
            self.update_search_counter(0, 0)
            return
        
        # Clear previous highlights
        self.clear_search_highlights()
        
        # Find all matches (case insensitive)
        content = self.status_text.toPlainText()
        search_lower = search_text.lower()
        content_lower = content.lower()
        
        # Find all occurrences
        self.search_matches = []
        start = 0
        while True:
            pos = content_lower.find(search_lower, start)
            if pos == -1:
                break
            self.search_matches.append((pos, len(search_text)))
            start = pos + 1
        
        # Highlight all matches
        if self.search_matches:
            cursor = self.status_text.textCursor()
            for match_pos, match_len in self.search_matches:
                cursor.setPosition(match_pos)
                cursor.setPosition(match_pos + match_len, QTextCursor.KeepAnchor)
                format_highlight = QTextCharFormat()
                format_highlight.setBackground(QColor(150, 70, 70))  # Dark red-gray
                cursor.mergeCharFormat(format_highlight)
            
            # Set current match to first one
            self.current_match_index = 0
            self.highlight_current_match()
        else:
            self.current_match_index = -1
        
        self.update_search_counter(len(self.search_matches), 
                                 self.current_match_index + 1 if self.search_matches else 0)
    
    def clear_search_highlights(self):
        """Clear all search highlights"""
        cursor = self.status_text.textCursor()
        cursor.select(QTextCursor.Document)
        format_clear = QTextCharFormat()
        format_clear.setBackground(Qt.transparent)
        cursor.mergeCharFormat(format_clear)
        self.search_matches = []
        self.current_match_index = -1
    
    def highlight_current_match(self):
        """Highlight the current match with different color"""
        if not hasattr(self, 'search_matches') or not self.search_matches or self.current_match_index < 0:
            return
        
        # First, re-apply all dark red-gray highlights
        cursor = self.status_text.textCursor()
        for match_pos, match_len in self.search_matches:
            cursor.setPosition(match_pos)
            cursor.setPosition(match_pos + match_len, QTextCursor.KeepAnchor)
            format_highlight = QTextCharFormat()
            format_highlight.setBackground(QColor(100, 70, 70))  # Dark red-gray
            cursor.mergeCharFormat(format_highlight)
        
        # Then highlight current match with different color (blue background)
        current_pos, current_len = self.search_matches[self.current_match_index]
        cursor.setPosition(current_pos)
        cursor.setPosition(current_pos + current_len, QTextCursor.KeepAnchor)
        format_current = QTextCharFormat()
        format_current.setBackground(Qt.blue)
        cursor.mergeCharFormat(format_current)
        
        # Scroll to current match
        cursor.setPosition(current_pos)
        self.status_text.setTextCursor(cursor)
        self.status_text.ensureCursorVisible()
    
    def next_search_match(self):
        """Go to next search match"""
        if not hasattr(self, 'search_matches') or not self.search_matches:
            return
        
        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self.highlight_current_match()
        self.update_search_counter(len(self.search_matches), self.current_match_index + 1)
    
    def previous_search_match(self):
        """Go to previous search match"""
        if not hasattr(self, 'search_matches') or not self.search_matches:
            return
        
        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self.highlight_current_match()
        self.update_search_counter(len(self.search_matches), self.current_match_index + 1)
    
    def update_search_counter(self, total_matches, current_match):
        """Update the search counter display"""
        if total_matches == 0:
            self.search_counter.setText("0 of 0")
        else:
            self.search_counter.setText(f"{current_match} of {total_matches}")

    # ============================================================================
    # DATABASE CARD ANIMATION & TOGGLE
    # ============================================================================