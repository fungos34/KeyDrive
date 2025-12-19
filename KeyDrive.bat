@echo off
REM ============================================================
REM KeyDrive Launcher for Windows
REM ============================================================
REM Double-click this file to open the KeyDrive Manager menu.
REM ============================================================

title KeyDrive Manager

REM Change to the directory where this batch file is located
cd /d "%~dp0"

echo Starting KeyDrive...
echo.

REM Check if Python is available
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found in PATH
    echo.
    echo Please install Python 3.10+ from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Check for gui.py in .smartdrive structure
if exist ".smartdrive\scripts\gui.py" (
    echo Launching KeyDrive GUI from .smartdrive\scripts\gui.py
    echo Current directory: %CD%
    echo.
    python -B ".smartdrive\scripts\gui.py"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: GUI failed to start (exit code %ERRORLEVEL%)
        pause
    )
    goto :end
)

REM Fallback: Check for gui.py in scripts structure
if exist "scripts\gui.py" (
    echo Launching KeyDrive GUI from scripts\gui.py
    echo Current directory: %CD%
    echo.
    python -B "scripts\gui.py"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: GUI failed to start (exit code %ERRORLEVEL%)
        pause
    )
    goto :end
)

REM Fallback: Check for smartdrive.py
if exist ".smartdrive\scripts\smartdrive.py" (
    echo Launching KeyDrive menu from .smartdrive\scripts\smartdrive.py
    where pythonw >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        start "" pythonw -B ".smartdrive\scripts\smartdrive.py"
    ) else (
        start "" python -B ".smartdrive\scripts\smartdrive.py"
    )
    goto :end
)

REM No valid scripts found
echo.
echo ERROR: Could not find KeyDrive scripts
echo.
echo Expected locations:
echo   - .smartdrive\scripts\gui.py
echo   - scripts\gui.py
echo   - .smartdrive\scripts\smartdrive.py
echo.
echo Current directory: %CD%
echo.
pause
exit /b 1

:end
REM Wait briefly for launch to complete
timeout /t 2 /nobreak >nul



