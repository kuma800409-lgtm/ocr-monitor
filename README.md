# OCR Monitor - Adaptive Change Detection

A Windows desktop app that monitors a screen region and runs OCR only when content stabilizes. Uses adaptive two-tier polling to minimize CPU usage.

## Key Feature: Adaptive Two-Tier Polling

This app uses an intelligent polling system that dramatically reduces CPU usage:

**IDLE Mode (slow polling):**
- Checks for changes every 1000ms (configurable)
- Minimal CPU usage when nothing is changing
- Switches to ACTIVE mode when change detected

**ACTIVE Mode (fast polling):**
- Checks every 150ms (configurable) to track changes
- Waits for content to stabilize (consecutive unchanged frames)
- Triggers OCR when content stops changing
- Returns to IDLE mode after OCR

**Result:** Instead of constantly polling at high frequency, the app only uses fast polling when something is actually changing. This is perfect for game text that changes occasionally.

## How It Works

```
[IDLE: 1000ms polling]
        |
        v
  Change detected?
        |
   YES  |  NO
        v   |
[ACTIVE: 150ms polling]
        |
        v
  Content stable?
        |
   YES  |  NO (keep checking)
        v
   [Run OCR]
        |
        v
  [COOLDOWN]
        |
        v
[Return to IDLE]
```

## Prerequisites

### 1. Python 3.8+
Download from: https://www.python.org/downloads/

### 2. Tesseract OCR (Required)

**Windows Installation:**

1. Download from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer
3. **Important:** Select additional language packs:
   - Chinese (Simplified): `chi_sim`
   - Chinese (Traditional): `chi_tra`
   - Japanese: `jpn`
   - Korean: `kor`
4. Install to: `C:\Program Files\Tesseract-OCR`

## Quick Start

1. **Extract** the zip file to a folder

2. **Run setup** (first time only):
   ```
   Double-click: setup.bat
   ```

3. **Start the app**:
   ```
   Double-click: run.bat
   ```

4. **Select a region**:
   - Press **Ctrl+Shift+X** (or click "Select Region")
   - Drag to select the area with text you want to monitor

5. **Start monitoring**:
   - Click "Start Monitoring"
   - Watch the mode indicator switch between IDLE and ACTIVE
   - OCR runs automatically when content stabilizes

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Idle Interval | 1000ms | Polling interval when nothing is changing |
| Active Interval | 150ms | Polling interval when tracking changes |
| Sensitivity | 5 | Pixel difference threshold (1-20). Lower = more sensitive |
| Stability Frames | 3 | Consecutive unchanged frames needed before OCR |
| Max Wait | 5s | Force OCR after this time even if content keeps changing |

### Recommended Settings by Use Case

**Game dialogue boxes:**
- Idle: 1000ms, Active: 150ms
- Sensitivity: 5, Stability: 3

**Fast-changing text (scrolling):**
- Idle: 1000ms, Active: 100ms
- Sensitivity: 3, Stability: 5, Max Wait: 10s

**Subtitles:**
- Idle: 500ms, Active: 100ms
- Sensitivity: 5, Stability: 2, Max Wait: 3s

## CPU Usage

The adaptive polling dramatically reduces CPU usage compared to constant fast polling:

| Scenario | Constant 150ms | Adaptive |
|----------|----------------|----------|
| Content idle | ~6.7 checks/sec | ~1 check/sec |
| Content changing | ~6.7 checks/sec | ~6.7 checks/sec |
| Average (mostly idle) | ~6.7 checks/sec | ~1-2 checks/sec |

When content is idle (most of the time), CPU usage is minimal.

## Troubleshooting

### "Tesseract not found" Error

1. Install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki
2. Install to: `C:\Program Files\Tesseract-OCR`
3. Restart the app

If installed elsewhere, edit `ocr_monitor.py` and add after imports:
```python
pytesseract.pytesseract.tesseract_cmd = r'C:\Your\Path\tesseract.exe'
```

### "Language pack not installed" Error

1. Re-run the Tesseract installer
2. Select the required language packs
3. Restart the app

### Hotkey not working

- Make sure no other app is using Ctrl+Shift+X
- Try clicking the "Select Region" button instead
- Run as Administrator if needed

### OCR never triggers

- Lower the Sensitivity value (try 3 instead of 5)
- Reduce Stability Frames (try 2 instead of 3)
- Check if Max Wait timeout is triggering

### Mode stays in ACTIVE forever

- Content might have subtle animations (cursor blink, etc.)
- Increase Sensitivity value (try 10 instead of 5)
- The Max Wait timeout will eventually force OCR

## Files

- `ocr_monitor.py` - Main application with adaptive change detection
- `setup.bat` - Creates venv and installs dependencies
- `run.bat` - Starts the app
- `requirements.txt` - Python dependencies

## Language Codes

| Language | Code |
|----------|------|
| English | `eng` |
| Chinese (Simplified) | `chi_sim` |
| Chinese (Traditional) | `chi_tra` |
| Japanese | `jpn` |
| Korean | `kor` |
| Chinese + English | `chi_sim+eng` |
| Japanese + English | `jpn+eng` |
| Korean + English | `kor+eng` |
