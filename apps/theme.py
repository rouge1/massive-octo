# Standard library imports
import json
import os

# Third-party imports
from PyQt5 import Qt  #type: ignore


# Dark theme color palette (shared constants)
COLORS = {
    'bg_main': '#2e2e2e',
    'bg_dark': '#1a1a1a',
    'bg_card': '#353535',
    'bg_input': '#3a3a3a',
    'bg_button': '#4b4b4b',
    'bg_button_hover': '#656565',
    'bg_button_pressed': '#3d3d3d',
    'bg_button_disabled': '#3a3a3a',
    'bg_success': '#4b7c4b',
    'bg_success_hover': '#5d9e5d',
    'bg_error': '#4b2e2e',
    'fg_main': '#ffffff',
    'fg_error': '#ffcccc',
    'border': '#5c5c5c',
    'border_hover': '#767676',
    'border_pressed': '#4e4e4e'
}


#This function is called to apply the theme to the dialog
def apply_dark_theme(widget):
    # Set minimum dialog size
    if isinstance(widget, Qt.QDialog):
        widget.setMinimumWidth(350)
        widget.setMinimumHeight(400)
    
    stylesheet = """
    QDialog, QWidget {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    QLabel {
        color: #ffffff;
        margin-top: 10px;  /* Add spacing above labels */
    }
    QPushButton {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
        min-width: 80px;
    }
    QPushButton:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QPushButton:pressed {
        background-color: #3d3d3d;
        border: 2px solid #4e4e4e;
    }
    QComboBox {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
        margin: 5px 0px;  /* Add vertical spacing */
    }
    QComboBox:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QComboBox QAbstractItemView {
        background-color: #4b4b4b;
        color: #ffffff;
        selection-background-color: #656565;
    }
    QSlider {
        background-color: transparent;
        margin: 15px 0px;  /* Add more vertical spacing around sliders */
    }
    QSlider::groove:horizontal {
        background-color: #4b4b4b;
        height: 8px;
        border-radius: 4px;
    }
    QSlider::handle:horizontal {
        background-color: #ffffff;
        border: none;
        width: 16px;
        margin: -4px 0;
        border-radius: 8px;
    }
    QSlider::handle:horizontal:hover {
        background-color: #dddddd;
    }
    QHBoxLayout {
        margin: 10px 0px;  /* Add spacing around horizontal layouts */
    }
    QVBoxLayout {
        margin: 10px 0px;  /* Add spacing around vertical layouts */
    }
    QTextEdit {
        background-color: #3a3a3a;  /* Slightly lighter than main background */
        color: #ffffff;
        border: 1px solid #5c5c5c;
        border-radius: 3px;
        padding: 5px;
    }
    QGroupBox {
        background-color: #353535;  /* Different color for cards */
        border: 2px solid #5c5c5c;
        border-radius: 8px;
        margin-top: 10px;
        padding-top: 10px;
        font-weight: bold;
    }
    QGroupBox::title {
        color: #ffffff;
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
    }
    QToolTip {
        background-color: #1a1a1a;
        color: #ffffff;
        border: 1px solid #5c5c5c;
        border-radius: 3px;
        padding: 2px;
        font-size: 12px;
    }
    """
    widget.setStyleSheet(stylesheet)

