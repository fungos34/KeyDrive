@echo off
REM ============================================================
REM KeyDrive Launcher for Windows
REM ============================================================
REM Double-click this file to open the KeyDrive GUI application.
REM Automatically activates bundled venv if present.
REM ============================================================

title KeyDrive

REM Change to the directory where this batch file is located
cd /d "%~dp0"

echo Starting KeyDrive...
echo.

REM ============================================================
REM VENV Detection and Activation
REM ============================================================
REM Priority:
REM   1. Bundled venv at .smartdrive\.venv (portable deployment)
REM   2. System Python in PATH (fallback)
REM ============================================================

set "VENV_ACTIVATE="
set "PYTHON_CMD="
set "PYTHONW_CMD="

REM Check for bundled venv in .smartdrive\.venv
if exist ".smartdrive\.venv\Scripts\python.exe" (
    echo Found bundled venv at .smartdrive\.venv
    set "VENV_ACTIVATE=%~dp0.smartdrive\.venv\Scripts\activate.bat"
    set "PYTHON_CMD=%~dp0.smartdrive\.venv\Scripts\python.exe"
    set "PYTHONW_CMD=%~dp0.smartdrive\.venv\Scripts\pythonw.exe"
    goto :venv_found
)

REM No bundled venv - check system Python
echo No bundled venv found, checking system Python...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Python not found
    echo.
    echo No bundled venv found at .smartdrive\.venv
    echo and Python is not available in system PATH.
    echo.
    echo Please either:
    echo   1. Install Python 3.10+ from https://www.python.org/
    echo      (Check "Add Python to PATH" during installation)
    echo   2. Copy a pre-configured .venv to .smartdrive\.venv
    echo.
    pause
    exit /b 1
)

REM System Python available - find pythonw.exe
for /f "delims=" %%i in ('python -c "import sys, os; print(os.path.dirname(sys.executable))"') do set PYTHON_DIR=%%i
set "PYTHON_CMD=python"
if exist "%PYTHON_DIR%\pythonw.exe" (
    set "PYTHONW_CMD=%PYTHON_DIR%\pythonw.exe"
) else (
    set "PYTHONW_CMD=python"
)
echo Using system Python: %PYTHON_DIR%
goto :run_gui

:venv_found
REM Activate the bundled venv
if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
    echo Venv activated
)

:run_gui
REM ============================================================
REM Bootstrap Dependencies (CHG-20251229-002)
REM ============================================================
REM Check for missing dependencies and offer to install them

if exist ".smartdrive\scripts\bootstrap_dependencies.py" (
    echo Checking dependencies...
    "%PYTHON_CMD%" -B ".smartdrive\scripts\bootstrap_dependencies.py" --check -q >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Some Python dependencies are missing.
        "%PYTHON_CMD%" -B ".smartdrive\scripts\bootstrap_dependencies.py"
        if %ERRORLEVEL% NEQ 0 (
            echo.
            echo Dependencies not installed. GUI may not work correctly.
            echo Press any key to continue anyway, or close this window to abort.
            pause >nul
        )
    )
)

REM ============================================================
REM Launch GUI
REM ============================================================

REM Check for gui.py in .smartdrive structure
if exist ".smartdrive\scripts\gui.py" (
    echo Launching KeyDrive GUI from .smartdrive\scripts\gui.py
    echo Current directory: %CD%
    echo PYTHONW_CMD: %PYTHONW_CMD%
    echo.
    
    REM BUG-20260102-009: Use CALL to ensure proper variable expansion
    REM The if exist check was failing due to batch parser evaluating before goto
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



