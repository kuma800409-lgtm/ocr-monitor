"""
Configuration module for OCR Monitor application.

Contains all constants, colors, fonts, spacing, and QSS stylesheets
used throughout the application. Centralizes configuration to make
styling and behavior adjustments easy.
"""

# ============================================================================
# Window Hotkey Constants (Windows API)
# ============================================================================

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_X = 0x58
WM_HOTKEY = 0x0312
HOTKEY_ID = 1


# ============================================================================
# Window Size Constants
# ============================================================================

# Main window
MAIN_WINDOW_MIN_WIDTH = 500
MAIN_WINDOW_MIN_HEIGHT = 600
MAIN_WINDOW_DEFAULT_WIDTH = 700
MAIN_WINDOW_DEFAULT_HEIGHT = 650

# Overlay window
OVERLAY_MIN_WIDTH = 300
OVERLAY_MIN_HEIGHT = 150
OVERLAY_DEFAULT_WIDTH = 450
OVERLAY_DEFAULT_HEIGHT = 300
OVERLAY_DEFAULT_OPACITY = 200


# ============================================================================
# Adaptive Change Detector Defaults
# ============================================================================

DEFAULT_THRESHOLD = 5
DEFAULT_STABILITY_FRAMES = 3
DEFAULT_MAX_WAIT_SECONDS = 5
DEFAULT_IDLE_INTERVAL_MS = 1000
DEFAULT_ACTIVE_INTERVAL_MS = 150
DEFAULT_COOLDOWN_MS = 500


# ============================================================================
# QSS Stylesheets
# ============================================================================

# Overlay window opacity slider
OPACITY_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        background: #555;
        height: 6px;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #0078d4;
        width: 14px;
        margin: -4px 0;
        border-radius: 7px;
    }
"""

# Overlay window buttons
COPY_BUTTON_STYLE = """
    QPushButton {
        background-color: #0078d4;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 3px;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #1084d8;
    }
"""

CLEAR_BUTTON_STYLE = """
    QPushButton {
        background-color: #555;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 3px;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #666;
    }
"""

CLOSE_BUTTON_STYLE = """
    QPushButton {
        background-color: #aa0000;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 3px;
        font-size: 9pt;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #cc0000;
    }
"""

# Pin button styles
PIN_BUTTON_ACTIVE_STYLE = """
    QPushButton {
        background-color: #ff6600;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 3px;
        font-size: 9pt;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #ff8833;
    }
"""

PIN_BUTTON_INACTIVE_STYLE = """
    QPushButton {
        background-color: #444;
        color: #ccc;
        border: 1px solid #666;
        padding: 8px 16px;
        border-radius: 3px;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #555;
        color: white;
    }
"""

# Overlay text area
RESULT_TEXT_STYLE = """
    QPlainTextEdit {
        background-color: rgba(20, 20, 20, 220);
        color: #ffffff;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 8px;
        selection-background-color: #0078d4;
    }
"""


# ============================================================================
# Color Constants
# ============================================================================

# Mode indicator colors
MODE_IDLE_COLOR = "#0066cc"
MODE_ACTIVE_COLOR = "#cc6600"
MODE_COOLDOWN_COLOR = "#666666"

# Status colors
STATUS_SUCCESS_COLOR = "green"
STATUS_ERROR_COLOR = "red"
STATUS_INFO_COLOR = "#666"
STATUS_SECONDARY_COLOR = "#444"


# ============================================================================
# Font Configurations
# ============================================================================

# Font family
FONT_FAMILY = "Segoe UI"
MONOSPACE_FONT = "Consolas"

# Font sizes
TITLE_FONT_SIZE = 9
LABEL_FONT_SIZE = 9
MODE_FONT_SIZE = 11
RESULT_FONT_SIZE = 12
INSTRUCTION_FONT_SIZE = 9


# ============================================================================
# Layout Constants
# ============================================================================

# Spacing
GROUP_SPACING = 15
CONTROL_SPACING = 10
HEADER_SPACING = 5

# Margins
MAIN_MARGIN = 20
GROUP_MARGIN_TOP = 20
GROUP_MARGIN_SIDES = 15
GROUP_MARGIN_BOTTOM = 10
