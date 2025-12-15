"""
Utility module for OCR Monitor application.

Contains helper functions and classes including:
- Global hotkey registration (Windows API)
- Region selection overlay for screen capture
"""

import sys
import ctypes

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QGuiApplication

from config import (
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_NOREPEAT,
    VK_X,
    HOTKEY_ID,
)


# ============================================================================
# Global Hotkey Registration (Windows API)
# ============================================================================

# Windows-specific imports and setup
if sys.platform == 'win32':
    from ctypes import wintypes
    user32 = ctypes.windll.user32
else:
    user32 = None


def register_hotkey(hwnd):
    """
    Register a global hotkey (Ctrl+Shift+X) with Windows.
    
    Args:
        hwnd: Window handle to receive hotkey messages.
    
    Returns:
        bool: True if registration succeeded, False otherwise.
    """
    if user32 is None:
        return False
    return user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_X)


def unregister_hotkey(hwnd):
    """
    Unregister the global hotkey.
    
    Args:
        hwnd: Window handle that registered the hotkey.
    """
    if user32 is None:
        return
    user32.UnregisterHotKey(hwnd, HOTKEY_ID)


# ============================================================================
# Region Selection Overlay
# ============================================================================

class RegionSelector(QWidget):
    """
    Full-screen transparent overlay for region selection.
    
    Allows users to click and drag to select a rectangular region
    of the screen for OCR monitoring. Supports multi-monitor setups.
    
    Signals:
        region_selected(QRect): Emitted when a valid region is selected
        selection_cancelled(): Emitted when selection is cancelled (ESC key)
    """
    region_selected = pyqtSignal(QRect)
    selection_cancelled = pyqtSignal()
    
    def __init__(self):
        """Initialize the region selector overlay."""
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
        """
        Get the combined geometry of all screens.
        
        Returns:
            QRect: Rectangle covering all connected displays.
        """
        screens = QGuiApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        
        min_x = min(s.geometry().x() for s in screens)
        min_y = min(s.geometry().y() for s in screens)
        max_x = max(s.geometry().x() + s.geometry().width() for s in screens)
        max_y = max(s.geometry().y() + s.geometry().height() for s in screens)
        
        return QRect(min_x, min_y, max_x - min_x, max_y - min_y)
    
    def paintEvent(self, event):
        """Paint the overlay with selection rectangle."""
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
        """Handle mouse press to start selection."""
        if event.button() == Qt.LeftButton:
            self.selection_start = event.pos()
            self.selection_rect = QRect()
            self.is_selecting = True
    
    def mouseMoveEvent(self, event):
        """Handle mouse move to update selection rectangle."""
        if self.is_selecting and self.selection_start:
            self.selection_rect = QRect(self.selection_start, event.pos()).normalized()
            self.update()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release to complete selection."""
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
        """Handle ESC key to cancel selection."""
        if event.key() == Qt.Key_Escape:
            self.selection_cancelled.emit()
            self.hide()
