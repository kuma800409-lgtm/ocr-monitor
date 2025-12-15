"""
UI module for OCR Monitor application.

Contains all PyQt UI components including:
- OCROverlayWindow: Separate overlay window for displaying OCR results
- OCRMonitorApp: Main application window with controls and settings

This module focuses on UI presentation and delegates business logic to the controller.
"""

import sys
import os
import ctypes
from datetime import datetime

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

from config import (
    MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT,
    OVERLAY_MIN_WIDTH, OVERLAY_MIN_HEIGHT,
    OVERLAY_DEFAULT_WIDTH, OVERLAY_DEFAULT_HEIGHT,
    OVERLAY_DEFAULT_OPACITY,
    WM_HOTKEY, HOTKEY_ID,
    OPACITY_SLIDER_STYLE, COPY_BUTTON_STYLE, CLEAR_BUTTON_STYLE,
    CLOSE_BUTTON_STYLE, PIN_BUTTON_ACTIVE_STYLE, PIN_BUTTON_INACTIVE_STYLE,
    RESULT_TEXT_STYLE,
    FONT_FAMILY, MONOSPACE_FONT,
    TITLE_FONT_SIZE, LABEL_FONT_SIZE, MODE_FONT_SIZE, RESULT_FONT_SIZE,
)
from ocr_engine import TESSERACT_PATH
from utils import register_hotkey, unregister_hotkey, RegionSelector
from controller import OCRMonitorController


class OCROverlayWindow(QWidget):
    """Separate overlay window for displaying OCR results."""
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.Tool | Qt.FramelessWindowHint)
        self.setMinimumSize(OVERLAY_MIN_WIDTH, OVERLAY_MIN_HEIGHT)
        self.resize(OVERLAY_DEFAULT_WIDTH, OVERLAY_DEFAULT_HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.bg_opacity = OVERLAY_DEFAULT_OPACITY
        self.is_pinned = False
        self._drag_pos = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)
        
        header = QHBoxLayout()
        header.setSpacing(5)
        
        self.pin_btn = QPushButton("PIN")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(False)
        self.pin_btn.setToolTip("Pin window to stay on top")
        self.pin_btn.clicked.connect(self.toggle_pin)
        self.update_pin_button_style()
        header.addWidget(self.pin_btn)
        
        opacity_label = QLabel("Op:")
        opacity_label.setStyleSheet("color: white; font-size: 9pt;")
        header.addWidget(opacity_label)
        
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(50, 255)
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
        
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setStyleSheet(COPY_BUTTON_STYLE)
        self.copy_btn.clicked.connect(self.copy_text)
        header.addWidget(self.copy_btn)
        
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(CLEAR_BUTTON_STYLE)
        self.clear_btn.clicked.connect(self.clear_text)
        header.addWidget(self.clear_btn)
        
        self.close_btn = QPushButton("X")
        self.close_btn.setStyleSheet(CLOSE_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        
        layout.addLayout(header)
        
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont(MONOSPACE_FONT, RESULT_FONT_SIZE))
        self.result_text.setPlaceholderText("OCR results will appear here...")
        self.result_text.setStyleSheet(RESULT_TEXT_STYLE)
        layout.addWidget(self.result_text)
        
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(5)
        self.status_label = QLabel("Last update: --")
        self.status_label.setStyleSheet("color: #aaa; font-size: 9pt;")
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        bottom_row.addWidget(self.size_grip)
        layout.addLayout(bottom_row)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(40, 40, 40, self.bg_opacity))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
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
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)
    
    def on_opacity_changed(self, value):
        self.bg_opacity = value
        self.opacity_value_label.setText(f"{int(value/255*100)}%")
        self.update()
    
    def set_text(self, text):
        self.result_text.setPlainText(text)
        self.status_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
    
    def append_text(self, text):
        current = self.result_text.toPlainText()
        if current:
            self.result_text.setPlainText(f"{text}\n---\n{current}")
        else:
            self.result_text.setPlainText(text)
        self.status_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
    
    def copy_text(self):
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
    
    def clear_text(self):
        self.result_text.clear()
        self.status_label.setText("Cleared")
    
    def get_text(self):
        return self.result_text.toPlainText()
    
    def toggle_pin(self):
        self.is_pinned = self.pin_btn.isChecked()
        was_visible = self.isVisible()
        pos = self.pos()
        size = self.size()
        flags = Qt.Window | Qt.Tool | Qt.FramelessWindowHint
        if self.is_pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.update_pin_button_style()
        if was_visible:
            self.show()
            self.move(pos)
            self.resize(size)
    
    def update_pin_button_style(self):
        if self.is_pinned:
            self.pin_btn.setStyleSheet(PIN_BUTTON_ACTIVE_STYLE)
            self.pin_btn.setText("PINNED")
            self.pin_btn.setToolTip("Window stays on top - click to unpin")
        else:
            self.pin_btn.setStyleSheet(PIN_BUTTON_INACTIVE_STYLE)
            self.pin_btn.setText("PIN")
            self.pin_btn.setToolTip("Pin window to stay on top")


