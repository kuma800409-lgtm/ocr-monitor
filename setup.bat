@echo off
echo ============================================
echo   OCR Monitor - Setup
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
if exist venv (
    echo Virtual environment already exists, skipping creation.
) else (
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

echo [2/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/3] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo IMPORTANT: Make sure Tesseract OCR is installed:
echo   Download from: https://github.com/UB-Mannheim/tesseract/wiki
echo   Install to: C:\Program Files\Tesseract-OCR
echo   Select language packs during installation (Chinese, Japanese, Korean)
echo.
echo To run the app, double-click: run.bat
echo.
pause
