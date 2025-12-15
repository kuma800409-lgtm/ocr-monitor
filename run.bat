@echo off
echo ============================================
echo   OCR Monitor - Starting App
echo ============================================
echo.

REM Check if venv exists
if not exist venv (
    echo ERROR: Virtual environment not found!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Starting OCR Monitor...
echo.
echo Press Ctrl+Shift+X to select a screen region
echo.

python main.py

REM Keep window open if there's an error
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
