"""
OCR Engine module for OCR Monitor application.

Contains all OCR processing logic including:
- Tesseract auto-detection and configuration
- Adaptive change detection with two-tier polling
- OCR worker thread for background processing
"""

import sys
import os
import shutil
import time
import hashlib

from PyQt5.QtCore import QThread, pyqtSignal
from PIL import Image
import pytesseract

from config import (
    DEFAULT_THRESHOLD,
    DEFAULT_STABILITY_FRAMES,
    DEFAULT_MAX_WAIT_SECONDS,
    DEFAULT_IDLE_INTERVAL_MS,
    DEFAULT_ACTIVE_INTERVAL_MS,
    DEFAULT_COOLDOWN_MS,
)
from logger import get_logger


# ============================================================================
# Tesseract Auto-Detection
# ============================================================================

def find_tesseract():
    """
    Auto-detect Tesseract installation on Windows.
    
    Searches common installation paths and the system PATH
    to locate the Tesseract executable.
    
    Returns:
        str or None: Path to tesseract.exe if found, None otherwise.
    """
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
    """
    Configure pytesseract with the correct Tesseract path.
    
    Returns:
        str or None: Path to Tesseract if found and configured, None otherwise.
    """
    if sys.platform == 'win32':
        tesseract_path = find_tesseract()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            return tesseract_path
        return None
    return shutil.which('tesseract')


# Initialize Tesseract path on module load
TESSERACT_PATH = configure_tesseract()


# ============================================================================
# Language Detection
# ============================================================================

# Language display names mapping
LANGUAGE_NAMES = {
    'eng': 'English',
    'chi_sim': 'Chinese (Simplified)',
    'chi_tra': 'Chinese (Traditional)',
    'jpn': 'Japanese',
    'kor': 'Korean',
    'fra': 'French',
    'deu': 'German',
    'spa': 'Spanish',
    'ita': 'Italian',
    'por': 'Portuguese',
    'rus': 'Russian',
    'ara': 'Arabic',
    'hin': 'Hindi',
    'tha': 'Thai',
    'vie': 'Vietnamese',
}

# Default languages to show in dropdown
DEFAULT_LANGUAGES = [
    'eng', 'chi_sim', 'chi_tra', 'jpn', 'kor',
    'chi_sim+eng', 'jpn+eng', 'kor+eng'
]


def get_installed_languages():
    """
    Get list of installed Tesseract language packs.
    
    Uses pytesseract.get_languages() to detect which language
    packs are available on the system.
    
    Returns:
        list: List of installed language codes, or empty list if Tesseract not found.
    """
    if not TESSERACT_PATH:
        return []
    
    try:
        languages = pytesseract.get_languages()
        # Filter out 'osd' (orientation and script detection) which is not a language
        return [lang for lang in languages if lang != 'osd']
    except Exception as e:
        print(f"Error getting installed languages: {e}")
        return []


def get_language_display_name(lang_code):
    """
    Get human-readable display name for a language code.
    
    Args:
        lang_code: Tesseract language code (e.g., 'eng', 'jpn')
    
    Returns:
        str: Display name (e.g., 'English', 'Japanese')
    """
    # Handle combined languages like 'chi_sim+eng'
    if '+' in lang_code:
        parts = lang_code.split('+')
        names = [LANGUAGE_NAMES.get(p, p) for p in parts]
        return ' + '.join(names)
    
    return LANGUAGE_NAMES.get(lang_code, lang_code)


def check_language_availability(lang_code, installed_languages):
    """
    Check if a language (or combined languages) is available.
    
    Args:
        lang_code: Language code to check (e.g., 'eng', 'jpn+eng')
        installed_languages: List of installed language codes
    
    Returns:
        tuple: (is_available: bool, missing_langs: list)
    """
    if '+' in lang_code:
        parts = lang_code.split('+')
        missing = [p for p in parts if p not in installed_languages]
        return (len(missing) == 0, missing)
    else:
        is_available = lang_code in installed_languages
        return (is_available, [] if is_available else [lang_code])


def get_tesseract_data_path():
    """
    Get the Tesseract tessdata directory path.
    
    Returns:
        str or None: Path to tessdata directory, or None if not found.
    """
    if not TESSERACT_PATH:
        return None
    
    # Common tessdata locations
    if sys.platform == 'win32':
        tesseract_dir = os.path.dirname(TESSERACT_PATH)
        tessdata_path = os.path.join(tesseract_dir, 'tessdata')
        if os.path.isdir(tessdata_path):
            return tessdata_path
    else:
        # Linux/Mac common paths
        common_paths = [
            '/usr/share/tesseract-ocr/4.00/tessdata',
            '/usr/share/tesseract-ocr/tessdata',
            '/usr/local/share/tessdata',
            '/opt/homebrew/share/tessdata',
        ]
        for path in common_paths:
            if os.path.isdir(path):
                return path
    
    return None


# ============================================================================
# Adaptive Change Detector with Two-Tier Polling
# ============================================================================

class AdaptiveChangeDetector:
    """
    Two-tier adaptive change detection for efficient screen monitoring.
    
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
        threshold=DEFAULT_THRESHOLD,
        stability_frames=DEFAULT_STABILITY_FRAMES,
        max_wait_seconds=DEFAULT_MAX_WAIT_SECONDS,
        idle_interval_ms=DEFAULT_IDLE_INTERVAL_MS,
        active_interval_ms=DEFAULT_ACTIVE_INTERVAL_MS,
        cooldown_ms=DEFAULT_COOLDOWN_MS
    ):
        """
        Initialize the adaptive change detector.
        
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
        
        Args:
            image: PIL Image to check for changes.
        
        Returns:
            dict with:
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
                old_mode = self.mode
                self.mode = self.MODE_ACTIVE
                self.stable_count = 0
                self.first_change_time = time.time()
                result['reason'] = f'Change detected (diff={change_score:.1f}), switching to active mode'
                # Log mode change and change detection
                logger = get_logger()
                logger.log_mode_change(old_mode, self.mode)
                logger.log_change_detected(change_score, self.mode)
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
    """
    Background thread for OCR processing.
    
    Runs Tesseract OCR on an image in a separate thread to avoid
    blocking the UI. Emits signals when complete or on error.
    
    Signals:
        result_ready(str, float): Emitted with OCR text and elapsed time
        error_occurred(str): Emitted with error message on failure
    """
    result_ready = pyqtSignal(str, float)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, image, lang='eng'):
        """
        Initialize the OCR worker.
        
        Args:
            image: PIL Image to process
            lang: Tesseract language code (default 'eng')
        """
        super().__init__()
        self.image = image
        self.lang = lang
        self.logger = get_logger()
    
    def run(self):
        """Execute OCR processing in background thread."""
        try:
            # Log OCR start
            region_size = f"{self.image.width}x{self.image.height}" if self.image else None
            self.logger.log_ocr_start(self.lang, region_size)
            
            start_time = time.time()
            text = pytesseract.image_to_string(self.image, lang=self.lang)
            elapsed = time.time() - start_time
            elapsed_ms = elapsed * 1000
            
            # Log OCR result
            text_stripped = text.strip()
            self.logger.log_ocr_result(len(text_stripped), elapsed_ms, self.lang)
            if text_stripped:
                self.logger.log_text_detected(text_stripped, self.lang)
            
            self.result_ready.emit(text_stripped, elapsed)
        except Exception as e:
            self.logger.log_ocr_error(str(e), self.lang)
            self.error_occurred.emit(str(e))
