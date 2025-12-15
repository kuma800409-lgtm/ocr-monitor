"""
OCR Monitor - Windows Desktop App with Adaptive Change Detection

Features:
- Two-tier adaptive polling: slow when idle, fast when changes detected
- Waits for content to stabilize before running OCR
- Minimal CPU usage when content is not changing
- Smart hysteresis to avoid repeated OCR of same content

Usage:
1. Run the app
2. Press Ctrl+Shift+X to select a screen region
3. Click "Start Monitoring" to begin
4. OCR runs automatically when content stabilizes after changes
"""

import sys
import os
import ctypes
import shutil
import time
import hashlib
from ctypes import wintypes
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QGroupBox,
    QMessageBox, QSlider, QPlainTextEdit, QSizeGrip, QScrollArea,
    QFrame, QGridLayout
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QRect, QPoint
)
from PyQt5.QtGui import (
    QFont, QPainter, QColor, QPen, QGuiApplication
)

import mss
from PIL import Image
import pytesseract


# ============================================================================
# Tesseract Auto-Detection
# ============================================================================

def find_tesseract():
    """Auto-detect Tesseract installation on Windows."""
    common_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        r'C:\Tesseract-OCR\tesseract.exe',
        os.path.expanduser(r'~\AppData\Local\Tesseract-OCR\tesseract.exe'),
        os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'),
    ]
    
    tesseract_in_path = shutil.which('tesseract')
    if tesseract_in_path:
        return tesseract_in_path
    
    for path in common_paths:
        if os.path.isfile(path):
            return path
    
    return None


def configure_tesseract():
    """Configure pytesseract with the correct Tesseract path."""
    if sys.platform == 'win32':
        tesseract_path = find_tesseract()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            return tesseract_path
        return None
    return shutil.which('tesseract')


TESSERACT_PATH = configure_tesseract()


# ============================================================================
# Global Hotkey Registration (Windows API)
# ============================================================================

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_X = 0x58
WM_HOTKEY = 0x0312
HOTKEY_ID = 1

user32 = ctypes.windll.user32


def register_hotkey(hwnd):
    return user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_X)


def unregister_hotkey(hwnd):
    user32.UnregisterHotKey(hwnd, HOTKEY_ID)


# ============================================================================
# Adaptive Change Detector with Two-Tier Polling
# ============================================================================

