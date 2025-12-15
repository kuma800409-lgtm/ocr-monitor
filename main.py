"""
Main entry point for OCR Monitor application.

Initializes the application, sets up DPI awareness on Windows,
and launches the main window.
"""

import sys
import ctypes

from PyQt5.QtWidgets import QApplication, QMessageBox

from ocr_engine import TESSERACT_PATH
from ui import OCRMonitorApp
from logger import get_logger


def setup_global_exception_handler():
    """
    Set up a global exception handler to catch unhandled exceptions.
    
    Logs the full error to the debug log file and shows a user-friendly
    error message before the application crashes.
    """
    logger = get_logger()
    
    def handle_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions."""
        # Don't catch keyboard interrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # Log the exception with full details
        logger.log_exception(
            "Unhandled Exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # Show user-friendly error message
        error_message = (
            f"An unexpected error occurred:\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"The error has been logged to ocr_debug.log.\n"
            f"Please check the log file for details."
        )
        
        # Try to show a message box if Qt is available
        try:
            app = QApplication.instance()
            if app:
                QMessageBox.critical(
                    None,
                    "OCR Monitor - Error",
                    error_message
                )
        except Exception:
            # If Qt message box fails, print to console
            print(f"\n{'='*60}")
            print("CRITICAL ERROR")
            print('='*60)
            print(error_message)
            print('='*60)
        
        # Call the default exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    # Set the global exception handler
    sys.excepthook = handle_exception


def main():
    """
    Main entry point for the OCR Monitor application.
    
    Sets up DPI awareness on Windows for proper high-DPI display support,
    initializes the Qt application with Fusion style, and launches
    the main window.
    """
    # Set up global exception handler first
    setup_global_exception_handler()
    
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
