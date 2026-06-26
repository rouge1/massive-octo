import logging
import sys
import os
import json
import webbrowser
from datetime import datetime
from PIL import Image, ImageEnhance
import io

from PyQt5.QtCore import (QThread, pyqtSignal, pyqtProperty, QPoint, Qt, QSize,
                          QPropertyAnimation, QEasingCurve, QTimer, QRectF, QPointF)
from PyQt5.QtGui import (QFont, QIcon, QPixmap, QTextCharFormat, QTextCursor, QColor,
                         QPainter, QPen, QBrush)
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QStatusBar, QPushButton,
                             QGroupBox, QApplication, QDialog, QFormLayout,
                             QLineEdit, QSpinBox, QMessageBox, QCheckBox, QFileDialog,
                             QComboBox, QGraphicsOpacityEffect, QInputDialog, QFrame)

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


# ============================================================================
# SCHWAB CONNECTION-STATE VISUAL LANGUAGE
# ============================================================================
# A cool semaphore, deliberately not the green/amber binary. Amber is reserved
# for the one state that needs the user (expired); azure separates "saved but
# never authorized" from "was connected, now lapsed".
SCHWAB_STATE_COLORS = {
    "not_configured": "#5B6573",  # steel  — inert, nothing entered
    "token_missing":  "#36C5F0",  # azure  — credentials saved, ready to authorize
    "token_expired":  "#E8A33D",  # amber  — was connected, session lapsed
    "token_revoked":  "#DA3633",  # red    — refresh token revoked, must re-auth from Step 1
    "authorized":     "#3FB950",  # green  — streaming
}

# Fixed background tint per stepper section so the three steps read as distinct
# cards. The UI is already saturated with green/gray, so the steps use a separate
# blue -> yellow -> orange ramp. These are independent of the banner's
# state-semaphore colours (steel/azure/amber/green), which live elsewhere.
SCHWAB_STEP_TINTS = {
    1: (59, 130, 246),   # blue       — App Key & Secret
    2: (198, 150, 36),   # dark gold  — Authorize (toned down: was a too-bright yellow)
    3: (249, 115, 22),   # orange     — Connection
}
# Per-step fill opacity multiplier — step 2 reads softer than the others.
SCHWAB_STEP_ALPHA = {1: 1.0, 2: 0.7, 3: 1.0}

# Banner copy per state: (state name, plain-language message).
SCHWAB_STATE_META = {
    "authorized":     ("LIVE",           "Streaming Schwab market data."),
    "token_expired":  ("EXPIRED",        "Session lapsed — click Authorize to reconnect."),
    "token_revoked":  ("RE-AUTH NEEDED", "Refresh token revoked — start at Step 1 and re-authorize."),
    "token_missing":  ("READY",          "Credentials saved — click Authorize to connect."),
    "not_configured": ("NOT CONFIGURED", "Add your Schwab App Key & Secret to begin."),
}


class SelectAllLineEdit(QLineEdit):
    """QLineEdit that selects all its text on focus so typing/pasting REPLACES the
    existing value instead of appending. Used for the Schwab credential fields: those
    are pre-filled (echo=Password, shown as dots), and pasting a key onto the existing
    value silently corrupts it (App Key grows past 32 chars → Schwab 'invalid_client')."""

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Defer to after the focusing click is processed — otherwise the click
        # repositions the cursor and clears the selection we just made.
        QTimer.singleShot(0, self.selectAll)


