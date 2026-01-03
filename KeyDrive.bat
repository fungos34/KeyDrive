@echo off
REM ============================================================
REM KeyDrive Launcher for Windows
REM ============================================================
REM Double-click this file to open the KeyDrive GUI application.
REM Automatically creates and activates OS-specific venv if needed.
REM CHG-20260103-001: Auto-creates venv and installs deps on first run
REM ============================================================

title KeyDrive

REM Change to the directory where this batch file is located
cd /d "%~dp0"

echo Starting KeyDrive...
echo.

REM ============================================================
REM VENV Detection, Creation, and Activation (CHG-20260103-001)
REM ============================================================
REM Priority:
REM   1. OS-specific venv at .smartdrive\.venv-win (auto-create if missing)
REM   2. Legacy venv at .smartdrive\.venv (backward compatibility)
REM   3. System Python in PATH (used to create venv)
REM ============================================================

set "VENV_DIR=.smartdrive\.venv-win"
set "VENV_ACTIVATE="
set "PYTHON_CMD="
set "PYTHONW_CMD="

REM Check for Windows-specific venv first (.venv-win)
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo Found bundled venv at %VENV_DIR%
    set "VENV_ACTIVATE=%~dp0%VENV_DIR%\Scripts\activate.bat"
    set "PYTHON_CMD=%~dp0%VENV_DIR%\Scripts\python.exe"
    set "PYTHONW_CMD=%~dp0%VENV_DIR%\Scripts\pythonw.exe"
    goto :venv_found
)

REM Fallback to legacy .venv for backward compatibility
if exist ".smartdrive\.venv\Scripts\python.exe" (
    echo Found legacy venv at .smartdrive\.venv
    set "VENV_ACTIVATE=%~dp0.smartdrive\.venv\Scripts\activate.bat"
    set "PYTHON_CMD=%~dp0.smartdrive\.venv\Scripts\python.exe"
    set "PYTHONW_CMD=%~dp0.smartdrive\.venv\Scripts\pythonw.exe"
    goto :venv_found
)

REM No bundled venv - need to create one
echo No Python environment found. Checking system Python...

REM Try multiple Python commands: python, py (Windows launcher), python3
set "SYS_PYTHON="
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "SYS_PYTHON=python"
    goto :python_found
)
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "SYS_PYTHON=py"
    goto :python_found
)
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "SYS_PYTHON=python3"
    goto :python_found
)

REM No Python found at all
echo.
echo ====================================================
echo   ERROR: Python not found
echo ====================================================
echo.
echo Python is required to run KeyDrive.
echo.
echo Please install Python 3.10+ from https://www.python.org/
echo (Check "Add Python to PATH" during installation)
echo.
pause
exit /b 1

:python_found
echo Found system Python: %SYS_PYTHON%

REM System Python available - create venv automatically
echo.
echo ====================================================
echo   First-time setup: Creating Python environment...
echo ====================================================
echo.
echo This may take a minute. Please wait...
echo.

REM Create venv
echo [1/3] Creating virtual environment at %VENV_DIR%...
%SYS_PYTHON% -m venv "%VENV_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to create virtual environment.
    echo Please ensure Python 3.10+ is properly installed.
    pause
    exit /b 1
)
echo       Done!

REM Set up paths
set "VENV_ACTIVATE=%~dp0%VENV_DIR%\Scripts\activate.bat"
set "PYTHON_CMD=%~dp0%VENV_DIR%\Scripts\python.exe"
set "PYTHONW_CMD=%~dp0%VENV_DIR%\Scripts\pythonw.exe"

REM Activate venv
call "%VENV_ACTIVATE%"

REM Install dependencies
echo.
echo [2/3] Installing dependencies from requirements.txt...
echo       (This may take a few minutes on first run)
echo.
if exist ".smartdrive\requirements.txt" (
    "%PYTHON_CMD%" -m pip install --upgrade pip >nul 2>&1
    "%PYTHON_CMD%" -m pip install -r ".smartdrive\requirements.txt"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo WARNING: Some dependencies may have failed to install.
        echo The GUI may not work correctly.
        echo.
        pause
    ) else (
        echo.
        echo       Done!
    )
) else (
    echo WARNING: requirements.txt not found. Dependencies not installed.
)

echo.
echo [3/3] Setup complete!
echo.
echo ====================================================
echo.
goto :run_gui

:venv_found
REM Activate the bundled venv
if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
    echo Venv activated
)

:run_gui
REM ============================================================
REM Bootstrap Dependencies (CHG-20260103-001)
REM ============================================================
REM Check for missing dependencies and install them automatically

if exist ".smartdrive\scripts\bootstrap_dependencies.py" (
    echo Checking dependencies...
    "%PYTHON_CMD%" -B ".smartdrive\scripts\bootstrap_dependencies.py" --check -q >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Updating Python dependencies...
        "%PYTHON_CMD%" -B ".smartdrive\scripts\bootstrap_dependencies.py" --auto
        if %ERRORLEVEL% NEQ 0 (
            echo.
            echo WARNING: Some dependencies may not be installed correctly.
            echo Press any key to continue anyway, or close this window to abort.
            pause >nul
        ) else (
            echo Dependencies updated successfully!
            echo.
        )
    )
)

REM ============================================================
REM Launch GUI
REM ============================================================

REM Check for gui.py in .smartdrive structure
if exist ".smartdrive\scripts\gui.py" (
    echo Launching KeyDrive GUI...
    echo.
    
    REM BUG-20260102-009: Use CALL to ensure proper variable expansion
    call :launch_gui
    goto :end
)

REM Fallback: Check for gui.py in scripts structure
if exist "scripts\gui.py" (
    echo Launching KeyDrive GUI from scripts\gui.py
    echo Current directory: %CD%
    echo.
    
    call :launch_gui_fallback
    goto :end
)

REM Fallback: Check for smartdrive.py (CLI)
if exist ".smartdrive\scripts\smartdrive.py" (
    echo Launching KeyDrive CLI from .smartdrive\scripts\smartdrive.py
    "%PYTHON_CMD%" -B ".smartdrive\scripts\smartdrive.py"
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

:launch_gui
REM Launch from .smartdrive\scripts\gui.py
REM BUG-20260102-009: Use start /B to run in background; quotes must surround entire path
if exist "%PYTHONW_CMD%" (
    start "KeyDrive" /B "%PYTHONW_CMD%" -B ".smartdrive\scripts\gui.py"
) else (
    "%PYTHON_CMD%" -B ".smartdrive\scripts\gui.py"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: GUI failed to start (exit code %ERRORLEVEL%)
        pause
    )
)
goto :eof

:launch_gui_fallback
REM Launch from scripts\gui.py (legacy)
if exist "%PYTHONW_CMD%" (
    start "KeyDrive" /B "%PYTHONW_CMD%" -B "scripts\gui.py"
) else (
    "%PYTHON_CMD%" -B "scripts\gui.py"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: GUI failed to start (exit code %ERRORLEVEL%)
        pause
    )
)
goto :eof

:end
REM Wait briefly for launch to complete
timeout /t 1 /nobreak >nul



