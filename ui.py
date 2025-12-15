"""
UI module for OCR Monitor application.

Contains all PyQt UI components including:
- OCROverlayWindow: Separate overlay window for displaying OCR results
- OCRMonitorApp: Main application window with controls and settings
"""

import sys
import os
import json
import ctypes
from datetime import datetime

# Windows-specific imports
if sys.platform == 'win32':
    from ctypes import wintypes

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QGroupBox,
    QMessageBox, QSlider, QPlainTextEdit, QSizeGrip, QScrollArea,
    QFrame, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QFont, QPainter, QColor, QPen

import mss
from PIL import Image

from config import (
    # Window sizes
    MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT,
    OVERLAY_MIN_WIDTH, OVERLAY_MIN_HEIGHT,
    OVERLAY_DEFAULT_WIDTH, OVERLAY_DEFAULT_HEIGHT,
    OVERLAY_DEFAULT_OPACITY,
    # Hotkey constants
    WM_HOTKEY, HOTKEY_ID,
    # Stylesheets
    OPACITY_SLIDER_STYLE, COPY_BUTTON_STYLE, CLEAR_BUTTON_STYLE,
    CLOSE_BUTTON_STYLE, PIN_BUTTON_ACTIVE_STYLE, PIN_BUTTON_INACTIVE_STYLE,
    RESULT_TEXT_STYLE,
    # Fonts
    FONT_FAMILY, MONOSPACE_FONT,
    TITLE_FONT_SIZE, LABEL_FONT_SIZE, MODE_FONT_SIZE, RESULT_FONT_SIZE,
)
from ocr_engine import (
    TESSERACT_PATH,
    AdaptiveChangeDetector,
    OCRWorker,
    get_installed_languages,
    get_language_display_name,
    check_language_availability,
    DEFAULT_LANGUAGES,
)
from utils import (
    register_hotkey,
    unregister_hotkey,
    RegionSelector,
)
from logger import get_logger, enable_logging, disable_logging, set_log_level


# ============================================================================
# OCR Overlay Window (Separate, Always-on-Top, Transparent)
# ============================================================================