class OCRMonitorApp(QMainWindow):
    """Main application window. Business logic delegated to OCRMonitorController."""
    
    def __init__(self):
        super().__init__()
        self.overlay_window = OCROverlayWindow()
        self.controller = OCRMonitorController(self)
        self._connect_controller_signals()
        self.region_selector = RegionSelector()
        self.region_selector.region_selected.connect(self._on_region_selected)
        self.region_selector.selection_cancelled.connect(self._on_selection_cancelled)
        self.init_ui()
        self.controller.check_tesseract()
        self._load_settings()
        self.hotkey_registered = False
        QTimer.singleShot(100, self._register_global_hotkey)
    
    def _connect_controller_signals(self):
        self.controller.monitoring_started.connect(self._on_monitoring_started)
        self.controller.monitoring_stopped.connect(self._on_monitoring_stopped)
        self.controller.polling_state_changed.connect(self._on_polling_state_changed)
        self.controller.ocr_result_ready.connect(self._on_ocr_result)
        self.controller.ocr_error.connect(self._on_ocr_error)
        self.controller.history_updated.connect(self._on_history_updated)
        self.controller.region_selected.connect(self._on_region_set)
        self.controller.tesseract_status.connect(self._on_tesseract_status)
    
    def init_ui(self):
        self.setWindowTitle("OCR Monitor - Adaptive Change Detection")
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self.resize(MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT)
        
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
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.scroll_content_widget = QWidget()
        top_layout = QVBoxLayout(self.scroll_content_widget)
        top_layout.setSpacing(15)
        top_layout.setContentsMargins(20, 20, 20, 20)
        
        # Status Section
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
        
        # Polling Status Section
        polling_group = QGroupBox("Adaptive Polling Status")
        polling_group.setFont(title_font)
        polling_layout = QVBoxLayout(polling_group)
        polling_layout.setSpacing(10)
        polling_layout.setContentsMargins(15, 20, 15, 10)
        
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
        
        self.change_status_label = QLabel("Status: Waiting to start...")
        self.change_status_label.setFont(label_font)
        self.change_status_label.setStyleSheet("color: #444;")
        self.change_status_label.setWordWrap(True)
        polling_layout.addWidget(self.change_status_label)
        
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

        # Settings Section
        settings_group = QGroupBox("Settings")
        settings_group.setFont(title_font)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(12)
        settings_layout.setContentsMargins(15, 20, 15, 10)
        
        # Language row
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        lang_label = QLabel("Language:")
        lang_label.setFont(label_font)
        row1.addWidget(lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.setFont(label_font)
        self.lang_combo.setMinimumWidth(200)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        row1.addWidget(self.lang_combo, 1)
        row1.addStretch(1)
        settings_layout.addLayout(row1)
        
        self.lang_status_label = QLabel("")
        self.lang_status_label.setFont(label_font)
        self.lang_status_label.setWordWrap(True)
        self.lang_status_label.setStyleSheet("color: #666; font-size: 8pt;")
        settings_layout.addWidget(self.lang_status_label)
        
        self._populate_language_dropdown()
        
        # Polling intervals row
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        idle_label = QLabel("Idle (ms):")
        idle_label.setFont(label_font)
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
        
        # Sensitivity row
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        sens_label = QLabel("Sensitivity:")
        sens_label.setFont(label_font)
        row3.addWidget(sens_label)
        self.sensitivity_spin = QSpinBox()
        self.sensitivity_spin.setFont(label_font)
        self.sensitivity_spin.setMinimumWidth(70)
        self.sensitivity_spin.setRange(1, 20)
        self.sensitivity_spin.setValue(5)
        self.sensitivity_spin.valueChanged.connect(self._on_sensitivity_changed)
        row3.addWidget(self.sensitivity_spin)
        self.sensitivity_label = QLabel("(Medium)")
        self.sensitivity_label.setFont(label_font)
        self.sensitivity_label.setMinimumWidth(80)
        row3.addWidget(self.sensitivity_label)
        row3.addStretch()
        settings_layout.addLayout(row3)
        
        # Stability row
        row4 = QHBoxLayout()
        row4.setSpacing(10)
        stab_label = QLabel("Stability:")
        stab_label.setFont(label_font)
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
        row4.addWidget(wait_label)
        self.max_wait_spin = QSpinBox()
        self.max_wait_spin.setFont(label_font)
        self.max_wait_spin.setMinimumWidth(60)
        self.max_wait_spin.setRange(1, 30)
        self.max_wait_spin.setValue(5)
        row4.addWidget(self.max_wait_spin)
        row4.addStretch()
        settings_layout.addLayout(row4)
        
        # Debug logging row
        row5 = QHBoxLayout()
        row5.setSpacing(10)
        debug_label = QLabel("Debug Log:")
        debug_label.setFont(label_font)
        row5.addWidget(debug_label)
        self.debug_log_checkbox = QPushButton("Logging ON")
        self.debug_log_checkbox.setFont(label_font)
        self.debug_log_checkbox.setCheckable(True)
        self.debug_log_checkbox.setChecked(True)
        self.debug_log_checkbox.clicked.connect(self._on_debug_log_toggled)
        row5.addWidget(self.debug_log_checkbox)
        self.log_level_combo = QComboBox()
        self.log_level_combo.setFont(label_font)
        self.log_level_combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
        self.log_level_combo.setCurrentText('DEBUG')
        self.log_level_combo.currentTextChanged.connect(self._on_log_level_changed)
        row5.addWidget(self.log_level_combo)
        row5.addStretch()
        settings_layout.addLayout(row5)
        
        top_layout.addWidget(settings_group)

        # Controls Section
        controls_group = QGroupBox("Controls")
        controls_group.setFont(title_font)
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(15)
        controls_layout.setContentsMargins(15, 20, 15, 10)
        
        self.select_btn = QPushButton("Select Region\n(Ctrl+Shift+X)")
        self.select_btn.setFont(label_font)
        self.select_btn.setStyleSheet("background-color: #0078d4; color: white; padding: 8px 16px;")
        self.select_btn.clicked.connect(self._show_region_selector)
        controls_layout.addWidget(self.select_btn)
        
        self.toggle_monitor_btn = QPushButton("Start\nMonitoring")
        self.toggle_monitor_btn.setFont(label_font)
        self.toggle_monitor_btn.setStyleSheet("background-color: #00aa00; color: white; padding: 8px 16px;")
        self.toggle_monitor_btn.setEnabled(False)
        self.toggle_monitor_btn.clicked.connect(self._toggle_monitoring)
        controls_layout.addWidget(self.toggle_monitor_btn)
        
        self.show_overlay_btn = QPushButton("Show Overlay\nWindow")
        self.show_overlay_btn.setFont(label_font)
        self.show_overlay_btn.setStyleSheet("background-color: #0078d4; color: white; padding: 8px 16px;")
        self.show_overlay_btn.clicked.connect(self._toggle_overlay)
        controls_layout.addWidget(self.show_overlay_btn)
        
        self.copy_btn = QPushButton("Copy Text")
        self.copy_btn.setFont(label_font)
        self.copy_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
        self.copy_btn.clicked.connect(self._copy_text)
        controls_layout.addWidget(self.copy_btn)
        
        top_layout.addWidget(controls_group)
        
        # History Section
        history_group = QGroupBox("OCR History (Last 10)")
        history_group.setFont(title_font)
        history_layout = QVBoxLayout(history_group)
        history_layout.setSpacing(10)
        history_layout.setContentsMargins(15, 20, 15, 10)
        
        self.history_list = QListWidget()
        self.history_list.setFont(label_font)
        self.history_list.setMinimumHeight(100)
        self.history_list.setMaximumHeight(150)
        self.history_list.setAlternatingRowColors(True)
        self.history_list.setStyleSheet("""
            QListWidget { border: 1px solid #ccc; border-radius: 4px; }
            QListWidget::item { padding: 4px; }
            QListWidget::item:hover { background-color: #e0e0e0; }
            QListWidget::item:selected { background-color: #0078d4; color: white; }
        """)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)
        history_layout.addWidget(self.history_list)
        
        clear_history_btn = QPushButton("Clear History")
        clear_history_btn.setFont(label_font)
        clear_history_btn.setStyleSheet("background-color: #666; color: white; padding: 4px 8px;")
        clear_history_btn.clicked.connect(self._clear_history)
        history_layout.addWidget(clear_history_btn)
        
        top_layout.addWidget(history_group)
        top_layout.addStretch()
        
        scroll_area.setWidget(self.scroll_content_widget)
        main_layout.addWidget(scroll_area)
        
        QTimer.singleShot(0, self._set_scroll_content_minimum_size)
    
    def _set_scroll_content_minimum_size(self):
        content_size = self.scroll_content_widget.sizeHint()
        self.scroll_content_widget.setMinimumSize(content_size.width(), content_size.height())

    def _on_sensitivity_changed(self, value):
        if value <= 2:
            label = "Very High"
        elif value <= 5:
            label = "High" if value <= 3 else "Medium"
        elif value <= 10:
            label = "Low"
        else:
            label = "Very Low"
        self.sensitivity_label.setText(f"({label})")
    
    def _on_debug_log_toggled(self, checked):
        if checked:
            self.debug_log_checkbox.setText("Logging ON")
        else:
            self.debug_log_checkbox.setText("Logging OFF")
        self.controller.apply_logging_settings(checked, self.log_level_combo.currentText())
    
    def _on_log_level_changed(self, level):
        self.controller.apply_logging_settings(self.debug_log_checkbox.isChecked(), level)
    
    def _populate_language_dropdown(self):
        language_data = self.controller.get_language_data()
        self.lang_combo.clear()
        for lang in language_data:
            self.lang_combo.addItem(lang['item_text'])
        self._update_language_status()
    
    def _on_language_changed(self, index):
        if index >= 0:
            self.controller.set_language(index)
            self._update_language_status()
    
    def _update_language_status(self):
        index = self.lang_combo.currentIndex()
        message, status = self.controller.get_language_status(index)
        if status == "available":
            self.lang_status_label.setText(message)
            self.lang_status_label.setStyleSheet("color: green; font-size: 8pt;")
        elif status == "missing":
            self.lang_status_label.setText(message)
            self.lang_status_label.setStyleSheet("color: #cc6600; font-size: 8pt;")
        else:
            self.lang_status_label.setText(message)
            self.lang_status_label.setStyleSheet("color: #666; font-size: 8pt;")
    
    def _on_tesseract_status(self, is_found, message):
        self.tesseract_label.setText(message)
        if is_found:
            self.tesseract_label.setStyleSheet("color: green;")
        else:
            self.tesseract_label.setStyleSheet("color: red;")
            QMessageBox.warning(self, "Tesseract Not Found",
                "Tesseract OCR is not installed.\n\n"
                "Please install from:\nhttps://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "Install to: C:\\Program Files\\Tesseract-OCR\nThen restart this application.")
    
    def _on_monitoring_started(self):
        self.monitor_label.setText("Monitoring: Active")
        self.monitor_label.setStyleSheet("color: green;")
        self.toggle_monitor_btn.setText("Stop\nMonitoring")
        self.toggle_monitor_btn.setStyleSheet("background-color: #aa0000; color: white; padding: 8px 16px;")
        self.select_btn.setEnabled(False)
        self.idle_interval_spin.setEnabled(False)
        self.active_interval_spin.setEnabled(False)
        self.sensitivity_spin.setEnabled(False)
        self.stability_spin.setEnabled(False)
        self.max_wait_spin.setEnabled(False)
    
    def _on_monitoring_stopped(self):
        self.monitor_label.setText("Monitoring: Off")
        self.monitor_label.setStyleSheet("")
        self.mode_label.setText("Mode: --")
        self.mode_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.change_status_label.setText("Status: Stopped")
        self.toggle_monitor_btn.setText("Start\nMonitoring")
        self.toggle_monitor_btn.setStyleSheet("background-color: #00aa00; color: white; padding: 8px 16px;")
        self.select_btn.setEnabled(True)
        self.idle_interval_spin.setEnabled(True)
        self.active_interval_spin.setEnabled(True)
        self.sensitivity_spin.setEnabled(True)
        self.stability_spin.setEnabled(True)
        self.max_wait_spin.setEnabled(True)
    
    def _on_polling_state_changed(self, state):
        mode = state['mode']
        if mode == "IDLE":
            self.mode_label.setText("Mode: IDLE (slow)")
            self.mode_label.setStyleSheet("color: #0066cc; font-weight: bold; font-size: 14px;")
        elif mode == "ACTIVE":
            self.mode_label.setText("Mode: ACTIVE (fast)")
            self.mode_label.setStyleSheet("color: #cc6600; font-weight: bold; font-size: 14px;")
        elif mode == "COOLDOWN":
            self.mode_label.setText("Mode: COOLDOWN")
            self.mode_label.setStyleSheet("color: #666666; font-weight: bold; font-size: 14px;")
        self.interval_label.setText(f"Interval: {state['next_interval_ms']}ms")
        self.change_status_label.setText(f"Status: {state['reason']}")
        self.change_score_label.setText(f"Change: {state['change_score']:.1f}")
        self.stable_count_label.setText(f"Stable: {state['stable_count']}/{state['stability_target']}")
        self.efficiency_label.setText(f"Poll: {state['stats']}")
        self.stats_label.setText(f"Captures: {state['capture_count']} | OCRs: {state['ocr_count']}")
    
    def _on_ocr_result(self, text, elapsed):
        self.overlay_window.set_text(text)
        if not self.overlay_window.isVisible():
            self.overlay_window.show()
            self.show_overlay_btn.setText("Hide Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def _on_ocr_error(self, error):
        self.overlay_window.set_text(f"Error: {error}")
        if "Failed loading language" in error:
            QMessageBox.warning(self, "Language Pack Missing",
                "The selected language pack is not installed.\n"
                "Please reinstall Tesseract and select the required language packs.")
    
    def _on_history_updated(self, history_items):
        self.history_list.clear()
        for item in history_items:
            item_text = f"[{item['timestamp']}] {item['preview']}"
            list_item = QListWidgetItem(item_text)
            list_item.setToolTip(item['tooltip'])
            self.history_list.addItem(list_item)
    
    def _on_region_set(self, region):
        self.region_label.setText(f"Region: {region['width']}x{region['height']}")
        self.region_label.setStyleSheet("color: green;")
        self.toggle_monitor_btn.setEnabled(True)

    def _show_region_selector(self):
        if self.controller.is_monitoring:
            self.controller.stop_monitoring()
        self.region_selector.show()
        self.region_selector.activateWindow()
    
    def _on_region_selected(self, rect):
        self.controller.set_region(rect)
        self.showNormal()
        self.activateWindow()
    
    def _on_selection_cancelled(self):
        self.showNormal()
        self.activateWindow()
    
    def _toggle_monitoring(self):
        if self.controller.is_monitoring:
            self.controller.stop_monitoring()
        else:
            settings = {
                'sensitivity': self.sensitivity_spin.value(),
                'stability': self.stability_spin.value(),
                'max_wait': self.max_wait_spin.value(),
                'idle_interval': self.idle_interval_spin.value(),
                'active_interval': self.active_interval_spin.value(),
            }
            self.controller.start_monitoring(settings)
    
    def _toggle_overlay(self):
        if self.overlay_window.isVisible():
            self.overlay_window.hide()
            self.show_overlay_btn.setText("Show Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #0078d4; color: white; padding: 8px 16px;")
        else:
            self.overlay_window.show()
            self.show_overlay_btn.setText("Hide Overlay\nWindow")
            self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def _on_history_item_clicked(self, item):
        index = self.history_list.row(item)
        full_text = self.controller.get_history_item(index)
        if full_text:
            self.overlay_window.set_text(full_text)
            if not self.overlay_window.isVisible():
                self.overlay_window.show()
                self.show_overlay_btn.setText("Hide Overlay\nWindow")
                self.show_overlay_btn.setStyleSheet("background-color: #666; color: white; padding: 8px 16px;")
    
    def _clear_history(self):
        self.controller.clear_history()
    
    def _copy_text(self):
        text = self.overlay_window.get_text()
        if text and text != "(No text detected)" and not text.startswith("OCR results"):
            QApplication.clipboard().setText(text)
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy Text"))
    
    def _save_settings(self):
        main_geom = self.geometry()
        overlay_geom = self.overlay_window.geometry()
        settings = {
            'language_index': self.lang_combo.currentIndex(),
            'idle_interval': self.idle_interval_spin.value(),
            'active_interval': self.active_interval_spin.value(),
            'sensitivity': self.sensitivity_spin.value(),
            'stability': self.stability_spin.value(),
            'max_wait': self.max_wait_spin.value(),
            'window_x': main_geom.x(),
            'window_y': main_geom.y(),
            'window_width': main_geom.width(),
            'window_height': main_geom.height(),
            'overlay_x': overlay_geom.x(),
            'overlay_y': overlay_geom.y(),
            'overlay_width': overlay_geom.width(),
            'overlay_height': overlay_geom.height(),
            'debug_logging_enabled': self.debug_log_checkbox.isChecked(),
            'log_level': self.log_level_combo.currentText(),
        }
        self.controller.save_settings(settings)
    
    def _load_settings(self):
        settings = self.controller.load_settings()
        if not settings:
            return
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
        if all(k in settings for k in ['window_x', 'window_y', 'window_width', 'window_height']):
            self.setGeometry(settings['window_x'], settings['window_y'],
                           settings['window_width'], settings['window_height'])
        if all(k in settings for k in ['overlay_x', 'overlay_y', 'overlay_width', 'overlay_height']):
            self.overlay_window.setGeometry(settings['overlay_x'], settings['overlay_y'],
                                           settings['overlay_width'], settings['overlay_height'])
        if 'debug_logging_enabled' in settings:
            enabled = settings['debug_logging_enabled']
            self.debug_log_checkbox.setChecked(enabled)
            if enabled:
                self.debug_log_checkbox.setText("Logging ON")
            else:
                self.debug_log_checkbox.setText("Logging OFF")
            self.controller.apply_logging_settings(enabled, settings.get('log_level', 'DEBUG'))
        if 'log_level' in settings:
            level = settings['log_level']
            if level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                self.log_level_combo.setCurrentText(level)
    
    def _register_global_hotkey(self):
        hwnd = int(self.winId())
        if register_hotkey(hwnd):
            self.hotkey_registered = True
            print("Global hotkey Ctrl+Shift+X registered")
        else:
            print("Failed to register global hotkey")
    
    def nativeEvent(self, eventType, message):
        if sys.platform == 'win32' and eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._show_region_selector()
                return True, 0
        return super().nativeEvent(eventType, message)
    
    def closeEvent(self, event):
        self.controller.stop_monitoring()
        self._save_settings()
        self.overlay_window.close()
        if self.hotkey_registered:
            unregister_hotkey(int(self.winId()))
        event.accept()
