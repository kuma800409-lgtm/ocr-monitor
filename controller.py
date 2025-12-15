"""
Controller module for OCR Monitor application.

Handles all business logic including:
- Monitoring control (start/stop)
- Change detection and adaptive polling
- OCR execution management
- Image capture logic
- History management
- Settings persistence

The controller emits signals for UI updates, keeping UI and logic separated.
"""

import os
import json
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

import mss
from PIL import Image

from ocr_engine import (
    TESSERACT_PATH,
    AdaptiveChangeDetector,
    OCRWorker,
    get_installed_languages,
    get_language_display_name,
    check_language_availability,
    DEFAULT_LANGUAGES,
)
from logger import get_logger, enable_logging, disable_logging, set_log_level


class OCRMonitorController(QObject):
    """
    Controller for OCR monitoring business logic.
    
    Emits signals for UI updates rather than directly manipulating widgets.
    This keeps the UI layer thin and focused on presentation.
    """
    
    # Monitoring state signals
    monitoring_started = pyqtSignal()
    monitoring_stopped = pyqtSignal()
    
    # Polling state signals
    polling_state_changed = pyqtSignal(dict)  # mode, interval, status, change_score, stable_count, stats
    
    # OCR result signals
    ocr_result_ready = pyqtSignal(str, float)  # text, elapsed_time
    ocr_error = pyqtSignal(str)  # error message
    
    # History signals
    history_updated = pyqtSignal(list)  # list of (timestamp, preview, full_text) tuples
    
    # Region selection signals
    region_selected = pyqtSignal(dict)  # region dict with left, top, width, height
    
    # Settings signals
    settings_loaded = pyqtSignal(dict)  # settings dictionary
    
    # Tesseract status signal
    tesseract_status = pyqtSignal(bool, str)  # is_found, message
    
    def __init__(self, parent=None):
        """Initialize the controller."""
        super().__init__(parent)
        
        # State
        self.selected_region = None
        self.is_monitoring = False
        self.ocr_worker = None
        
        # Adaptive timer - interval changes based on mode
        self.capture_timer = QTimer(self)
        self.capture_timer.timeout.connect(self._on_timer_tick)
        
        # Adaptive change detector
        self.change_detector = AdaptiveChangeDetector(
            threshold=5,
            stability_frames=3,
            max_wait_seconds=5,
            idle_interval_ms=1000,
            active_interval_ms=150,
            cooldown_ms=500
        )
        
        # Screen capture
        self.mss_instance = mss.mss()
        self.last_captured_image = None
        
        # Stats
        self.ocr_count = 0
        self.capture_count = 0
        
        # OCR History (stores last 10 results)
        self.ocr_history = []  # List of (timestamp, full_text) tuples
        self.max_history_items = 10
        
        # Current language setting
        self.current_language = 'eng'
        
        # Language data
        self.installed_languages = []
        self.language_codes = []
        
        # Logger
        self.logger = get_logger()
    
    def check_tesseract(self):
        """Check if Tesseract is installed and emit status."""
        if TESSERACT_PATH:
            self.tesseract_status.emit(True, "Tesseract: Found")
        else:
            self.tesseract_status.emit(False, "Tesseract: NOT FOUND")
    
    def get_language_data(self):
        """
        Get language dropdown data with availability status.
        
        Returns list of dicts with:
        - code: language code (e.g., 'eng')
        - display_name: human readable name (e.g., 'English')
        - is_available: bool
        - item_text: formatted text for dropdown
        """
        self.installed_languages = get_installed_languages()
        self.language_codes = []
        
        language_data = []
        for lang_code in DEFAULT_LANGUAGES:
            display_name = get_language_display_name(lang_code)
            is_available, missing = check_language_availability(lang_code, self.installed_languages)
            
            if is_available:
                item_text = f"{display_name} ({lang_code})"
            else:
                item_text = f"{display_name} ({lang_code}) [Not Installed]"
            
            language_data.append({
                'code': lang_code,
                'display_name': display_name,
                'is_available': is_available,
                'missing': missing,
                'item_text': item_text
            })
            self.language_codes.append(lang_code)
        
        return language_data
    
    def get_language_status(self, index):
        """Get status message for selected language."""
        if index < 0 or index >= len(self.language_codes):
            return "", "normal"
        
        lang_code = self.language_codes[index]
        is_available, missing = check_language_availability(lang_code, self.installed_languages)
        
        if is_available:
            return "Language pack installed and ready to use.", "available"
        else:
            missing_str = ', '.join(missing)
            return (
                f"Missing language pack(s): {missing_str}\n"
                f"Install via Tesseract installer or download .traineddata files to tessdata folder.",
                "missing"
            )
    
    def set_language(self, index):
        """Set the current language by index."""
        if 0 <= index < len(self.language_codes):
            self.current_language = self.language_codes[index]
    
    def set_region(self, rect):
        """Set the selected region for monitoring."""
        self.selected_region = {
            'left': rect.x(),
            'top': rect.y(),
            'width': rect.width(),
            'height': rect.height()
        }
        self.change_detector.reset()
        self.region_selected.emit(self.selected_region)
    
    def has_region(self):
        """Check if a region is selected."""
        return self.selected_region is not None
    
    def start_monitoring(self, settings):
        """
        Start monitoring the selected region.
        
        Args:
            settings: dict with idle_interval, active_interval, sensitivity,
                     stability, max_wait values
        """
        if not self.selected_region:
            return False
        
        # Update change detector settings
        self.change_detector.threshold = settings.get('sensitivity', 5)
        self.change_detector.stability_frames = settings.get('stability', 3)
        self.change_detector.max_wait_seconds = settings.get('max_wait', 5)
        self.change_detector.idle_interval_ms = settings.get('idle_interval', 1000)
        self.change_detector.active_interval_ms = settings.get('active_interval', 150)
        self.change_detector.reset()
        
        self.is_monitoring = True
        self.capture_count = 0
        self.ocr_count = 0
        
        # Start in idle mode
        initial_interval = self.change_detector.idle_interval_ms
        self.capture_timer.start(initial_interval)
        
        self.logger.log_mode_change("IDLE", initial_interval)
        self.monitoring_started.emit()
        return True
    
    def stop_monitoring(self):
        """Stop monitoring."""
        self.is_monitoring = False
        self.capture_timer.stop()
        self.logger.log_ocr_stop()
        self.monitoring_stopped.emit()
    
    def _capture_region(self):
        """Capture the selected screen region."""
        if not self.selected_region:
            return None
        
        try:
            screenshot = self.mss_instance.grab(self.selected_region)
            img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
            return img
        except Exception as e:
            self.logger.log_ocr_error(str(e))
            return None
    
    def _on_timer_tick(self):
        """Called by timer - adaptive polling logic."""
        if not self.is_monitoring or not self.selected_region:
            return
        
        # Skip if OCR is already running
        if self.ocr_worker and self.ocr_worker.isRunning():
            return
        
        # Capture current frame
        image = self._capture_region()
        if image is None:
            return
        
        self.capture_count += 1
        self.last_captured_image = image
        
        # Check for changes with adaptive detector
        result = self.change_detector.check_frame(image)
        
        # Emit polling state for UI update
        polling_state = {
            'mode': result['mode'].upper(),
            'next_interval_ms': result['next_interval_ms'],
            'reason': result['reason'],
            'change_score': result['change_score'],
            'stable_count': result['stable_count'],
            'stability_target': self.change_detector.stability_frames,
            'stats': self.change_detector.get_stats(),
            'capture_count': self.capture_count,
            'ocr_count': self.ocr_count
        }
        self.polling_state_changed.emit(polling_state)
        
        # Adjust timer interval if needed
        current_interval = self.capture_timer.interval()
        if current_interval != result['next_interval_ms']:
            self.capture_timer.setInterval(result['next_interval_ms'])
            self.logger.log_mode_change(result['mode'].upper(), result['next_interval_ms'])
        
        # Run OCR if needed
        if result['should_ocr']:
            self._run_ocr(image)
    
    def _run_ocr(self, image):
        """Run OCR on the given image."""
        if not TESSERACT_PATH:
            return
        
        self.ocr_count += 1
        self.logger.log_ocr_start(self.current_language)
        
        self.ocr_worker = OCRWorker(image, self.current_language)
        self.ocr_worker.result_ready.connect(self._on_ocr_result)
        self.ocr_worker.error_occurred.connect(self._on_ocr_error)
        self.ocr_worker.finished.connect(lambda: self.change_detector.mark_ocr_done(image))
        self.ocr_worker.start()
    
    def _on_ocr_result(self, text, elapsed):
        """Handle OCR result."""
        result_text = text if text else "(No text detected)"
        
        if text:
            self.logger.log_ocr_result(text, elapsed)
            self._add_to_history(text)
        
        self.ocr_result_ready.emit(result_text, elapsed)
    
    def _on_ocr_error(self, error):
        """Handle OCR error."""
        self.logger.log_ocr_error(error)
        self.ocr_error.emit(error)
    
    def _add_to_history(self, text):
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
        
        # Emit history update
        self._emit_history_update()
    
    def _emit_history_update(self):
        """Emit history update signal with formatted data."""
        history_items = []
        for timestamp, text in self.ocr_history:
            # Create preview (first 50 chars, single line)
            preview = text.replace('\n', ' ').strip()
            if len(preview) > 50:
                preview = preview[:47] + "..."
            
            history_items.append({
                'timestamp': timestamp,
                'preview': preview,
                'full_text': text,
                'tooltip': text[:200] + "..." if len(text) > 200 else text
            })
        
        self.history_updated.emit(history_items)
    
    def get_history_item(self, index):
        """Get full text for a history item by index."""
        if 0 <= index < len(self.ocr_history):
            return self.ocr_history[index][1]
        return None
    
    def clear_history(self):
        """Clear all OCR history."""
        self.ocr_history.clear()
        self.history_updated.emit([])
    
    # ===== Settings Persistence =====
    
    def get_settings_path(self):
        """Get the path to the settings file."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'ocr_settings.json')
    
    def save_settings(self, ui_settings):
        """
        Save settings to JSON file.
        
        Args:
            ui_settings: dict containing UI-specific settings like:
                - language_index, idle_interval, active_interval, sensitivity,
                  stability, max_wait
                - window_x, window_y, window_width, window_height
                - overlay_x, overlay_y, overlay_width, overlay_height
                - debug_logging_enabled, log_level
        """
        try:
            with open(self.get_settings_path(), 'w') as f:
                json.dump(ui_settings, f, indent=2)
            print(f"Settings saved to {self.get_settings_path()}")
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False
    
    def load_settings(self):
        """
        Load settings from JSON file.
        
        Returns dict of settings or None if file doesn't exist.
        Emits settings_loaded signal with the loaded settings.
        """
        settings_path = self.get_settings_path()
        
        if not os.path.exists(settings_path):
            print("No saved settings found, using defaults")
            return None
        
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
            
            print(f"Settings loaded from {settings_path}")
            self.settings_loaded.emit(settings)
            return settings
        except Exception as e:
            print(f"Error loading settings: {e}")
            return None
    
    def apply_logging_settings(self, enabled, level):
        """Apply debug logging settings."""
        if enabled:
            enable_logging()
        else:
            disable_logging()
        
        if level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
            set_log_level(level)