class SchwabStateIndicator(QWidget):
    """Custom-painted connection-state glyph.

    Distinct by silhouette, not only colour, so the state reads at a glance and
    survives colour-blindness:
      not_configured  hollow steel ring        (inert / off)
      token_missing   azure ring + go-chevron   (ready, proceed)
      token_expired   broken amber ring + "!"   (lapsed, needs attention)
      authorized      solid green node + pulse  (live / streaming)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # only the glyph paints; banner tint shows through
        self._state = "not_configured"
        self._pulse = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._advance_pulse)

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        # The pulse animation is the one moving element; only the live state earns it.
        if state == "authorized":
            self._pulse = 0.0
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _advance_pulse(self):
        self._pulse = (self._pulse + 0.025) % 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(SCHWAB_STATE_COLORS.get(self._state, SCHWAB_STATE_COLORS["not_configured"]))
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = min(cx, cy) - 6.0  # ring radius, leaving room for the live halo

        if self._state == "authorized":
            # expanding, fading halo around a solid node
            halo = QColor(color)
            halo.setAlphaF(max(0.0, 0.40 * (1.0 - self._pulse)))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            halo_r = r + self._pulse * 8.0
            p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)
            p.setBrush(color)
            p.drawEllipse(QPointF(cx, cy), r - 1.0, r - 1.0)
            return

        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if self._state in ("token_expired", "token_revoked"):
            # broken ring (gap near the top) + exclamation — "needs attention".
            # token_revoked paints in red (per SCHWAB_STATE_COLORS) to read as more severe.
            rectf = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            p.drawArc(rectf, int(120 * 16), int(300 * 16))  # 60° gap straddling the top
            p.drawLine(QPointF(cx, cy - r * 0.40), QPointF(cx, cy + r * 0.12))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(cx, cy + r * 0.42), 1.4, 1.4)
        elif self._state == "token_missing":
            # full ring + right-pointing chevron (proceed to next step)
            p.drawEllipse(QPointF(cx, cy), r, r)
            ch = r * 0.42
            p.drawLine(QPointF(cx - ch * 0.5, cy - ch), QPointF(cx + ch * 0.65, cy))
            p.drawLine(QPointF(cx + ch * 0.65, cy), QPointF(cx - ch * 0.5, cy + ch))
        else:  # not_configured
            p.drawEllipse(QPointF(cx, cy), r, r)


class SchwabStepFrame(QFrame):
    """A stepper-section container that paints its own border.

    At rest only the **top + left** edges are coloured (in the step's hue). When the
    step opens, the `trace` property animates 0->1 and a light "runs" across the
    **bottom** edge (left->right) then up the **right** edge, completing the box —
    closing animates it back. Background tint deepens when the step is open.
    """

    def __init__(self, rgb, parent=None, alpha_scale=1.0):
        super().__init__(parent)
        self._rgb = tuple(rgb)
        self._alpha_scale = alpha_scale  # per-step fill opacity multiplier
        self._bg_alpha = 0.16 * alpha_scale
        self._open = False
        self._trace = 0.0  # 0..1 progress of the bottom+right "running light"

    def setHue(self, rgb):
        self._rgb = tuple(rgb)
        self.update()

    def setOpen(self, is_open):
        self._open = bool(is_open)
        self._bg_alpha = (0.30 if is_open else 0.16) * self._alpha_scale
        self.update()

    def getTrace(self):
        return self._trace

    def setTrace(self, v):
        self._trace = max(0.0, min(1.0, float(v)))
        self.update()

    trace = pyqtProperty(float, fget=getTrace, fset=setTrace)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r, g, b = self._rgb
        w, h = self.width(), self.height()
        pw = 2.0
        o = pw / 2.0
        x0, y0, x1, y1 = o, o, w - o, h - o

        # background tint (square box; corners kept sharp so the trace runs clean)
        bg = QColor(r, g, b)
        bg.setAlphaF(self._bg_alpha)
        p.fillRect(QRectF(0, 0, w, h), bg)

        # static top + left accent — always lit
        static = QColor(r, g, b)
        static.setAlphaF(0.85 * self._alpha_scale)
        sp = QPen(static, pw)
        sp.setCapStyle(Qt.SquareCap)
        p.setPen(sp)
        p.drawLine(QPointF(x0, y0), QPointF(x1, y0))   # top
        p.drawLine(QPointF(x0, y0), QPointF(x0, y1))   # left

        # animated bottom + right — the "running light"
        t = self._trace
        if t > 0.0:
            bw = x1 - x0
            rh = y1 - y0
            total = bw + rh
            d = t * total
            lit = QColor(r, g, b)
            lit.setAlphaF(1.0 * self._alpha_scale)
            lp = QPen(lit, pw + 0.4)
            lp.setCapStyle(Qt.SquareCap)
            p.setPen(lp)
            if d <= bw:                                 # still running along the bottom
                hx, hy = x0 + d, y1
                p.drawLine(QPointF(x0, y1), QPointF(hx, hy))
            else:                                       # bottom done, running up the right
                p.drawLine(QPointF(x0, y1), QPointF(x1, y1))
                up = min(d - bw, rh)
                hx, hy = x1, y1 - up
                p.drawLine(QPointF(x1, y1), QPointF(hx, hy))
            # bright head while in motion — ~double the line thickness so it reads as a
            # running "head"; it vanishes once the trace completes
            if 0.0 < t < 1.0:
                head = QColor(r, g, b)
                head.setAlphaF(1.0 * self._alpha_scale)
                p.setPen(Qt.NoPen)
                p.setBrush(head)
                head_r = 4.0  # clearly bigger than the ~2.4px line so the tip reads as a head
                p.drawEllipse(QPointF(hx, hy), head_r, head_r)


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
        # Per-card chevron state, restored from watcher_settings.json (default: both open)
        _saved_cards = gm.get_settings().get('cards', {})
        self._card_collapsed = {
            'db': bool(_saved_cards.get('db_collapsed', False)),
            'schwab': bool(_saved_cards.get('schwab_collapsed', False)),
        }
        self._card_titles = {}                                 # base titles (without chevron)
        self._card_status_labels = {}                          # one-line status shown when collapsed
        self._card_content = {}                                # collapsible body container per card
        self.create_database_card(main_layout)

        # Create Schwab API card
        self.create_schwab_card(main_layout)

        # Make each card's title a clickable chevron that collapses/expands its body
        self._setup_card_chevron(self.db_card, 'db', "Database Connection")
        self._setup_card_chevron(self.schwab_card, 'schwab', "Schwab API")


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
        db_layout.setSpacing(8)

        # State banner (always visible — the chevron toggles only the form below it), so a
        # collapsed card shows: orb + CONNECTED · db@host + action button. Mirrors Schwab.
        self.db_banner = QFrame()
        self.db_banner.setObjectName("dbBanner")
        db_banner_layout = QHBoxLayout(self.db_banner)
        db_banner_layout.setContentsMargins(14, 8, 10, 8)
        db_banner_layout.setSpacing(8)
        self.db_indicator = SchwabStateIndicator()
        db_banner_layout.addWidget(self.db_indicator, 0, Qt.AlignVCenter)
        self.db_state_name = QLabel("OFFLINE")
        _dbn_font = QFont("Arial", 12)
        _dbn_font.setBold(True)
        _dbn_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.db_state_name.setFont(_dbn_font)
        self.db_state_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.db_state_sep = QLabel("·")
        self.db_state_sep.setFont(QFont("Arial", 12))
        self.db_state_sep.setAlignment(Qt.AlignCenter)
        self.db_state_sep.setStyleSheet("color: #5B6573; background: transparent;")
        self.db_state_msg = QLabel("Not connected")
        self.db_state_msg.setFont(QFont("Arial", 10))
        self.db_state_msg.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.db_state_msg.setStyleSheet("color: #FFFFFF; background: transparent;")
        for _lbl in (self.db_state_name, self.db_state_sep, self.db_state_msg):
            _lbl.setContentsMargins(0, 0, 0, 8)
        db_banner_layout.addWidget(self.db_state_name, 0, Qt.AlignVCenter)
        db_banner_layout.addWidget(self.db_state_sep, 0, Qt.AlignVCenter)
        db_banner_layout.addWidget(self.db_state_msg, 0, Qt.AlignVCenter)
        db_banner_layout.addStretch()
        self._db_banner_layout = db_banner_layout  # the action button is added here below
        db_layout.addWidget(self.db_banner)
        self._make_banner_clickable(self.db_banner, 'db', self.db_card)

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
        self._db_banner_layout.addWidget(self.db_action_btn, 0, Qt.AlignVCenter)  # right of the banner
        self.update_db_button_text()
        
        form_layout.addRow(pass_label, password_row_layout)
        
        # Wrap the form in a container that can shrink to 0 so the card can collapse
        # down to just the status line (without compressing the form rows).
        db_content = QWidget()
        db_content.setMinimumHeight(0)
        db_content_layout = QVBoxLayout(db_content)
        db_content_layout.setContentsMargins(0, 0, 0, 0)
        db_content_layout.addLayout(form_layout)
        db_layout.addWidget(db_content)
        self._card_content['db'] = db_content
        
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

        # The state banner (built below) stays visible whether the card is expanded or
        # collapsed; the chevron toggles only the steps. So a collapsed card shows the
        # full banner (orb + LIVE · message + Reset) — exactly the expanded header.
        schwab_layout.setSpacing(8)

        # Content container (the numbered steps). minHeight 0 lets it collapse to 0.
        self._schwab_content = QWidget()
        self._schwab_content.setMinimumHeight(0)
        schwab_content_layout = QVBoxLayout(self._schwab_content)
        schwab_content_layout.setContentsMargins(0, 0, 0, 0)
        schwab_content_layout.setSpacing(6)  # small gap so the tinted step cards read as distinct

        # --- State banner: the prominent at-a-glance status (replaces the old 12px dot) ---
        self.schwab_banner = QFrame()
        self.schwab_banner.setObjectName("schwabBanner")
        banner_layout = QHBoxLayout(self.schwab_banner)
        banner_layout.setContentsMargins(14, 8, 10, 8)
        banner_layout.setSpacing(8)

        self.schwab_indicator = SchwabStateIndicator()
        banner_layout.addWidget(self.schwab_indicator, 0, Qt.AlignVCenter)

        # Single-line banner: glyph · NAME · message ........ [Reset]
        self.schwab_state_name = QLabel("NOT CONFIGURED")
        name_font = QFont("Arial", 12)
        name_font.setBold(True)
        name_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.schwab_state_name.setFont(name_font)
        self.schwab_state_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.schwab_state_sep = QLabel("·")
        self.schwab_state_sep.setFont(QFont("Arial", 12))
        self.schwab_state_sep.setAlignment(Qt.AlignCenter)
        self.schwab_state_sep.setStyleSheet("color: #5B6573; background: transparent;")
        self.schwab_state_msg = QLabel("Add your Schwab App Key & Secret to begin.")
        self.schwab_state_msg.setFont(QFont("Arial", 10))
        self.schwab_state_msg.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.schwab_state_msg.setStyleSheet("color: #FFFFFF; background: transparent;")
        # Nudge the text up ~4px so its optical centre lines up with the orb's centre
        # (an 8px bottom content-margin lifts vertically-centred text by half that).
        for _lbl in (self.schwab_state_name, self.schwab_state_sep, self.schwab_state_msg):
            _lbl.setContentsMargins(0, 0, 0, 8)
        banner_layout.addWidget(self.schwab_state_name, 0, Qt.AlignVCenter)
        banner_layout.addWidget(self.schwab_state_sep, 0, Qt.AlignVCenter)
        banner_layout.addWidget(self.schwab_state_msg, 0, Qt.AlignVCenter)
        banner_layout.addStretch()

        schwab_layout.addWidget(self.schwab_banner)  # always visible (above the collapsible steps)
        self._make_banner_clickable(self.schwab_banner, 'schwab', self.schwab_card)

        # Load saved credentials
        creds = gm.get_schwab_credentials()

        self.schwab_id_field = SelectAllLineEdit(creds.get('client_id') or '')
        self.schwab_id_field.setFont(QFont("Arial", 12))
        self.schwab_id_field.setEchoMode(QLineEdit.Password)
        self.schwab_id_field.setPlaceholderText("Charles Schwab App Key")
        self.schwab_id_field.textChanged.connect(self._refresh_schwab_save_enabled)

        self.schwab_secret_field = SelectAllLineEdit(creds.get('client_secret') or '')
        self.schwab_secret_field.setFont(QFont("Arial", 12))
        self.schwab_secret_field.setEchoMode(QLineEdit.Password)
        self.schwab_secret_field.setPlaceholderText("Charles Schwab Secret")
        self.schwab_secret_field.textChanged.connect(self._refresh_schwab_save_enabled)

        # Start EMPTY — never pre-fill a saved callback URL. OAuth callback URLs are
        # single-use (the code is consumed, the state is tied to one login), so a
        # stale one guarantees a "mismatching_state / CSRF" failure on the first
        # Authorize click. Empty means the first click opens a fresh browser login.
        self.schwab_auth_url_field = QLineEdit()
        self.schwab_auth_url_field.setFont(QFont("Arial", 12))
        self.schwab_auth_url_field.setEchoMode(QLineEdit.Password)  # mask like ID/Secret — no plaintext callback URL
        self.schwab_auth_url_field.setPlaceholderText("Paste the https://127.0.0.1:9090/callback?code=... URL")
        # Enter in this field finishes auth; typing flips the adjacent button between
        # "Finish" and "Reconnect" live (see _refresh_schwab_url_button).
        self.schwab_auth_url_field.returnPressed.connect(self._do_schwab_url_action)
        self.schwab_auth_url_field.textChanged.connect(lambda *_: self._refresh_schwab_url_button())

        # Action buttons — created here, placed into step bodies / footer below.
        self.schwab_save_btn = QPushButton("Save")
        self.schwab_save_btn.setFont(QFont("Arial", 12))
        self.schwab_save_btn.setMinimumWidth(90)
        self.schwab_save_btn.clicked.connect(self._do_schwab_save)

        self.schwab_auth_btn = QPushButton("Authorize")
        self.schwab_auth_btn.setFont(QFont("Arial", 12))
        self.schwab_auth_btn.setMinimumWidth(110)
        self.schwab_auth_btn.clicked.connect(self._do_schwab_authorize)

        self.schwab_reconnect_btn = QPushButton("Reconnect")
        self.schwab_reconnect_btn.setFont(QFont("Arial", 12))
        self.schwab_reconnect_btn.setMinimumWidth(110)
        self.schwab_reconnect_btn.setToolTip("Try to revive the existing session without a full re-login")
        self.schwab_reconnect_btn.clicked.connect(self._do_schwab_url_action)

        self.schwab_disconnect_btn = QPushButton("Disconnect")
        self.schwab_disconnect_btn.setFont(QFont("Arial", 12))
        self.schwab_disconnect_btn.setMinimumWidth(110)
        self.schwab_disconnect_btn.clicked.connect(self.schwab_disconnect_clicked)

        # Reset (full wipe) lives on the right of the state banner above.
        self.schwab_reset_btn = QPushButton("Reset")
        self.schwab_reset_btn.setFont(QFont("Arial", 12))
        self.schwab_reset_btn.setMinimumWidth(90)
        self.schwab_reset_btn.setToolTip(
            "Erase the saved App Key, Secret, and token and start over — "
            "you'll re-enter your credentials and re-authorize from scratch.")
        self.schwab_reset_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; padding: 5px 16px; }")
        self.schwab_reset_btn.clicked.connect(self.schwab_delete_clicked)
        banner_layout.addWidget(self.schwab_reset_btn, 0, Qt.AlignVCenter)  # right of the banner (after the stretch)

        # ---- Numbered stepper: (1) keys -> (2) authorize -> (3) connection ----
        self.schwab_steps = {}
        self._schwab_step_override = None  # lets the user reopen a completed step

        # Step 1 — App Key & Secret
        step1 = self._build_schwab_step(1, "App Key & Secret")
        b1 = self.schwab_steps[1]["body_layout"]
        # "Get keys" link sits at the top — it's what you reach for before you have keys
        get_keys_btn = QPushButton("Get keys at developer.schwab.com  ↗")
        get_keys_btn.setFlat(True)
        get_keys_btn.setCursor(Qt.PointingHandCursor)
        get_keys_btn.setStyleSheet(
            "QPushButton { color: #36C5F0; background: transparent; border: none; text-align: left; padding: 0; }")
        get_keys_btn.clicked.connect(lambda: webbrowser.open("https://developer.schwab.com"))
        keys_row = QHBoxLayout()
        keys_row.addWidget(get_keys_btn)
        keys_row.addStretch()
        b1.addLayout(keys_row)

        creds_form = QFormLayout()
        creds_form.setSpacing(8)
        creds_form.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        creds_form.setFormAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        id_lbl = QLabel("Client ID:")
        id_lbl.setFont(QFont("Arial", 11))
        # negative top-margin lifts the label without growing the row (same as the DB card)
        id_lbl.setStyleSheet("QLabel { background: transparent; margin-top: -16px; }")
        secret_lbl = QLabel("Client Secret:")
        secret_lbl.setFont(QFont("Arial", 11))
        secret_lbl.setStyleSheet("QLabel { background: transparent; margin-top: -16px; }")
        creds_form.addRow(id_lbl, self.schwab_id_field)
        # Save sits on the Client Secret line, to the right of the field
        secret_row = QHBoxLayout()
        secret_row.setSpacing(8)
        secret_row.addWidget(self.schwab_secret_field)
        secret_row.addWidget(self.schwab_save_btn)
        creds_form.addRow(secret_lbl, secret_row)
        b1.addLayout(creds_form)

        # Step 2 — Authorize
        step2 = self._build_schwab_step(2, "Authorize")
        b2 = self.schwab_steps[2]["body_layout"]
        guide = QLabel(
            "Click Authorize to open Schwab sign-in, then paste the redirect URL "
            "Schwab sends you back to and click Authorize again to finish.")
        guide.setWordWrap(True)
        guide.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        guide.setMinimumHeight(36)  # reserve 2 lines so the card's sizeHint can't squeeze/clip it
        guide.setFont(QFont("Arial", 11))  # same size as the "Redirect URL:" label
        guide.setStyleSheet("color: #E6EDF3; background: transparent;")  # white, readable
        # Guide text on the left, Authorize button in line on the right
        guide_row = QHBoxLayout()
        guide_row.setSpacing(12)
        guide_row.addWidget(guide, 1)
        guide_row.addWidget(self.schwab_auth_btn, 0, Qt.AlignVCenter)
        b2.addLayout(guide_row)
        url_form = QFormLayout()
        url_form.setSpacing(8)
        url_form.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        url_form.setFormAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        url_lbl = QLabel("Redirect URL:")
        url_lbl.setFont(QFont("Arial", 11))
        url_lbl.setStyleSheet("QLabel { background: transparent; margin-top: -16px; }")  # lift, no row growth
        # Redirect URL field with Reconnect to its right
        url_field_row = QHBoxLayout()
        url_field_row.setSpacing(12)
        url_field_row.addWidget(self.schwab_auth_url_field)
        url_field_row.addWidget(self.schwab_reconnect_btn)
        url_form.addRow(url_lbl, url_field_row)
        b2.addLayout(url_form)

        # Step 3 — Connection: a single inline row, no expandable body.
        #   [3] Connection   LIVE · Streaming … data.        [Disconnect]
        step3 = self._build_schwab_step(3, "Connection")
        self.schwab_steps[3]["body_layout"].setContentsMargins(0, 0, 0, 0)  # body stays zero-height
        h3 = self.schwab_steps[3]["header_layout"]

        # "LIVE" is its own label so it can pulse on its own (the rest stays steady).
        # Pulse is a QTimer that breathes the green brightness — robust + renders cleanly
        # (unlike QGraphicsOpacityEffect, which doesn't composite through QWidget.render).
        self.schwab_live_word = QLabel("LIVE")
        _live_font = QFont("Arial", 12)  # match the "Connection" title size
        _live_font.setBold(True)
        self.schwab_live_word.setFont(_live_font)
        self.schwab_live_word.setStyleSheet("color:#3FB950; background: transparent;")
        self._live_pulse_phase = 0.0
        self._live_pulse_timer = QTimer(self)
        self._live_pulse_timer.setInterval(50)
        self._live_pulse_timer.timeout.connect(self._advance_live_pulse)

        self.schwab_live_text = QLabel("·  Streaming Schwab market data.")
        self.schwab_live_text.setFont(QFont("Arial", 12))  # same size as the "Connection" title
        self.schwab_live_text.setStyleSheet("color:#FFFFFF; background: transparent;")

        # LIVE + live text go right after the "Connection" title (before the stretch);
        # Disconnect sits on the far right — all on the header's single line.
        h3.insertWidget(2, self.schwab_live_word, 0, Qt.AlignVCenter)
        h3.insertWidget(3, self.schwab_live_text, 0, Qt.AlignVCenter)
        h3.addWidget(self.schwab_disconnect_btn, 0, Qt.AlignVCenter)
        # Center every element on the row against the (tallest) Disconnect button
        h3.setAlignment(self.schwab_steps[3]["disc"], Qt.AlignVCenter)
        h3.setAlignment(self.schwab_steps[3]["title"], Qt.AlignVCenter)
        h3.setAlignment(self.schwab_steps[3]["chip"], Qt.AlignVCenter)

        schwab_content_layout.addWidget(step1)
        schwab_content_layout.addWidget(step2)
        schwab_content_layout.addWidget(step3)
        schwab_layout.addWidget(self._schwab_content)
        self._card_content['schwab'] = self._schwab_content

        self.schwab_card.setMaximumHeight(0)
        self.schwab_card.hide()
        parent_layout.addWidget(self.schwab_card)

        # Track previous status for transition detection
        self._prev_schwab_status = None
        # Which step body is currently open (None until first paint → no entry animation)
        self._schwab_shown_step = None

        # Reflect current status
        self.update_schwab_status()

        # Periodically refresh Schwab status (catches mid-session token expiry)
        self._schwab_status_timer = QTimer(self)
        self._schwab_status_timer.timeout.connect(self.update_schwab_status)
        self._schwab_status_timer.start(60_000)  # every 60 seconds

    def _build_schwab_step(self, num, title):
        """Build one stepper row: numbered disc + title + status chip + collapsible body.

        Stores widget refs in self.schwab_steps[num] and returns the frame.
        """
        frame = SchwabStepFrame(SCHWAB_STEP_TINTS[num], alpha_scale=SCHWAB_STEP_ALPHA[num])
        frame.setObjectName(f"schwabStep{num}")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        header = QWidget()
        # Transparent (ID-scoped so child inputs/buttons keep their own bg) — otherwise
        # the theme's opaque QWidget background paints over the frame's tint + trace.
        header.setObjectName("schwabStepHeader")
        header.setStyleSheet("#schwabStepHeader { background: transparent; }")
        h = QHBoxLayout(header)
        h.setContentsMargins(6, 6, 10, 6)
        h.setSpacing(10)
        disc = QLabel(str(num))
        disc.setFixedSize(26, 26)
        disc.setAlignment(Qt.AlignCenter)
        disc.setFont(QFont("Arial", 11, QFont.Bold))
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Arial", 12, QFont.Bold))
        title_lbl.setStyleSheet("background: transparent;")
        chip = QLabel("")
        chip.setFont(QFont("Arial", 12))  # match the step title size (e.g. "saved")
        chip.setTextFormat(Qt.RichText)   # allows the green-box ✓ badge
        chip.setStyleSheet("background: transparent; color: #8B98A5;")
        h.addWidget(disc)
        h.addWidget(title_lbl)
        h.addStretch()
        h.addWidget(chip)

        body = QWidget()
        body.setObjectName("schwabStepBody")
        body.setStyleSheet("#schwabStepBody { background: transparent; }")  # let the frame tint/trace show
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(36, 4, 6, 8)  # indent under the disc; top pad so text clears the header
        body_layout.setSpacing(8)

        outer.addWidget(header)
        outer.addWidget(body)

        # Click a completed step's header to reopen it (e.g. to change saved keys)
        header.setCursor(Qt.PointingHandCursor)
        header.mousePressEvent = lambda event, n=num: self._on_schwab_step_clicked(n)

        self.schwab_steps[num] = {
            "frame": frame, "header": header, "header_layout": h, "disc": disc,
            "title": title_lbl, "chip": chip, "body": body, "body_layout": body_layout,
        }
        return frame

    def _advance_live_pulse(self):
        """Subtly breathe the green of the Step 3 'LIVE' word (timer-driven brightness)."""
        self._live_pulse_phase = (self._live_pulse_phase + 0.03) % 1.0
        tri = 1.0 - abs(1.0 - 2.0 * self._live_pulse_phase)  # 0 -> 1 -> 0 triangle
        f = 0.55 + 0.45 * tri                                 # brightness 0.55 .. 1.0
        r, g, b = int(63 * f), int(185 * f), int(80 * f)      # scale base green #3FB950
        self.schwab_live_word.setStyleSheet(f"color: rgb({r}, {g}, {b}); background: transparent;")

    def _schwab_done_chip(self, word):
        """Rich-text chip for a completed step: the word, then a green box with a black ✓."""
        return (f'<span style="color:#E6EDF3;">{word}&nbsp;</span>'
                '<span style="background-color:#3FB950; color:#0c0f12;">&nbsp;✓&nbsp;</span>')

    def _schwab_active_step(self, status):
        """Which step is the current action: 1=keys, 2=authorize, 3=connected."""
        return {
            "not_configured": 1,
            "token_revoked": 1,   # revoked → reset to the top; Reconnect can't revive it
            "token_missing": 2,
            "token_expired": 2,
            "authorized": 3,
        }.get(status, 1)

    def _on_schwab_step_clicked(self, num):
        """Reopen a completed step so saved values can be edited; ignore active/locked."""
        active = self._schwab_active_step(schwab_client.get_status())
        if num < active:
            # toggle: clicking the already-reopened step closes it again
            self._schwab_step_override = None if self._schwab_step_override == num else num
        else:
            self._schwab_step_override = None
        self.update_schwab_status()

    def _apply_schwab_shown(self, shown):
        """Show the `shown` step's body and hide the others, animating the height when
        the open step changes. First paint (no prior shown step) applies instantly."""
        prev = self._schwab_shown_step
        if prev == shown:
            return  # nothing changed — don't restart animations on every status tick
        animate = prev is not None
        for num in (1, 2, 3):
            body = self.schwab_steps[num]["body"]
            frame = self.schwab_steps[num]["frame"]
            if num == shown:
                # body expands first; only AFTER it settles does the bottom+right border
                # "run" (so the expansion motion doesn't compete with the travelling line)
                if animate:
                    body.setVisible(True)
                    body.layout().activate()
                    target = body.sizeHint().height()
                    body.setMaximumHeight(0)
                    frame.setTrace(0.0)

                    def _after_expand(b=body, f=frame):
                        b.setMaximumHeight(16777215)
                        self._animate_trace(f, 0.0, 1.0)
                    self._animate_height(body, 0, target, on_finish=_after_expand)
                else:
                    body.setVisible(True)
                    body.setMaximumHeight(16777215)
                    frame.setTrace(1.0)
            else:
                # body closes; drop the trace immediately so only the opening box's line
                # is the moving element the eye follows
                if animate and body.isVisible() and body.maximumHeight() != 0:
                    frame.setTrace(0.0)
                    self._animate_height(
                        body, body.height(), 0,
                        on_finish=lambda b=body: b.setVisible(False))
                else:
                    body.setVisible(False)
                    body.setMaximumHeight(16777215)  # reset clamp for next open
                    frame.setTrace(0.0)
        self._schwab_shown_step = shown

    def _animate_trace(self, frame, start, end):
        """Animate a SchwabStepFrame's bottom+right border 'running light' (trace 0..1)."""
        anim = QPropertyAnimation(frame, b"trace")
        anim.setDuration(1380)  # slowed 3x so the travelling head is easy to follow
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setEasingCurve(QEasingCurve.Linear)  # constant speed reads as a head running across
        anim.start()
        if not hasattr(self, '_animations'):
            self._animations = []
        self._animations.append(anim)

    def _refresh_schwab_save_enabled(self):
        """Enable Save the moment both credential fields have content (live, per keystroke)."""
        has = bool(self.schwab_id_field.text().strip() and self.schwab_secret_field.text().strip())
        self.schwab_save_btn.setEnabled(has)
        self.schwab_save_btn.setStyleSheet(
            "QPushButton { background-color: #3FB950; color: white; }" if has
            else "QPushButton { background-color: #555555; color: #999999; }")

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
            elif status == "token_revoked":
                logger.warning("Schwab refresh token revoked — reset to Step 1; full re-Authorize required")
            elif status == "token_expired":
                logger.warning("Schwab token expired — click Authorize to reconnect")
            self._write_data_source()
            self._schwab_step_override = None  # status advanced — drop any manual reopen
        self._prev_schwab_status = status

        # State banner: painted glyph + name + plain-language message, tinted to state
        name, msg = SCHWAB_STATE_META.get(status, SCHWAB_STATE_META["not_configured"])
        color = SCHWAB_STATE_COLORS.get(status, SCHWAB_STATE_COLORS["not_configured"])
        self.schwab_indicator.set_state(status)
        self.schwab_state_name.setText(name)
        self.schwab_state_name.setStyleSheet(f"color: {color}; background: transparent;")
        self.schwab_state_msg.setText(msg)
        c = QColor(color)
        r, g, b = c.red(), c.green(), c.blue()
        self.schwab_banner.setStyleSheet(
            f"#schwabBanner {{ background-color: rgba({r}, {g}, {b}, 0.10);"
            f" border: 1px solid rgba({r}, {g}, {b}, 0.35);"
            f" border-left: 3px solid {color}; border-radius: 6px; }}"
        )

        # ---- Stepper: derive the active step and paint each row ----
        active = self._schwab_active_step(status)
        # An override lets the user reopen a completed step (e.g. to change saved keys).
        shown = self._schwab_step_override if self._schwab_step_override is not None else active

        DONE_C = "#3FB950"
        DIM_C = "#5B6573"
        TXT_C = "#E6EDF3"

        for num in (1, 2, 3):
            step = self.schwab_steps[num]
            disc, title_lbl, chip, frame = step["disc"], step["title"], step["chip"], step["frame"]

            # Disc keeps its NUMBER in every state (no ✓ swap — completion is shown by
            # the green check badge in the chip instead). Titles are always white.
            if num < active:        # completed — green disc, black number
                disc.setText(str(num))
                disc.setStyleSheet(f"background-color: {DONE_C}; color: #0c0f12; border-radius: 13px;")
            elif num == active:     # current — disc takes the state colour
                disc.setText(str(num))
                disc.setStyleSheet(f"background-color: {color}; color: #0c0f12; border-radius: 13px;")
            else:                   # locked — outlined disc, white number
                disc.setText(str(num))
                disc.setStyleSheet(f"background-color: transparent; color: {TXT_C}; "
                                   f"border: 1.6px solid {DIM_C}; border-radius: 13px;")
            title_lbl.setStyleSheet(f"color: {TXT_C}; background: transparent;")

            # status chip — completed steps show a green box + black ✓ badge then the word
            chip_html, chip_text, chip_color = None, "", TXT_C
            if num == 1 and num < active:
                chip_html = self._schwab_done_chip("saved")
            elif num == 2:
                if num < active:
                    chip_html = self._schwab_done_chip("authorized")
                elif num == active:
                    if status == "token_expired":
                        chip_text, chip_color = "expired — reauthorize", "#E8A33D"
                    else:
                        chip_text, chip_color = "action needed", "#36C5F0"
                else:
                    chip_text, chip_color = "locked", TXT_C
            elif num == 3:
                chip_text, chip_color = ("", DONE_C) if num == active else ("locked", TXT_C)
            if chip_html is not None:
                chip.setText(chip_html)
                chip.setStyleSheet("background: transparent;")
            else:
                chip.setText(chip_text)
                chip.setStyleSheet(f"color: {chip_color}; background: transparent;")

            # Step 3 shows its live status inline on the header line (LIVE + text +
            # Disconnect) only when connected; otherwise it's just "locked".
            if num == 3:
                live = (num == active)  # connected/authorized
                self.schwab_live_word.setVisible(live)
                self.schwab_live_text.setVisible(live)
                self.schwab_disconnect_btn.setVisible(live)
                chip.setVisible(not live)
                if live:
                    if not self._live_pulse_timer.isActive():
                        self._live_pulse_timer.start()
                else:
                    self._live_pulse_timer.stop()
                    self.schwab_live_word.setStyleSheet("color:#3FB950; background: transparent;")

            # per-step colour is painted by SchwabStepFrame: a static top+left accent
            # plus the bottom+right "running light" trace (animated in _apply_schwab_shown).
            # Here we just mark which step reads as open (deeper bg tint).
            frame.setOpen(num == shown)

        # Reveal the active/clicked step's body — animated when it changes, instant on
        # first paint. (Driven here so it tracks both status changes and step clicks.)
        self._apply_schwab_shown(shown)

        # ---- Button states ----
        live = (status == "authorized")
        GREY_BTN = "QPushButton { background-color: #555555; color: #999999; padding: 5px 16px; }"
        self._refresh_schwab_save_enabled()
        # When connected live, lock down steps 1 & 2 — don't let the user edit keys or
        # re-run auth while the link is working. Reset (top-right) is the way to redo it.
        if live:
            self.schwab_save_btn.setEnabled(False)
            self.schwab_save_btn.setStyleSheet("QPushButton { background-color: #555555; color: #999999; }")
        self.schwab_auth_btn.setEnabled(not live)
        self.schwab_auth_btn.setStyleSheet(
            GREY_BTN if live
            else "QPushButton { background-color: #2196F3; color: white; padding: 5px 16px; }")
        # The button beside the Redirect URL field is context-aware: it FINISHES auth
        # when a redirect URL is pasted, otherwise it RECONNECTs a lapsed session. It
        # stays in the layout at all times (toggling visibility made it overlap Authorize).
        self._refresh_schwab_url_button(status)
        self.schwab_disconnect_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
        self.schwab_reset_btn.setEnabled(status != "not_configured")

        # While connected live, the credential + URL fields are read-only (Reset to change)
        self.schwab_id_field.setReadOnly(live)
        self.schwab_secret_field.setReadOnly(live)
        self.schwab_auth_url_field.setReadOnly(live)

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
        # Soft length check: a real Schwab App Key is 32 chars and Secret is 16. Wrong
        # lengths almost always mean a paste appended onto a pre-filled field. Warn and
        # confirm, but don't hard-block (in case Schwab ever changes the format).
        issues = []
        if len(client_id) != 32:
            issues.append(f"• App Key (Client ID) is {len(client_id)} chars — expected 32")
        if len(client_secret) != 16:
            issues.append(f"• Secret is {len(client_secret)} chars — expected 16")
        if issues:
            reply = QMessageBox.warning(
                self, "Schwab credentials look off",
                "These don't match Schwab's usual format:\n\n"
                + "\n".join(issues)
                + "\n\nThis often happens when a pasted value got appended onto an "
                  "existing one. Click into a field and it now selects all, so re-paste "
                  "to replace.\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                logger.info("Schwab save cancelled — credential length check "
                            f"(id={len(client_id)}, secret={len(client_secret)})")
                return
        was_revoked = schwab_client.get_status() == "token_revoked"
        gm.save_schwab_credentials(client_id, client_secret)
        if was_revoked:
            # The stored token is dead (invalid_grant). Discard it on Save so the flow
            # advances to a clean Authorize (Step 2) instead of looping back to Step 1.
            schwab_client.clear_token()
            logger.info("Discarded revoked Schwab token — click Authorize to re-connect")
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

    def _refresh_schwab_url_button(self, status=None):
        """The button beside the Redirect URL field does double duty:
          - a redirect URL is pasted -> green "Finish" (completes the OAuth sign-in)
          - lapsed session, no URL    -> green "Reconnect" (revive without re-login)
          - otherwise                 -> greyed + disabled
        Called on status changes and live as the URL field is edited, so whatever the
        user reaches for next to the field does the right thing."""
        if status is None:
            status = schwab_client.get_status()
        GREEN = "QPushButton { background-color: #3FB950; color: white; padding: 5px 16px; }"
        GREY = "QPushButton { background-color: #555555; color: #999999; padding: 5px 16px; }"
        has_url = bool(self.schwab_auth_url_field.text().strip())
        btn = self.schwab_reconnect_btn
        if has_url and status != "authorized":
            btn.setText("Finish")
            btn.setToolTip("Complete sign-in with the pasted redirect URL")
            btn.setEnabled(True)
            btn.setStyleSheet(GREEN)
        elif status == "token_expired":
            btn.setText("Reconnect")
            btn.setToolTip("Try to revive the existing session without a full re-login")
            btn.setEnabled(True)
            btn.setStyleSheet(GREEN)
        else:
            btn.setText("Reconnect")
            btn.setToolTip("Try to revive the existing session without a full re-login")
            btn.setEnabled(False)
            btn.setStyleSheet(GREY)

    def _do_schwab_url_action(self):
        """Context-aware action for the URL-field button (and Enter in the field):
        finish auth when a redirect URL is present, else revive a lapsed session."""
        if self.schwab_auth_url_field.text().strip() and schwab_client.get_status() != "authorized":
            self._do_schwab_authorize()   # URL present -> hits the complete_auth path
        else:
            self.schwab_reconnect_clicked()

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
            for c in (self.db_card, self.schwab_card):
                c.setMaximumHeight(c.height())  # clamp to actual (cards are unclamped while open)
            self.animate_card(self.db_card, 0)
            self.animate_card(self.schwab_card, 0)
            self.db_card_visible = False
        else:
            # Reveal both cards, each restored to its saved chevron state
            for k, c in (('db', self.db_card), ('schwab', self.schwab_card)):
                self._apply_card_collapse(k, c, animate=False)  # set body + status to saved state
                c.show()
                c.setMaximumHeight(0)
                self._animate_height(c, 0, c.sizeHint().height(),
                                     on_finish=lambda card=c: card.setMaximumHeight(16777215))
            self.db_card_visible = True
    
    def _setup_card_chevron(self, card, key, base_title):
        """Make a settings card's title a clickable chevron that collapses/expands its body."""
        self._card_titles[key] = base_title
        card.setTitle(f"▾  {base_title}")
        # The title/frame shows a hand cursor; child fields keep their own (I-beam etc.)
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda event, k=key, c=card: self._on_card_header_press(event, k, c)

    def _card_header_height(self, card):
        """Collapsed height — just enough to show the title row."""
        return card.fontMetrics().height() + 18

    def _on_card_header_press(self, event, key, card):
        # Only the title band toggles; clicks on the body reach the child widgets instead.
        if event.button() == Qt.LeftButton and event.pos().y() <= self._card_header_height(card):
            self._toggle_card_collapse(key, card)

    def _toggle_card_collapse(self, key, card):
        """Flip a card between collapsed (title + status line) and expanded (full body), animated."""
        collapsed = not self._card_collapsed.get(key, False)
        self._card_collapsed[key] = collapsed
        gm.save_settings(cards_collapsed=self._card_collapsed)  # persist last chevron state
        self._apply_card_collapse(key, card, animate=True)

    def _make_banner_clickable(self, banner, key, card):
        """Let a card's status banner toggle collapse/expand on click — a big target so you
        don't have to hit the small chevron. The banner's action button still works: it's a
        child widget that consumes its own clicks, so they never reach this handler."""
        banner.setCursor(Qt.PointingHandCursor)
        banner.mousePressEvent = lambda e, k=key, c=card: (
            self._toggle_card_collapse(k, c) if e.button() == Qt.LeftButton else None)

    def _apply_card_collapse(self, key, card, animate=True):
        """Collapse to (title + always-visible banner) or expand to the full body by
        animating the body container's height. The card stays unclamped and follows along.
        The banner's action button (Reset / Connect·Disconnect) hides while collapsed."""
        collapsed = self._card_collapsed.get(key, False)
        content = self._card_content.get(key)
        base = self._card_titles.get(key, card.title())
        card.setTitle(f"{'▸' if collapsed else '▾'}  {base}")
        # Banner stays visible; only its action button is hidden when collapsed
        btn = {'schwab': getattr(self, 'schwab_reset_btn', None),
               'db': getattr(self, 'db_action_btn', None)}.get(key)
        if btn is not None:
            btn.setVisible(not collapsed)
        if content is None:
            return
        if collapsed:
            if animate:
                self._animate_height(content, content.height(), 0,
                                     on_finish=lambda c=content: c.setVisible(False))
            else:
                content.setMaximumHeight(0)
                content.setVisible(False)
        else:
            content.setVisible(True)
            content.setMaximumHeight(16777215)
            content.layout().activate()
            full = content.sizeHint().height()
            if animate:
                content.setMaximumHeight(0)
                self._animate_height(content, 0, full,
                                     on_finish=lambda c=content: c.setMaximumHeight(16777215))
            else:
                content.setMaximumHeight(16777215)

    def _animate_height(self, widget, start, end, on_finish=None):
        """Smoothly animate a widget's maximumHeight from start to end (300ms ease)."""
        anim = QPropertyAnimation(widget, b"maximumHeight")
        anim.setDuration(300)
        anim.setStartValue(int(start))
        anim.setEndValue(int(end))
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        if on_finish is not None:
            anim.finished.connect(on_finish)
        anim.finished.connect(self.scroll_status_to_bottom)
        anim.start()
        if not hasattr(self, '_animations'):
            self._animations = []
        self._animations.append(anim)

    def _update_card_status_label(self, key):
        """Both cards now keep an always-visible banner instead of a collapsed-only status
        line, so there is nothing extra to refresh here (kept for the collapse plumbing)."""
        return

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
        """Update the database action button + the always-visible banner from connection state."""
        try:
            connected = bool(self.db_manager and self.db_manager.is_connected())
        except Exception as e:
            logger.debug(f"Error checking DB connection: {e}")
            connected = False

        if connected:
            self.db_action_btn.setText("Disconnect")
            self.db_action_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; }")  # Red
        else:
            self.db_action_btn.setText("Connect")
            self.db_action_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")  # Green

        # Banner: orb + NAME · detail, tinted to state (mirrors the Schwab banner)
        if getattr(self, 'db_banner', None) is not None:
            if connected:
                db = self.database_field.text().strip() or "?"
                host = self.host_field.text().strip() or "?"
                self.db_indicator.set_state("authorized")
                self.db_state_name.setText("CONNECTED")
                self.db_state_name.setStyleSheet("color: #3FB950; background: transparent;")
                self.db_state_msg.setText(f"{db}@{host}")
                color = "#3FB950"
            else:
                self.db_indicator.set_state("not_configured")
                self.db_state_name.setText("OFFLINE")
                self.db_state_name.setStyleSheet("color: #8B98A5; background: transparent;")
                self.db_state_msg.setText("Not connected")
                color = "#5B6573"
            c = QColor(color)
            r, g, b = c.red(), c.green(), c.blue()
            self.db_banner.setStyleSheet(
                f"#dbBanner {{ background-color: rgba({r}, {g}, {b}, 0.10);"
                f" border: 1px solid rgba({r}, {g}, {b}, 0.35);"
                f" border-left: 3px solid {color}; border-radius: 6px; }}")

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