@echo off
REM ============================================================
REM KeyDrive GUI Launcher for Windows
REM ============================================================
REM This script launches the KeyDrive GUI application.
REM ============================================================

cd /d "%~dp0"

echo Starting KeyDrive GUI...

REM Check if Python is available
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Python not found in PATH
    echo.
    echo Please install Python 3.10+ from https://www.python.org/
    echo Ensure "Add Python to PATH" is checked during installation.
    echo.
    pause
    exit /b 1
)

REM Launch GUI - check .smartdrive structure first
if exist ".smartdrive\scripts\gui.py" (
    where pythonw >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        start "" pythonw -B ".smartdrive\scripts\gui.py"
    ) else (
        start "" python -B ".smartdrive\scripts\gui.py"
    )
) else if exist "scripts\gui.py" (
    where pythonw >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        start "" pythonw -B "scripts\gui.py"
    ) else (
        start "" python -B "scripts\gui.py"
    )
) else (
    echo.
    echo ERROR: Could not find gui.py
    echo.
    echo Expected locations:
    echo   - .smartdrive\scripts\gui.py
    echo   - scripts\gui.py
    echo.
    pause
    exit /b 1
)



