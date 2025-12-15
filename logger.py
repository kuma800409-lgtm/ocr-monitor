"""
Debug logging module for OCR Monitor application.

Provides configurable logging for OCR events, errors, and future
translation API integration. Logs are written to ocr_debug.log.
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler


# ============================================================================
# Logger Configuration
# ============================================================================

# Log file path (same directory as script)
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, 'ocr_debug.log')

# Log format
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Maximum log file size (5 MB) and backup count
MAX_LOG_SIZE = 5 * 1024 * 1024
BACKUP_COUNT = 3


class OCRLogger:
    """
    Centralized logger for OCR Monitor application.
    
    Provides methods for logging OCR events, errors, and future
    translation API calls with configurable log levels.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """Singleton pattern to ensure single logger instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the logger if not already initialized."""
        if OCRLogger._initialized:
            return
        
        self.logger = logging.getLogger('OCRMonitor')
        self.logger.setLevel(logging.DEBUG)
        
        # File handler with rotation
        self.file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        self.file_handler.setLevel(logging.DEBUG)
        self.file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        
        # Console handler (for development)
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(logging.INFO)
        self.console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(self.console_handler)
        
        # Logging enabled flag (can be toggled from UI)
        self._enabled = True
        self._log_level = logging.DEBUG
        
        OCRLogger._initialized = True
        self.info("OCR Logger initialized")
    
    @property
    def enabled(self):
        """Check if logging is enabled."""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value):
        """Enable or disable logging."""
        self._enabled = value
        if value:
            self.info("Logging enabled")
        else:
            self.logger.info("Logging disabled")
    
    def set_level(self, level):
        """
        Set the logging level.
        
        Args:
            level: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
        """
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
        }
        if level in level_map:
            self._log_level = level_map[level]
            self.file_handler.setLevel(self._log_level)
            self.info(f"Log level set to {level}")
    
    def get_level_name(self):
        """Get the current log level name."""
        level_names = {
            logging.DEBUG: 'DEBUG',
            logging.INFO: 'INFO',
            logging.WARNING: 'WARNING',
            logging.ERROR: 'ERROR',
        }
        return level_names.get(self._log_level, 'DEBUG')
    
    def debug(self, message):
        """Log a debug message."""
        if self._enabled:
            self.logger.debug(message)
    
    def info(self, message):
        """Log an info message."""
        if self._enabled:
            self.logger.info(message)
    
    def warning(self, message):
        """Log a warning message."""
        if self._enabled:
            self.logger.warning(message)
    
    def error(self, message):
        """Log an error message."""
        if self._enabled:
            self.logger.error(message)
    
    def critical(self, message):
        """Log a critical error message."""
        if self._enabled:
            self.logger.critical(message)
    
    # ========================================================================
    # Exception Logging Methods
    # ========================================================================
    
    def log_exception(self, context, exc_info=None):
        """
        Log an exception with full stack trace and context.
        
        Args:
            context: Description of what operation was being performed
            exc_info: Exception info tuple (type, value, traceback) or None to use current exception
        """
        if exc_info is None:
            exc_info = sys.exc_info()
        
        exc_type, exc_value, exc_tb = exc_info
        
        if exc_type is None:
            self.error(f"Exception in {context}: No exception info available")
            return
        
        # Format the exception details
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        exc_type_name = exc_type.__name__ if exc_type else "Unknown"
        exc_message = str(exc_value) if exc_value else "No message"
        
        # Get the full stack trace
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        full_traceback = ''.join(tb_lines)
        
        # Log the exception with all details
        log_message = (
            f"\n{'='*60}\n"
            f"EXCEPTION in {context}\n"
            f"{'='*60}\n"
            f"Timestamp: {timestamp}\n"
            f"Type: {exc_type_name}\n"
            f"Message: {exc_message}\n"
            f"{'='*60}\n"
            f"Stack Trace:\n{full_traceback}"
            f"{'='*60}\n"
        )
        
        # Always log exceptions regardless of enabled state (critical errors)
        self.logger.error(log_message)
    
    def log_critical_error(self, context, error_message, additional_info=None):
        """
        Log a critical error with context information.
        
        Args:
            context: Description of what operation failed
            error_message: The error message
            additional_info: Optional dict with additional context
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        log_message = (
            f"\n{'='*60}\n"
            f"CRITICAL ERROR in {context}\n"
            f"{'='*60}\n"
            f"Timestamp: {timestamp}\n"
            f"Error: {error_message}\n"
        )
        
        if additional_info:
            log_message += f"Additional Info:\n"
            for key, value in additional_info.items():
                log_message += f"  {key}: {value}\n"
        
        log_message += f"{'='*60}\n"
        
        # Always log critical errors regardless of enabled state
        self.logger.critical(log_message)
    
    # ========================================================================
    # OCR-Specific Logging Methods
    # ========================================================================
    
    def log_ocr_start(self, language, region_size=None):
        """Log OCR operation start."""
        region_info = f" | Region: {region_size}" if region_size else ""
        self.debug(f"OCR Start | Language: {language}{region_info}")
    
    def log_ocr_stop(self):
        """Log OCR monitoring stopped."""
        self.info("OCR Monitoring Stopped")
    
    def log_ocr_result(self, text_length, elapsed_ms, language):
        """Log OCR operation result."""
        preview = f"{text_length} chars" if text_length > 0 else "No text"
        self.info(f"OCR Result | {preview} | {elapsed_ms:.0f}ms | Lang: {language}")
    
    def log_ocr_error(self, error_message, language=None):
        """Log OCR error."""
        lang_info = f" | Lang: {language}" if language else ""
        self.error(f"OCR Error | {error_message}{lang_info}")
    
    def log_text_detected(self, text, language):
        """Log detected text (truncated for privacy/size)."""
        preview = text[:100].replace('\n', ' ') if text else "(empty)"
        if len(text) > 100:
            preview += "..."
        self.debug(f"Text Detected | {len(text)} chars | Preview: {preview}")
    
    def log_change_detected(self, change_score, mode):
        """Log change detection event."""
        self.debug(f"Change Detected | Score: {change_score:.1f} | Mode: {mode}")
    
    def log_mode_change(self, old_mode, new_mode):
        """Log polling mode change."""
        self.debug(f"Mode Change | {old_mode} -> {new_mode}")
    
    def log_polling_interval(self, mode, interval_ms):
        """Log polling interval change."""
        self.debug(f"Polling Interval | Mode: {mode} | Interval: {interval_ms}ms")
    
    # ========================================================================
    # Translation API Hooks (Future Integration)
    # ========================================================================
    
    def log_translation_start(self, source_lang, target_lang, text_length):
        """Log translation API call start (future use)."""
        self.debug(f"Translation Start | {source_lang} -> {target_lang} | {text_length} chars")
    
    def log_translation_result(self, source_lang, target_lang, elapsed_ms):
        """Log translation API result (future use)."""
        self.info(f"Translation Result | {source_lang} -> {target_lang} | {elapsed_ms:.0f}ms")
    
    def log_translation_error(self, error_message, source_lang=None, target_lang=None):
        """Log translation API error (future use)."""
        lang_info = f" | {source_lang} -> {target_lang}" if source_lang else ""
        self.error(f"Translation Error | {error_message}{lang_info}")
    
    def log_api_request(self, api_name, endpoint, method='GET'):
        """Log API request (future use)."""
        self.debug(f"API Request | {api_name} | {method} {endpoint}")
    
    def log_api_response(self, api_name, status_code, elapsed_ms):
        """Log API response (future use)."""
        self.debug(f"API Response | {api_name} | Status: {status_code} | {elapsed_ms:.0f}ms")


# Global logger instance
ocr_logger = OCRLogger()


# Convenience functions for direct access
def get_logger():
    """Get the global OCR logger instance."""
    return ocr_logger


def enable_logging():
    """Enable debug logging."""
    ocr_logger.enabled = True


def disable_logging():
    """Disable debug logging."""
    ocr_logger.enabled = False


def set_log_level(level):
    """Set the log level ('DEBUG', 'INFO', 'WARNING', 'ERROR')."""
    ocr_logger.set_level(level)