class AdaptiveChangeDetector:
    """
    Two-tier adaptive change detection:
    
    IDLE MODE (slow polling):
    - Polls every idle_interval_ms (default 1000ms)
    - Minimal CPU usage when nothing is changing
    - Switches to ACTIVE mode when change detected
    
    ACTIVE MODE (fast polling):
    - Polls every active_interval_ms (default 150ms)
    - Tracks stability (consecutive unchanged frames)
    - Triggers OCR when content stabilizes
    - Returns to IDLE mode after OCR + cooldown
    
    This dramatically reduces CPU usage compared to constant fast polling.
    """
    
    # Polling modes
    MODE_IDLE = "idle"
    MODE_ACTIVE = "active"
    MODE_COOLDOWN = "cooldown"
    
    def __init__(
        self,
        threshold=5,
        stability_frames=3,
        max_wait_seconds=5,
        idle_interval_ms=1000,
        active_interval_ms=150,
        cooldown_ms=500
    ):
        """
        Args:
            threshold: Pixel difference threshold (0-255) to consider "changed"
            stability_frames: Consecutive unchanged frames before OCR triggers
            max_wait_seconds: Force OCR after this time even if unstable
            idle_interval_ms: Polling interval in idle mode (slow)
            active_interval_ms: Polling interval in active mode (fast)
            cooldown_ms: Time to wait after OCR before returning to idle
        """
        self.threshold = threshold
        self.stability_frames = stability_frames
        self.max_wait_seconds = max_wait_seconds
        self.idle_interval_ms = idle_interval_ms
        self.active_interval_ms = active_interval_ms
        self.cooldown_ms = cooldown_ms
        
        # State
        self.mode = self.MODE_IDLE
        self.last_thumbnail = None
        self.last_ocr_hash = None
        self.stable_count = 0
        self.first_change_time = None
        self.cooldown_start = None
        
        # Stats
        self.idle_checks = 0
        self.active_checks = 0
    
    def _get_thumbnail(self, image, size=(32, 32)):
        """Convert image to small grayscale thumbnail for fast comparison."""
        return image.convert('L').resize(size, Image.Resampling.LANCZOS)
    
    def _get_hash(self, thumbnail):
        """Get hash of thumbnail for quick equality check."""
        return hashlib.md5(thumbnail.tobytes()).hexdigest()
    
    def _calculate_difference(self, thumb1, thumb2):
        """Calculate average pixel difference between two thumbnails."""
        if thumb1 is None or thumb2 is None:
            return 255
        
        pixels1 = list(thumb1.getdata())
        pixels2 = list(thumb2.getdata())
        
        if len(pixels1) != len(pixels2):
            return 255
        
        total_diff = sum(abs(p1 - p2) for p1, p2 in zip(pixels1, pixels2))
        return total_diff / len(pixels1)
    
    def get_current_interval(self):
        """Get the current polling interval based on mode."""
        if self.mode == self.MODE_IDLE:
            return self.idle_interval_ms
        elif self.mode == self.MODE_COOLDOWN:
            return self.cooldown_ms
        else:
            return self.active_interval_ms
    
    def check_frame(self, image):
        """
        Check a new frame and determine next action.
        
        Returns dict with:
            - should_ocr: bool - True if OCR should run now
            - mode: str - Current mode (idle/active/cooldown)
            - next_interval_ms: int - Suggested interval for next check
            - change_score: float - Difference from last frame
            - stable_count: int - Consecutive stable frames
            - reason: str - Human-readable status
        """
        thumbnail = self._get_thumbnail(image)
        current_hash = self._get_hash(thumbnail)
        change_score = self._calculate_difference(thumbnail, self.last_thumbnail)
        is_changed = change_score >= self.threshold
        
        result = {
            'should_ocr': False,
            'mode': self.mode,
            'next_interval_ms': self.get_current_interval(),
            'change_score': change_score,
            'stable_count': self.stable_count,
            'reason': ''
        }
        
        # Handle cooldown mode
        if self.mode == self.MODE_COOLDOWN:
            if self.cooldown_start and (time.time() - self.cooldown_start) * 1000 >= self.cooldown_ms:
                self.mode = self.MODE_IDLE
                self.cooldown_start = None
                result['reason'] = 'Cooldown complete, returning to idle'
            else:
                result['reason'] = 'In cooldown after OCR'
            result['mode'] = self.mode
            result['next_interval_ms'] = self.get_current_interval()
            self.last_thumbnail = thumbnail
            return result
        
        # IDLE MODE: Check for any change
        if self.mode == self.MODE_IDLE:
            self.idle_checks += 1
            
            if is_changed:
                # Change detected! Switch to active mode
                self.mode = self.MODE_ACTIVE
                self.stable_count = 0
                self.first_change_time = time.time()
                result['reason'] = f'Change detected (diff={change_score:.1f}), switching to active mode'
            else:
                # No change, stay in idle
                # Check hysteresis - if content same as last OCR, stay idle
                if self.last_ocr_hash and current_hash == self.last_ocr_hash:
                    result['reason'] = 'Idle: No change since last OCR'
                else:
                    result['reason'] = 'Idle: Monitoring for changes'
        
        # ACTIVE MODE: Track stability and trigger OCR
        elif self.mode == self.MODE_ACTIVE:
            self.active_checks += 1
            
            if is_changed:
                # Still changing, reset stability counter
                self.stable_count = 0
                result['reason'] = f'Active: Content changing (diff={change_score:.1f})'
            else:
                # No change, increment stability
                self.stable_count += 1
                
                if self.stable_count >= self.stability_frames:
                    # Content has stabilized - trigger OCR!
                    # But only if different from last OCR
                    if self.last_ocr_hash and current_hash == self.last_ocr_hash:
                        result['reason'] = 'Stable but same as last OCR, returning to idle'
                        self.mode = self.MODE_IDLE
                        self.stable_count = 0
                    else:
                        result['should_ocr'] = True
                        result['reason'] = f'Content stable for {self.stable_count} frames - triggering OCR'
                else:
                    result['reason'] = f'Active: Waiting for stability ({self.stable_count}/{self.stability_frames})'
            
            # Check max wait timeout
            if self.first_change_time:
                elapsed = time.time() - self.first_change_time
                if elapsed > self.max_wait_seconds and not result['should_ocr']:
                    if self.last_ocr_hash != current_hash:
                        result['should_ocr'] = True
                        result['reason'] = f'Max wait timeout ({self.max_wait_seconds}s) - forcing OCR'
        
        # Update state
        self.last_thumbnail = thumbnail
        result['mode'] = self.mode
        result['next_interval_ms'] = self.get_current_interval()
        result['stable_count'] = self.stable_count
        
        return result
    
    def mark_ocr_done(self, image):
        """Called after OCR completes. Enters cooldown mode."""
        thumbnail = self._get_thumbnail(image)
        self.last_ocr_hash = self._get_hash(thumbnail)
        self.mode = self.MODE_COOLDOWN
        self.cooldown_start = time.time()
        self.stable_count = 0
        self.first_change_time = None
    
    def reset(self):
        """Reset detector state."""
        self.mode = self.MODE_IDLE
        self.last_thumbnail = None
        self.last_ocr_hash = None
        self.stable_count = 0
        self.first_change_time = None
        self.cooldown_start = None
        self.idle_checks = 0
        self.active_checks = 0
    
    def get_stats(self):
        """Get statistics about polling efficiency."""
        total = self.idle_checks + self.active_checks
        if total == 0:
            return "No checks yet"
        idle_pct = (self.idle_checks / total) * 100
        return f"Idle: {self.idle_checks} ({idle_pct:.0f}%) | Active: {self.active_checks}"