class OCROverlayWindow(QWidget):
    """
    Separate overlay window for displaying OCR results.
    
    Features:
    - Frameless window (no title bar) - drag anywhere to move
    - Toggleable always-on-top via pin button (default: unpinned)
    - Adjustable background transparency (text stays readable)
    - Resizable via corner grip
    - Can be shown/hidden independently of main window
    """
    
    def __init__(self, parent=None):
        """Initialize the overlay window."""
        # Frameless window without always-on-top by default
        super().__init__(parent, Qt.Window | Qt.Tool | Qt.FramelessWindowHint)
        self.setMinimumSize(OVERLAY_MIN_WIDTH, OVERLAY_MIN_HEIGHT)
        self.resize(OVERLAY_DEFAULT_WIDTH, OVERLAY_DEFAULT_HEIGHT)
        
        # Enable translucent background for proper transparency
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Track background opacity (0-255 for RGBA)
        self.bg_opacity = OVERLAY_DEFAULT_OPACITY
        
        # Track pinned state (always-on-top)
        self.is_pinned = False
        
        # For custom window dragging
        self._drag_pos = None
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the overlay UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Header with controls - use flexible layout
        header = QHBoxLayout()
        header.setSpacing(5)
        
        # Pin button (toggle always-on-top)
        self.pin_btn = QPushButton("PIN")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(False)
        self.pin_btn.setToolTip("Pin window to stay on top of other windows")
        self.pin_btn.clicked.connect(self.toggle_pin)
        self.update_pin_button_style()
        header.addWidget(self.pin_btn)
        
        # Opacity control - flexible width
        opacity_label = QLabel("Op:")
        opacity_label.setStyleSheet("color: white; font-size: 9pt;")
        header.addWidget(opacity_label)
        
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(50, 255)  # 20% to 100%
        self.opacity_slider.setValue(self.bg_opacity)
        self.opacity_slider.setMinimumWidth(50)
        self.opacity_slider.setMaximumWidth(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        self.opacity_slider.setStyleSheet(OPACITY_SLIDER_STYLE)
        header.addWidget(self.opacity_slider, 1)
        
        self.opacity_value_label = QLabel(f"{int(self.bg_opacity/255*100)}%")
        self.opacity_value_label.setStyleSheet("color: white; font-size: 9pt;")
        self.opacity_value_label.setMinimumWidth(30)
        header.addWidget(self.opacity_value_label)
        
        header.addStretch()
        
        # Copy button - with proper padding
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setStyleSheet(COPY_BUTTON_STYLE)
        self.copy_btn.clicked.connect(self.copy_text)
        header.addWidget(self.copy_btn)
        
        # Clear button - with proper padding
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(CLEAR_BUTTON_STYLE)
        self.clear_btn.clicked.connect(self.clear_text)
        header.addWidget(self.clear_btn)
        
        # Close button - with proper padding
        self.close_btn = QPushButton("X")
        self.close_btn.setStyleSheet(CLOSE_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        
        layout.addLayout(header)
        
        # OCR Result text area
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont(MONOSPACE_FONT, RESULT_FONT_SIZE))
        self.result_text.setPlaceholderText("OCR results will appear here...\n\nDrag anywhere to move this window.")
        self.result_text.setStyleSheet(RESULT_TEXT_STYLE)
        layout.addWidget(self.result_text)
        
        # Bottom row with status and resize grip
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(5)
        
        self.status_label = QLabel("Last update: --")
        self.status_label.setStyleSheet("color: #aaa; font-size: 9pt;")
        bottom_row.addWidget(self.status_label)
        
        bottom_row.addStretch()
        
        # Resize grip in bottom-right corner
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        bottom_row.addWidget(self.size_grip)
        
        layout.addLayout(bottom_row)
    
    def paintEvent(self, event):
        """Custom paint for semi-transparent background."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw rounded rectangle background
        painter.setBrush(QColor(40, 40, 40, self.bg_opacity))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
    
    def mousePressEvent(self, event):
        """Start dragging if clicking on empty area."""
        if event.button() == Qt.LeftButton:
            # Check if clicking on a child widget
            child = self.childAt(event.pos())
            if child is None or isinstance(child, QLabel):
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
            else:
                self._drag_pos = None
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle window dragging."""
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """End dragging."""
        self._drag_pos = None
        super().mouseReleaseEvent(event)
    
    def on_opacity_changed(self, value):
        """Handle opacity slider change."""
        self.bg_opacity = value
        self.opacity_value_label.setText(f"{int(value/255*100)}%")
        self.update()  # Trigger repaint
    
    def set_text(self, text):
        """Set the OCR result text."""
        self.result_text.setPlainText(text)
        self.status_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
    
    def append_text(self, text):
        """Append text to the result (for history mode)."""
        current = self.result_text.toPlainText()
        if current:
            self.result_text.setPlainText(f"{text}\n---\n{current}")
        else:
            self.result_text.setPlainText(text)
        self.status_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
    
    def copy_text(self):
        """Copy current text to clipboard."""
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
    
    def clear_text(self):
        """Clear the result text."""
        self.result_text.clear()
        self.status_label.setText("Cleared")
    
    def get_text(self):
        """Get current text."""
        return self.result_text.toPlainText()
    
    def toggle_pin(self):
        """Toggle always-on-top (pinned) state."""
        self.is_pinned = self.pin_btn.isChecked()
        
        # Need to hide and show to apply the flag change
        was_visible = self.isVisible()
        pos = self.pos()
        size = self.size()
        
        # Update window flags
        flags = Qt.Window | Qt.Tool | Qt.FramelessWindowHint
        if self.is_pinned:
            flags |= Qt.WindowStaysOnTopHint
        
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        self.update_pin_button_style()
        
        # Restore visibility and position
        if was_visible:
            self.show()
            self.move(pos)
            self.resize(size)
    
    def update_pin_button_style(self):
        """Update pin button appearance based on pinned state."""
        if self.is_pinned:
            self.pin_btn.setStyleSheet(PIN_BUTTON_ACTIVE_STYLE)
            self.pin_btn.setText("PINNED")
            self.pin_btn.setToolTip("Window stays on top - click to unpin")
        else:
            self.pin_btn.setStyleSheet(PIN_BUTTON_INACTIVE_STYLE)
            self.pin_btn.setText("PIN")
            self.pin_btn.setToolTip("Pin window to stay on top of other windows")


# ============================================================================
# Main Application Window
# ============================================================================

class OCRMonitorApp(QMainWindow):
    """
    Main application window with adaptive two-tier polling.
    
    Provides controls for:
    - Region selection for OCR monitoring
    - Start/stop monitoring
    - Language and sensitivity settings
    - Polling interval configuration
    - OCR overlay window management
    """
    
    def __init__(self):
        """Initialize the main application window."""
        super().__init__()
        
        self.selected_region = None
        self.is_monitoring = False
        self.ocr_worker = None
        
        # Adaptive timer - interval changes based on mode
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.check_for_changes)
        
        # Adaptive change detector
        self.change_detector = AdaptiveChangeDetector(
            threshold=5,
            stability_frames=3,
            max_wait_seconds=5,
            idle_interval_ms=1000,
            active_interval_ms=150,
            cooldown_ms=500
        )
        
        # Region selector
        self.region_selector = RegionSelector()
        self.region_selector.region_selected.connect(self.on_region_selected)
        self.region_selector.selection_cancelled.connect(self.on_selection_cancelled)
        
        # Screen capture
        self.mss_instance = mss.mss()
        self.last_captured_image = None
        
        # Stats
        self.ocr_count = 0
        self.capture_count = 0
        
        # OCR History (stores last 10 results)
        self.ocr_history = []  # List of (timestamp, full_text) tuples
        self.max_history_items = 10
        
        # Create the overlay window for OCR results
        self.overlay_window = OCROverlayWindow()
        
        self.init_ui()
        self.check_tesseract()
        
        # Load saved settings after UI is initialized
        self.load_settings()
        
        # Register global hotkey
        self.hotkey_registered = False
        QTimer.singleShot(100, self.register_global_hotkey)
    
    def init_ui(self):
        """Initialize the main UI components."""
        self.setWindowTitle("OCR Monitor - Adaptive Change Detection")
        # Minimum size to prevent text clipping
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self.resize(MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT)
        
        # Define fonts using QFont - compact sizes for better fit
        title_font = QFont(FONT_FAMILY, TITLE_FONT_SIZE)
        title_font.setBold(True)
        label_font = QFont(FONT_FAMILY, LABEL_FONT_SIZE)
        mode_font = QFont(FONT_FAMILY, MODE_FONT_SIZE)
        mode_font.setBold(True)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create scroll area for responsive design
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Main content widget inside scroll area (store reference for deferred sizing)
        self.scroll_content_widget = QWidget()
        top_layout = QVBoxLayout(self.scroll_content_widget)
        top_layout.setSpacing(15)
        top_layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== Status Section =====
        status_group = QGroupBox("Status")
        status_group.setFont(title_font)
        status_layout = QHBoxLayout(status_group)
        status_layout.setSpacing(15)
        status_layout.setContentsMargins(15, 20, 15, 10)
        
        self.tesseract_label = QLabel("Tesseract: Checking...")
        self.tesseract_label.setFont(label_font)
        self.tesseract_label.setWordWrap(True)
        self.region_label = QLabel("Region: Not selected")
        self.region_label.setFont(label_font)
        self.region_label.setWordWrap(True)
        self.monitor_label = QLabel("Monitoring: Off")
        self.monitor_label.setFont(label_font)
        self.monitor_label.setWordWrap(True)
        
        status_layout.addWidget(self.tesseract_label, 1)
        status_layout.addWidget(self.region_label, 1)
        status_layout.addWidget(self.monitor_label, 1)
        top_layout.addWidget(status_group)
        
        # ===== Adaptive Polling Status Section =====
        polling_group = QGroupBox("Adaptive Polling Status")
        polling_group.setFont(title_font)
        polling_layout = QVBoxLayout(polling_group)
        polling_layout.setSpacing(10)
        polling_layout.setContentsMargins(15, 20, 15, 10)
        
        # Mode indicator row - use flexible layout
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(15)
        self.mode_label = QLabel("Mode: IDLE")
        self.mode_label.setFont(mode_font)
        self.mode_label.setStyleSheet("color: #0066cc;")
        self.mode_label.setWordWrap(True)
        mode_layout.addWidget(self.mode_label, 1)
        
        self.interval_label = QLabel("Interval: 1000ms")
        self.interval_label.setFont(label_font)
        self.interval_label.setWordWrap(True)
        mode_layout.addWidget(self.interval_label, 1)
        polling_layout.addLayout(mode_layout)
        
        # Status line - enable word wrap for long status messages
        self.change_status_label = QLabel("Status: Waiting to start...")
        self.change_status_label.setFont(label_font)
        self.change_status_label.setStyleSheet("color: #444;")
        self.change_status_label.setWordWrap(True)
        polling_layout.addWidget(self.change_status_label)
        
        # Stats row - use flexible layout with word wrap
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)
        self.change_score_label = QLabel("Change: --")
        self.change_score_label.setFont(label_font)
        self.change_score_label.setWordWrap(True)
        self.stable_count_label = QLabel("Stable: --")
        self.stable_count_label.setFont(label_font)
        self.stable_count_label.setWordWrap(True)
        self.efficiency_label = QLabel("Efficiency: --")
        self.efficiency_label.setFont(label_font)
        self.efficiency_label.setWordWrap(True)
        stats_layout.addWidget(self.change_score_label, 1)
        stats_layout.addWidget(self.stable_count_label, 1)
        stats_layout.addWidget(self.efficiency_label, 1)
        polling_layout.addLayout(stats_layout)
        
        self.stats_label = QLabel("Captures: 0 | OCRs: 0")
        self.stats_label.setFont(label_font)
        self.stats_label.setWordWrap(True)
        polling_layout.addWidget(self.stats_label)
        
        top_layout.addWidget(polling_group)
        
        # ===== Settings Section =====
        settings_group = QGroupBox("Settings")
        settings_group.setFont(title_font)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(12)
        settings_layout.setContentsMargins(15, 20, 15, 10)
        
        # Row 1: Language - flexible layout with availability status
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        lang_label = QLabel("Language:")
        lang_label.setFont(label_font)
        lang_label.setWordWrap(True)
        row1.addWidget(lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.setFont(label_font)
        self.lang_combo.setMinimumWidth(200)
        self.lang_combo.setSizePolicy(self.lang_combo.sizePolicy().horizontalPolicy(), self.lang_combo.sizePolicy().verticalPolicy())
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        row1.addWidget(self.lang_combo, 1)
        row1.addStretch(1)
        settings_layout.addLayout(row1)
        
        # Language status label (shows availability info)
        self.lang_status_label = QLabel("")
        self.lang_status_label.setFont(label_font)
        self.lang_status_label.setWordWrap(True)
        self.lang_status_label.setStyleSheet("color: #666; font-size: 8pt;")
        settings_layout.addWidget(self.lang_status_label)
        
        # Populate language dropdown with availability status
        self.populate_language_dropdown()
        
        # Row 2: Polling intervals - use grid for better wrapping
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        idle_label = QLabel("Idle (ms):")
        idle_label.setFont(label_font)
        idle_label.setWordWrap(True)
        row2.addWidget(idle_label)
        self.idle_interval_spin = QSpinBox()
        self.idle_interval_spin.setFont(label_font)
        self.idle_interval_spin.setMinimumWidth(70)
        self.idle_interval_spin.setRange(500, 5000)
        self.idle_interval_spin.setValue(1000)
        self.idle_interval_spin.setSingleStep(100)
        row2.addWidget(self.idle_interval_spin)
        
        row2.addSpacing(15)
        
        active_label = QLabel("Active (ms):")
        active_label.setFont(label_font)
        active_label.setWordWrap(True)
        row2.addWidget(active_label)
        self.active_interval_spin = QSpinBox()
        self.active_interval_spin.setFont(label_font)
        self.active_interval_spin.setMinimumWidth(70)
        self.active_interval_spin.setRange(50, 500)
        self.active_interval_spin.setValue(150)
        self.active_interval_spin.setSingleStep(25)
        row2.addWidget(self.active_interval_spin)
        row2.addStretch()
        settings_layout.addLayout(row2)
        
        # Row 3: Sensitivity - SpinBox (1-20, lower = more sensitive)
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        sens_label = QLabel("Sensitivity:")
        sens_label.setFont(label_font)
        sens_label.setWordWrap(True)
        row3.addWidget(sens_label)
        self.sensitivity_spin = QSpinBox()
        self.sensitivity_spin.setFont(label_font)
        self.sensitivity_spin.setMinimumWidth(70)
        self.sensitivity_spin.setRange(1, 20)
        self.sensitivity_spin.setValue(5)
        self.sensitivity_spin.valueChanged.connect(self.on_sensitivity_changed)
        row3.addWidget(self.sensitivity_spin)
        self.sensitivity_label = QLabel("(Medium)")
        self.sensitivity_label.setFont(label_font)
        self.sensitivity_label.setMinimumWidth(80)
        self.sensitivity_label.setWordWrap(True)
        row3.addWidget(self.sensitivity_label)
        row3.addStretch()
        settings_layout.addLayout(row3)
        
        # Row 4: Stability and max wait - flexible layout
        row4 = QHBoxLayout()
        row4.setSpacing(10)
        stab_label = QLabel("Stability:")
        stab_label.setFont(label_font)
        stab_label.setWordWrap(True)
        row4.addWidget(stab_label)
        self.stability_spin = QSpinBox()
        self.stability_spin.setFont(label_font)
        self.stability_spin.setMinimumWidth(60)
        self.stability_spin.setRange(1, 10)
        self.stability_spin.setValue(3)
        row4.addWidget(self.stability_spin)
        
        row4.addSpacing(15)
        
        wait_label = QLabel("Max Wait (s):")
        wait_label.setFont(label_font)
        wait_label.setWordWrap(True)
        row4.addWidget(wait_label)
        self.max_wait_spin = QSpinBox()
        self.max_wait_spin.setFont(label_font)
        self.max_wait_spin.setMinimumWidth(60)
        self.max_wait_spin.setRange(1, 30)
        self.max_wait_spin.setValue(5)
        row4.addWidget(self.max_wait_spin)
        row4.addStretch()
        settings_layout.addLayout(row4)
        
        # Row 5: Debug Logging - simple checkbox style
        row5 = QHBoxLayout()
        row5.setSpacing(10)
        debug_label = QLabel("Debug Log:")
        debug_label.setFont(label_font)
        debug_label.setWordWrap(True)
        row5.addWidget(debug_label)
        self.debug_log_checkbox = QPushButton("Logging ON")
        self.debug_log_checkbox.setFont(label_font)
        self.debug_log_checkbox.setCheckable(True)
        self.debug_log_checkbox.setChecked(True)
        self.debug_log_checkbox.clicked.connect(self.on_debug_log_toggled)
        row5.addWidget(self.debug_log_checkbox)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.setFont(label_font)
        self.log_level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
        self.log_level_combo.setCurrentText('DEBUG')
        self.log_level_combo.currentTextChanged.connect(self.on_log_level_changed)
        row5.addWidget(self.log_level_combo)
        row5.addStretch()
        settings_layout.addLayout(row5)
        
        top_layout.addWidget(settings_group)
        
        # ===== Controls Section =====
        controls_group = QGroupBox("Controls")
        controls_group.setFont(title_font)
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(10)
        controls_layout.setContentsMargins(15, 20, 15, 10)
        
        self.select_btn = QPushButton("Select Region\n(Ctrl+Shift+X)")
        self.select_btn.setFont(label_font)
        self.select_btn.setStyleSheet("padding: 8px 16px;")
        self.select_btn.setMinimumHeight(self.select_btn.sizeHint().height())
        self.select_btn.clicked.connect(self.show_region_selector)
        controls_layout.addWidget(self.select_btn, 1)
        
        # Single toggle button for Start/Stop monitoring
        self.toggle_monitor_btn = QPushButton("Start\nMonitoring")
        self.toggle_monitor_btn.setFont(label_font)
        self.toggle_monitor_btn.setStyleSheet("background-color: #00aa00; color: white; padding: 8px 16px;")
        self.toggle_monitor_btn.setMinimumHeight(self.toggle_monitor_btn.sizeHint().height())
        self.toggle_monitor_btn.clicked.connect(self.toggle_monitoring)
        self.toggle_monitor_btn.setEnabled(False)
        controls_layout.addWidget(self.toggle_monitor_btn, 1)
        
        top_layout.addWidget(controls_group)
        
        # ===== Overlay Controls Section =====
        overlay_group = QGroupBox("OCR Results Overlay")
        overlay_group.setFont(title_font)
        overlay_layout = QVBoxLayout(overlay_group)
        overlay_layout.setSpacing(10)
        overlay_layout.setContentsMargins(15, 20, 15, 10)
        
        # Buttons row
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        
        self.show_overlay_btn = QPushButton("Show Overlay\nWindow")
        self.show_overlay_btn.setFont(label_font)
        self.show_overlay_btn.setStyleSheet("background-color: #0078d4; color: white; padding: 8px 16px;")
        self.show_overlay_btn.setMinimumHeight(self.show_overlay_btn.sizeHint().height())
        self.show_overlay_btn.clicked.connect(self.toggle_overlay)
        buttons_row.addWidget(self.show_overlay_btn, 1)
        
        self.copy_btn = QPushButton("Copy Text")
        self.copy_btn.setFont(label_font)
        self.copy_btn.setStyleSheet("padding: 8px 16px;")
        self.copy_btn.setMinimumHeight(self.copy_btn.sizeHint().height())
        self.copy_btn.clicked.connect(self.copy_text)
        buttons_row.addWidget(self.copy_btn, 1)
        
        # Removed addStretch(1) to prevent stealing horizontal space from buttons
        overlay_layout.addLayout(buttons_row)
        
        overlay_info = QLabel("OCR results appear in a separate overlay window that can be positioned over your game.")
        overlay_info.setFont(label_font)
        overlay_info.setStyleSheet("color: #666;")
        overlay_info.setWordWrap(True)
        overlay_layout.addWidget(overlay_info)
        
        top_layout.addWidget(overlay_group)
        
        # ===== OCR History Section =====
        history_group = QGroupBox("OCR History (Last 10)")
        history_group.setFont(title_font)
        history_layout = QVBoxLayout(history_group)
        history_layout.setSpacing(10)
        history_layout.setContentsMargins(15, 20, 15, 10)
        
        self.history_list = QListWidget()
        self.history_list.setFont(label_font)
        self.history_list.setMinimumHeight(120)
        self.history_list.setMaximumHeight(180)
        self.history_list.setAlternatingRowColors(True)
        self.history_list.itemClicked.connect(self.on_history_item_clicked)
        self.history_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #e5f3ff;
            }
        """)
        history_layout.addWidget(self.history_list)
        
        # History buttons row
        history_buttons = QHBoxLayout()
        history_buttons.setSpacing(10)
        
        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.setFont(label_font)
        self.clear_history_btn.setStyleSheet("padding: 5px 10px;")
        self.clear_history_btn.clicked.connect(self.clear_history)
        history_buttons.addWidget(self.clear_history_btn)
        
        history_buttons.addStretch()
        history_layout.addLayout(history_buttons)
        
        history_info = QLabel("Click an item to view full text in overlay window")
        history_info.setFont(label_font)
        history_info.setStyleSheet("color: #666;")
        history_layout.addWidget(history_info)
        
        top_layout.addWidget(history_group)
        
        # Instructions at bottom of scrollable content
        instructions = QLabel(
            "Adaptive Two-Tier Polling: IDLE (slow) when nothing changes | ACTIVE (fast) when changes detected | OCR when stable"
        )
        instructions.setFont(QFont(FONT_FAMILY, 9))
        instructions.setStyleSheet("color: #666; padding: 5px;")
        instructions.setWordWrap(True)
        top_layout.addWidget(instructions)
        
        # Add stretch to push everything up within scroll area
        top_layout.addStretch()
        
        # Set the scroll area widget and add to main layout
        scroll_area.setWidget(self.scroll_content_widget)
        main_layout.addWidget(scroll_area)
        
        # Defer minimum size calculation until after show() for accurate metrics
        QTimer.singleShot(0, self._set_scroll_content_minimum_size)
    
    def _set_scroll_content_minimum_size(self):
        """Set scroll content minimum size after window is shown for accurate metrics."""
        content_size = self.scroll_content_widget.sizeHint()
        self.scroll_content_widget.setMinimumSize(content_size.width(), content_size.height())
    
    def on_sensitivity_changed(self, value):
        """Handle sensitivity spinbox change."""
        # Lower value = more sensitive (detects smaller changes)
        if value <= 2:
            label = "Very High"
        elif value <= 5:
            label = "High" if value <= 3 else "Medium"
        elif value <= 10:
            label = "Low"
        else:
            label = "Very Low"
        self.sensitivity_label.setText(f"({label})")
    
    def on_debug_log_toggled(self, checked):
        """Handle debug logging toggle."""
        if checked:
            enable_logging()
            self.debug_log_checkbox.setText("Logging ON")
        else:
            disable_logging()
            self.debug_log_checkbox.setText("Logging OFF")
    
    def on_log_level_changed(self, level):
        """Handle log level change."""
        set_log_level(level)
    
    def get_settings_path(self):
        """Get the path to the settings file."""
        # Store settings in the same directory as the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'ocr_settings.json')
    
    def save_settings(self):
        """Save current settings to JSON file including window positions."""
        # Get main window geometry
        main_geom = self.geometry()
        
        # Get overlay window geometry
        overlay_geom = self.overlay_window.geometry()
        
        settings = {
            'language_index': self.lang_combo.currentIndex(),
            'idle_interval': self.idle_interval_spin.value(),
            'active_interval': self.active_interval_spin.value(),
            'sensitivity': self.sensitivity_spin.value(),
            'stability': self.stability_spin.value(),
            'max_wait': self.max_wait_spin.value(),
            # Main window position and size
            'window_x': main_geom.x(),
            'window_y': main_geom.y(),
            'window_width': main_geom.width(),
            'window_height': main_geom.height(),
            # Overlay window position and size
            'overlay_x': overlay_geom.x(),
            'overlay_y': overlay_geom.y(),
            'overlay_width': overlay_geom.width(),
            'overlay_height': overlay_geom.height(),
            # Debug logging settings
            'debug_logging_enabled': self.debug_log_checkbox.isChecked(),
            'log_level': self.log_level_combo.currentText(),
        }
        
        try:
            with open(self.get_settings_path(), 'w') as f:
                json.dump(settings, f, indent=2)
            print(f"Settings saved to {self.get_settings_path()}")
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def load_settings(self):
        """Load settings from JSON file including window positions."""
        settings_path = self.get_settings_path()
        
        if not os.path.exists(settings_path):
            print("No saved settings found, using defaults")
            return
        
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
            
            # Apply loaded settings
            if 'language_index' in settings:
                index = settings['language_index']
                if 0 <= index < self.lang_combo.count():
                    self.lang_combo.setCurrentIndex(index)
            
            if 'idle_interval' in settings:
                self.idle_interval_spin.setValue(settings['idle_interval'])
            
            if 'active_interval' in settings:
                self.active_interval_spin.setValue(settings['active_interval'])
            
            if 'sensitivity' in settings:
                self.sensitivity_spin.setValue(settings['sensitivity'])
            
            if 'stability' in settings:
                self.stability_spin.setValue(settings['stability'])
            
            if 'max_wait' in settings:
                self.max_wait_spin.setValue(settings['max_wait'])
            
            # Restore main window position and size
            if all(k in settings for k in ['window_x', 'window_y', 'window_width', 'window_height']):
                self.setGeometry(
                    settings['window_x'],
                    settings['window_y'],
                    settings['window_width'],
                    settings['window_height']
                )
            
            # Restore overlay window position and size
            if all(k in settings for k in ['overlay_x', 'overlay_y', 'overlay_width', 'overlay_height']):
                self.overlay_window.setGeometry(
                    settings['overlay_x'],
                    settings['overlay_y'],
                    settings['overlay_width'],
                    settings['overlay_height']
                )
            
            # Restore debug logging settings
            if 'debug_logging_enabled' in settings:
                enabled = settings['debug_logging_enabled']
                self.debug_log_checkbox.setChecked(enabled)
                if enabled:
                    enable_logging()
                    self.debug_log_checkbox.setText("Logging ON")
                else:
                    disable_logging()
                    self.debug_log_checkbox.setText("Logging OFF")
            
            if 'log_level' in settings:
                level = settings['log_level']
                if level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                    self.log_level_combo.setCurrentText(level)
                    set_log_level(level)
            
            print(f"Settings loaded from {settings_path}")
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def populate_language_dropdown(self):
        """
        Populate the language dropdown with availability status.
        
        Shows checkmarks for available languages and X marks for missing ones.
        Stores the actual language code as item data for retrieval.
        """
        self.installed_languages = get_installed_languages()
        self.lang_combo.clear()
        
        # Store language codes for each item
        self.language_codes = []
        
        for lang_code in DEFAULT_LANGUAGES:
            display_name = get_language_display_name(lang_code)
            is_available, missing = check_language_availability(lang_code, self.installed_languages)
            
            if is_available:
                # Available language - show with checkmark
                item_text = f"{display_name} ({lang_code})"
                self.lang_combo.addItem(item_text)
            else:
                # Missing language - show with X mark
                item_text = f"{display_name} ({lang_code}) [Not Installed]"
                self.lang_combo.addItem(item_text)
            
            self.language_codes.append(lang_code)
        
        # Update status label for initial selection
        self.update_language_status()
    
    def on_language_changed(self, index):
        """Handle language selection change."""
        if index >= 0:
            self.update_language_status()
    
    def update_language_status(self):
        """Update the language status label based on current selection."""
        index = self.lang_combo.currentIndex()
        if index < 0 or index >= len(self.language_codes):
            return
        
        lang_code = self.language_codes[index]
        is_available, missing = check_language_availability(lang_code, self.installed_languages)
        
        if is_available:
            self.lang_status_label.setText("Language pack installed and ready to use.")
            self.lang_status_label.setStyleSheet("color: green; font-size: 8pt;")
        else:
            missing_str = ', '.join(missing)
            self.lang_status_label.setText(
                f"Missing language pack(s): {missing_str}\n"
                f"Install via Tesseract installer or download .traineddata files to tessdata folder."
            )
            self.lang_status_label.setStyleSheet("color: #cc6600; font-size: 8pt;")
    
    def get_selected_language(self):
        """Get the actual language code for the selected item."""
        index = self.lang_combo.currentIndex()
        if index >= 0 and index < len(self.language_codes):
            return self.language_codes[index]
        return 'eng'  # Default fallback
    
    def check_tesseract(self):
        """Check if Tesseract is installed and update UI accordingly."""
        if TESSERACT_PATH:
            self.tesseract_label.setText("Tesseract: Found")
            self.tesseract_label.setStyleSheet("color: green;")
        else:
            self.tesseract_label.setText("Tesseract: NOT FOUND")
            self.tesseract_label.setStyleSheet("color: red;")
            QMessageBox.warning(
                self, "Tesseract Not Found",
                "Tesseract OCR is not installed.\n\n"
                "Please install from:\n"
                "https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "Install to: C:\\Program Files\\Tesseract-OCR\n"
                "Then restart this application."
            )
    
    def register_global_hotkey(self):
        """Register the global hotkey (Ctrl+Shift+X)."""
        hwnd = int(self.winId())
        if register_hotkey(hwnd):
            self.hotkey_registered = True
            print("Global hotkey Ctrl+Shift+X registered")
        else:
            print("Failed to register global hotkey")
    
    def nativeEvent(self, eventType, message):
        """Handle native Windows events for hotkey."""
        if sys.platform == 'win32' and eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.show_region_selector()
                return True, 0
        return super().nativeEvent(eventType, message)
    
    def show_region_selector(self):
        """Show the region selection overlay."""
        if self.is_monitoring:
            self.stop_monitoring()
        self.region_selector.show()
        self.region_selector.activateWindow()
    
    def on_region_selected(self, rect):
        """Handle region selection completion."""
        self.selected_region = {
            'left': rect.x(),
            'top': rect.y(),
            'width': rect.width(),
            'height': rect.height()
        }
        self.region_label.setText(f"Region: {rect.width()}x{rect.height()}")
        self.region_label.setStyleSheet("color: green;")
        
        self.toggle_monitor_btn.setEnabled(True)
        self.change_detector.reset()
        
        self.showNormal()
        self.activateWindow()
    
    def on_selection_cancelled(self):
        """Handle region selection cancellation."""
        self.showNormal()
        self.activateWindow()
    
    def capture_region(self):
        """Capture the selected screen region."""
        if not self.selected_region:
            return None
        
        try:
            screenshot = self.mss_instance.grab(self.selected_region)
            img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
            return img
        except Exception as e:
            print(f"Capture error: {e}")
            return None
    
    def check_for_changes(self):
        """Called by timer - adaptive polling logic."""
        if not self.is_monitoring or not self.selected_region:
            return
        
        # Skip if OCR is already running
        if self.ocr_worker and self.ocr_worker.isRunning():
            return
        
        # Capture current frame
        image = self.capture_region()
        if image is None:
            return
        
        self.capture_count += 1
        self.last_captured_image = image
        
        # Check for changes with adaptive detector
        result = self.change_detector.check_frame(image)
        
        # Update UI - Mode indicator
        mode = result['mode'].upper()
        if mode == "IDLE":
            self.mode_label.setText("Mode: IDLE (slow)")
            self.mode_label.setStyleSheet("color: #0066cc; font-weight: bold; font-size: 14px;")
        elif mode == "ACTIVE":
            self.mode_label.setText("Mode: ACTIVE (fast)")
            self.mode_label.setStyleSheet("color: #cc6600; font-weight: bold; font-size: 14px;")
        elif mode == "COOLDOWN":
            self.mode_label.setText("Mode: COOLDOWN")
            self.mode_label.setStyleSheet("color: #666666; font-weight: bold; font-size: 14px;")
        
        self.interval_label.setText(f"Interval: {result['next_interval_ms']}ms")
        self.change_status_label.setText(f"Status: {result['reason']}")
        self.change_score_label.setText(f"Change: {result['change_score']:.1f}")
        self.stable_count_label.setText(f"Stable: {result['stable_count']}/{self.stability_spin.value()}")
        self.efficiency_label.setText(f"Poll: {self.change_detector.get_stats()}")
        self.stats_label.setText(f"Captures: {self.capture_count} | OCRs: {self.ocr_count}")
        
        # Adjust timer interval if needed
        current_interval = self.capture_timer.interval()
        if current_interval != result['next_interval_ms']:
            self.capture_timer.setInterval(result['next_interval_ms'])
        
        # Run OCR if needed
        if result['should_ocr']:
            self.run_ocr(image)
    
    def run_ocr(self, image):
        """Run OCR on the given image."""
        if not TESSERACT_PATH:
            return
        
        self.ocr_count += 1
        
        # Use get_selected_language to get the actual language code
        self.ocr_worker = OCRWorker(image, self.get_selected_language())
        self.ocr_worker.result_ready.connect(self.on_ocr_result)
        self.ocr_worker.error_occurred.connect(self.on_ocr_error)
        self.ocr_worker.finished.connect(lambda: self.change_detector.mark_ocr_done(image))
        self.ocr_worker.start()
    
    def toggle_overlay(self):
        """Show or hide the OCR overlay window."""
        if self.overlay_window.isVisible():
            self.overlay_window.hide()
            self.show_overlay_btn.setText("Show Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #0078d4; color: white; padding: 8px 16px;")
        else:
            self.overlay_window.show()
            self.show_overlay_btn.setText("Hide Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def on_ocr_result(self, text, elapsed):
        """Handle OCR result - send to overlay window and add to history."""
        result_text = text if text else "(No text detected)"
        self.overlay_window.set_text(result_text)
        
        # Add to history (only if actual text was detected)
        if text:
            self.add_to_history(text)
        
        # Show overlay if not visible
        if not self.overlay_window.isVisible():
            self.overlay_window.show()
            self.show_overlay_btn.setText("Hide Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def on_ocr_error(self, error):
        """Handle OCR error - show in overlay window."""
        self.overlay_window.set_text(f"Error: {error}")
        if "Failed loading language" in error:
            QMessageBox.warning(
                self, "Language Pack Missing",
                "The selected language pack is not installed.\n"
                "Please reinstall Tesseract and select the required language packs."
            )
    
    def add_to_history(self, text):
        """Add OCR result to history list."""
        if not text or text == "(No text detected)":
            return
        
        # Create timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Store full text in history
        self.ocr_history.insert(0, (timestamp, text))
        
        # Limit history size
        if len(self.ocr_history) > self.max_history_items:
            self.ocr_history = self.ocr_history[:self.max_history_items]
        
        # Update the list widget
        self.update_history_list()
    
    def update_history_list(self):
        """Update the history list widget from stored history."""
        self.history_list.clear()
        
        for timestamp, text in self.ocr_history:
            # Create preview (first 50 chars, single line)
            preview = text.replace('\n', ' ').strip()
            if len(preview) > 50:
                preview = preview[:47] + "..."
            
            item_text = f"[{timestamp}] {preview}"
            item = QListWidgetItem(item_text)
            item.setToolTip(text[:200] + "..." if len(text) > 200 else text)
            self.history_list.addItem(item)
    
    def on_history_item_clicked(self, item):
        """Handle click on history item - show full text in overlay."""
        index = self.history_list.row(item)
        if 0 <= index < len(self.ocr_history):
            timestamp, full_text = self.ocr_history[index]
            self.overlay_window.set_text(full_text)
            
            # Show overlay if not visible
            if not self.overlay_window.isVisible():
                self.overlay_window.show()
                self.show_overlay_btn.setText("Hide Overlay\nWindow")
                self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def clear_history(self):
        """Clear all OCR history."""
        self.ocr_history.clear()
        self.history_list.clear()
    
    def toggle_monitoring(self):
        """Toggle monitoring on/off."""
        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()
    
    def start_monitoring(self):
        """Start monitoring the selected region."""
        if not self.selected_region:
            return
        
        # Update change detector settings
        self.change_detector.threshold = self.sensitivity_spin.value()
        self.change_detector.stability_frames = self.stability_spin.value()
        self.change_detector.max_wait_seconds = self.max_wait_spin.value()
        self.change_detector.idle_interval_ms = self.idle_interval_spin.value()
        self.change_detector.active_interval_ms = self.active_interval_spin.value()
        self.change_detector.reset()
        
        self.is_monitoring = True
        self.capture_count = 0
        self.ocr_count = 0
        
        # Start in idle mode
        initial_interval = self.change_detector.idle_interval_ms
        self.capture_timer.start(initial_interval)
        
        self.monitor_label.setText("Monitoring: Active")
        self.monitor_label.setStyleSheet("color: green;")
        
        # Update toggle button to show Stop state
        self.toggle_monitor_btn.setText("Stop\nMonitoring")
        self.toggle_monitor_btn.setStyleSheet("background-color: #aa0000; color: white; padding: 8px 16px;")
        self.select_btn.setEnabled(False)
        
        # Disable settings while monitoring
        self.idle_interval_spin.setEnabled(False)
        self.active_interval_spin.setEnabled(False)
        self.sensitivity_spin.setEnabled(False)
        self.stability_spin.setEnabled(False)
        self.max_wait_spin.setEnabled(False)
    
    def stop_monitoring(self):
        """Stop monitoring."""
        self.is_monitoring = False
        self.capture_timer.stop()
        
        self.monitor_label.setText("Monitoring: Off")
        self.monitor_label.setStyleSheet("")
        self.mode_label.setText("Mode: --")
        self.mode_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.change_status_label.setText("Status: Stopped")
        
        # Update toggle button to show Start state
        self.toggle_monitor_btn.setText("Start\nMonitoring")
        self.toggle_monitor_btn.setStyleSheet("background-color: #00aa00; color: white; padding: 8px 16px;")
        self.select_btn.setEnabled(True)
        
        # Re-enable settings
        self.idle_interval_spin.setEnabled(True)
        self.active_interval_spin.setEnabled(True)
        self.sensitivity_spin.setEnabled(True)
        self.stability_spin.setEnabled(True)
        self.max_wait_spin.setEnabled(True)
    
    def copy_text(self):
        """Copy text from overlay window to clipboard."""
        text = self.overlay_window.get_text()
        if text and text != "(No text detected)" and not text.startswith("OCR results"):
            QApplication.clipboard().setText(text)
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy Text"))
    
    def closeEvent(self, event):
        """Handle application close."""
        self.stop_monitoring()
        
        # Save settings before closing
        self.save_settings()
        
        # Close overlay window
        self.overlay_window.close()
        
        if self.hotkey_registered:
            unregister_hotkey(int(self.winId()))
        
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.quit()
            self.ocr_worker.wait()
        
        event.accept()
