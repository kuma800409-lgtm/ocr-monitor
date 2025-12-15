"""
Main entry point for OCR Monitor application.

Initializes the application, sets up DPI awareness on Windows,
and launches the main window.
"""

import sys
import ctypes

from PyQt5.QtWidgets import QApplication

from ocr_engine import TESSERACT_PATH
from ui import OCRMonitorApp


def main():
    """
    Main entry point for the OCR Monitor application.
    
    Sets up DPI awareness on Windows for proper high-DPI display support,
    initializes the Qt application with Fusion style, and launches
    the main window.
    """
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