# ============================================================================
# OCR Worker Thread
# ============================================================================

class OCRWorker(QThread):
    """Background thread for OCR processing."""
    result_ready = pyqtSignal(str, float)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, image, lang='eng'):
        super().__init__()
        self.image = image
        self.lang = lang
    
    def run(self):
        try:
            start_time = time.time()
            text = pytesseract.image_to_string(self.image, lang=self.lang)
            elapsed = time.time() - start_time
            self.result_ready.emit(text.strip(), elapsed)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ============================================================================
# Region Selection Overlay
# ============================================================================

class RegionSelector(QWidget):
    """Full-screen transparent overlay for region selection."""
    region_selected = pyqtSignal(QRect)
    selection_cancelled = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        
        self.virtual_geometry = self._get_virtual_geometry()
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(self.virtual_geometry)
        
        self.selection_start = None
        self.selection_rect = QRect()
        self.is_selecting = False
        
        self.setCursor(Qt.CrossCursor)
    
    def _get_virtual_geometry(self):
        screens = QGuiApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        
        min_x = min(s.geometry().x() for s in screens)
        min_y = min(s.geometry().y() for s in screens)
        max_x = max(s.geometry().x() + s.geometry().width() for s in screens)
        max_y = max(s.geometry().y() + s.geometry().height() for s in screens)
        
        return QRect(min_x, min_y, max_x - min_x, max_y - min_y)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        if not self.selection_rect.isNull():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(self.selection_rect, Qt.transparent)
            
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 255, 136), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.selection_rect)
            
            if self.selection_rect.width() > 50 and self.selection_rect.height() > 20:
                size_text = f"{self.selection_rect.width()} x {self.selection_rect.height()}"
                painter.setPen(QColor(255, 255, 255))
                painter.setFont(QFont("Arial", 10))
                painter.drawText(self.selection_rect.x() + 5, self.selection_rect.y() + 15, size_text)
        
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 14))
        painter.drawText(20, 30, "Click and drag to select region. Press ESC to cancel.")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selection_start = event.pos()
            self.selection_rect = QRect()
            self.is_selecting = True
    
    def mouseMoveEvent(self, event):
        if self.is_selecting and self.selection_start:
            self.selection_rect = QRect(self.selection_start, event.pos()).normalized()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            
            if self.selection_rect.width() > 10 and self.selection_rect.height() > 10:
                screen_rect = QRect(
                    self.selection_rect.x() + self.virtual_geometry.x(),
                    self.selection_rect.y() + self.virtual_geometry.y(),
                    self.selection_rect.width(),
                    self.selection_rect.height()
                )
                self.region_selected.emit(screen_rect)
            else:
                self.selection_cancelled.emit()
            
            self.hide()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.selection_cancelled.emit()
            self.hide()


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
        # Frameless window without always-on-top by default
        super().__init__(parent, Qt.Window | Qt.Tool | Qt.FramelessWindowHint)
        self.setMinimumSize(300, 150)
        self.resize(450, 300)
        
        # Enable translucent background for proper transparency
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Track background opacity (0-255 for RGBA)
        self.bg_opacity = 200
        
        # Track pinned state (always-on-top)
        self.is_pinned = False
        
        # For custom window dragging
        self._drag_pos = None
        
        self.init_ui()
    
    def init_ui(self):
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
        self.opacity_slider.setStyleSheet("""
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
        """)
        header.addWidget(self.opacity_slider, 1)
        
        self.opacity_value_label = QLabel(f"{int(self.bg_opacity/255*100)}%")
        self.opacity_value_label.setStyleSheet("color: white; font-size: 9pt;")
        self.opacity_value_label.setMinimumWidth(30)
        header.addWidget(self.opacity_value_label)
        
        header.addStretch()
        
        # Copy button - with proper padding
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setStyleSheet("""
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
        """)
        self.copy_btn.clicked.connect(self.copy_text)
        header.addWidget(self.copy_btn)
        
        # Clear button - with proper padding
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet("""
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
        """)
        self.clear_btn.clicked.connect(self.clear_text)
        header.addWidget(self.clear_btn)
        
        # Close button - with proper padding
        self.close_btn = QPushButton("X")
        self.close_btn.setStyleSheet("""
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
        """)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        
        layout.addLayout(header)
        
        # OCR Result text area
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Consolas", 12))
        self.result_text.setPlaceholderText("OCR results will appear here...\n\nDrag anywhere to move this window.")
        self.result_text.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgba(20, 20, 20, 220);
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
                selection-background-color: #0078d4;
            }
        """)
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
            self.pin_btn.setStyleSheet("""
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
            """)
            self.pin_btn.setText("PINNED")
            self.pin_btn.setToolTip("Window stays on top - click to unpin")
        else:
            self.pin_btn.setStyleSheet("""
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
            """)
            self.pin_btn.setText("PIN")
            self.pin_btn.setToolTip("Pin window to stay on top of other windows")


# ============================================================================
# Main Application Window
# ============================================================================

class OCRMonitorApp(QMainWindow):
    """Main application window with adaptive two-tier polling."""
    
    def __init__(self):
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
        
        # Create the overlay window for OCR results
        self.overlay_window = OCROverlayWindow()
        
        self.init_ui()
        self.check_tesseract()
        
        # Register global hotkey
        self.hotkey_registered = False
        QTimer.singleShot(100, self.register_global_hotkey)
    
    def init_ui(self):
        self.setWindowTitle("OCR Monitor - Adaptive Change Detection")
        # Minimum size to prevent text clipping
        self.setMinimumSize(500, 600)
        self.resize(700, 650)
        
        # Define fonts using QFont - compact sizes for better fit
        title_font = QFont("Segoe UI", 9)
        title_font.setBold(True)
        label_font = QFont("Segoe UI", 9)
        mode_font = QFont("Segoe UI", 11)
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
        
        # Row 1: Language - flexible layout
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        lang_label = QLabel("Language:")
        lang_label.setFont(label_font)
        lang_label.setWordWrap(True)
        row1.addWidget(lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.setFont(label_font)
        self.lang_combo.setMinimumWidth(120)
        self.lang_combo.setSizePolicy(self.lang_combo.sizePolicy().horizontalPolicy(), self.lang_combo.sizePolicy().verticalPolicy())
        self.lang_combo.addItems([
            "eng", "chi_sim", "chi_tra", "jpn", "kor",
            "chi_sim+eng", "jpn+eng", "kor+eng"
        ])
        row1.addWidget(self.lang_combo, 1)
        row1.addStretch(2)
        settings_layout.addLayout(row1)
        
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
        
        # Row 3: Sensitivity - flexible slider
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        sens_label = QLabel("Sensitivity:")
        sens_label.setFont(label_font)
        sens_label.setWordWrap(True)
        row3.addWidget(sens_label)
        self.sensitivity_slider = QSlider(Qt.Horizontal)
        self.sensitivity_slider.setMinimumWidth(100)
        self.sensitivity_slider.setRange(1, 20)
        self.sensitivity_slider.setValue(5)
        self.sensitivity_slider.setTickPosition(QSlider.TicksBelow)
        self.sensitivity_slider.valueChanged.connect(self.on_sensitivity_changed)
        row3.addWidget(self.sensitivity_slider, 1)
        self.sensitivity_label = QLabel("5 (Medium)")
        self.sensitivity_label.setFont(label_font)
        self.sensitivity_label.setMinimumWidth(80)
        self.sensitivity_label.setWordWrap(True)
        row3.addWidget(self.sensitivity_label)
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
        
        self.start_btn = QPushButton("Start\nMonitoring")
        self.start_btn.setFont(label_font)
        self.start_btn.setStyleSheet("background-color: #00aa00; color: white; padding: 8px 16px;")
        self.start_btn.setMinimumHeight(self.start_btn.sizeHint().height())
        self.start_btn.clicked.connect(self.start_monitoring)
        self.start_btn.setEnabled(False)
        controls_layout.addWidget(self.start_btn, 1)
        
        self.stop_btn = QPushButton("Stop\nMonitoring")
        self.stop_btn.setFont(label_font)
        self.stop_btn.setStyleSheet("background-color: #aa0000; color: white; padding: 8px 16px;")
        self.stop_btn.setMinimumHeight(self.stop_btn.sizeHint().height())
        self.stop_btn.clicked.connect(self.stop_monitoring)
        self.stop_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_btn, 1)
        
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
        
        # Instructions at bottom of scrollable content
        instructions = QLabel(
            "Adaptive Two-Tier Polling: IDLE (slow) when nothing changes | ACTIVE (fast) when changes detected | OCR when stable"
        )
        instructions.setFont(QFont("Segoe UI", 9))
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
        labels = {1: "Very High", 5: "Medium", 10: "Low", 20: "Very Low"}
        label = labels.get(value, f"{value}")
        self.sensitivity_label.setText(f"{value} ({label})")
    
    def check_tesseract(self):
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
        hwnd = int(self.winId())
        if register_hotkey(hwnd):
            self.hotkey_registered = True
            print("Global hotkey Ctrl+Shift+X registered")
        else:
            print("Failed to register global hotkey")
    
    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.show_region_selector()
                return True, 0
        return super().nativeEvent(eventType, message)
    
    def show_region_selector(self):
        if self.is_monitoring:
            self.stop_monitoring()
        self.region_selector.show()
        self.region_selector.activateWindow()
    
    def on_region_selected(self, rect):
        self.selected_region = {
            'left': rect.x(),
            'top': rect.y(),
            'width': rect.width(),
            'height': rect.height()
        }
        self.region_label.setText(f"Region: {rect.width()}x{rect.height()}")
        self.region_label.setStyleSheet("color: green;")
        
        self.start_btn.setEnabled(True)
        self.change_detector.reset()
        
        self.showNormal()
        self.activateWindow()
    
    def on_selection_cancelled(self):
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
        
        self.ocr_worker = OCRWorker(image, self.lang_combo.currentText())
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
        """Handle OCR result - send to overlay window."""
        result_text = text if text else "(No text detected)"
        self.overlay_window.set_text(result_text)
        
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
    
    def start_monitoring(self):
        if not self.selected_region:
            return
        
        # Update change detector settings
        self.change_detector.threshold = self.sensitivity_slider.value()
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
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.select_btn.setEnabled(False)
        
        # Disable settings while monitoring
        self.idle_interval_spin.setEnabled(False)
        self.active_interval_spin.setEnabled(False)
        self.sensitivity_slider.setEnabled(False)
        self.stability_spin.setEnabled(False)
        self.max_wait_spin.setEnabled(False)
    
    def stop_monitoring(self):
        self.is_monitoring = False
        self.capture_timer.stop()
        
        self.monitor_label.setText("Monitoring: Off")
        self.monitor_label.setStyleSheet("")
        self.mode_label.setText("Mode: --")
        self.mode_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.change_status_label.setText("Status: Stopped")
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.select_btn.setEnabled(True)
        
        # Re-enable settings
        self.idle_interval_spin.setEnabled(True)
        self.active_interval_spin.setEnabled(True)
        self.sensitivity_slider.setEnabled(True)
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
        self.stop_monitoring()
        
        # Close overlay window
        self.overlay_window.close()
        
        if self.hotkey_registered:
            unregister_hotkey(int(self.winId()))
        
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.quit()
            self.ocr_worker.wait()
        
        event.accept()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    # Enable DPI awareness on Windows
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except:
                pass
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    if not TESSERACT_PATH:
        print("\n" + "="*60)
        print("WARNING: Tesseract OCR not found!")
        print("="*60)
        print("\nPlease install Tesseract:")
        print("1. Download from: https://github.com/UB-Mannheim/tesseract/wiki")
        print("2. Install to: C:\\Program Files\\Tesseract-OCR")
        print("3. Select language packs during installation")
        print("4. Restart this application")
        print("="*60 + "\n")
    else:
        print(f"Tesseract found: {TESSERACT_PATH}")
    
    window = OCRMonitorApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
