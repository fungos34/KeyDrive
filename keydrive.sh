#!/bin/bash
# ============================================================
# KeyDrive Launcher for Linux/macOS
# ============================================================
# Run this script to open the KeyDrive GUI application.
# Automatically activates bundled venv if present.
# Usage: ./keydrive.sh
# ============================================================

# Change to script directory
cd "$(dirname "$0")"

echo "Starting KeyDrive..."
echo

# ============================================================
# VENV Detection and Activation (BUG-20260102-012)
# ============================================================
# Priority:
#   1. OS-specific venv: .smartdrive/.venv-linux or .smartdrive/.venv-mac
#   2. Legacy venv: .smartdrive/.venv (backward compatibility)
#   3. System Python in PATH (fallback)
# ============================================================

PYTHON_CMD=""
VENV_ACTIVATE=""
VENV_NAME=""

# Detect OS for venv selection
if [[ "$OSTYPE" == "darwin"* ]]; then
    VENV_NAME=".venv-mac"
else
    VENV_NAME=".venv-linux"
fi

# Check for OS-specific venv first
if [ -f ".smartdrive/${VENV_NAME}/bin/python" ]; then
    echo "Found bundled venv at .smartdrive/${VENV_NAME}"
    VENV_ACTIVATE=".smartdrive/${VENV_NAME}/bin/activate"
    PYTHON_CMD=".smartdrive/${VENV_NAME}/bin/python"
    
    # Activate the venv
    if [ -f "$VENV_ACTIVATE" ]; then
        source "$VENV_ACTIVATE"
        echo "Venv activated"
    fi
# Fallback to legacy .venv for backward compatibility
elif [ -f ".smartdrive/.venv/bin/python" ]; then
    echo "Found legacy venv at .smartdrive/.venv"
    VENV_ACTIVATE=".smartdrive/.venv/bin/activate"
    PYTHON_CMD=".smartdrive/.venv/bin/python"
    
    # Activate the venv
    if [ -f "$VENV_ACTIVATE" ]; then
        source "$VENV_ACTIVATE"
        echo "Venv activated"
    fi
else
    # No bundled venv - check system Python
    echo "No bundled venv found, checking system Python..."
    
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        echo ""
        echo "ERROR: Python not found"
        echo ""
        echo "No bundled venv found at .smartdrive/${VENV_NAME}"
        echo "and Python is not available in system PATH."
        echo ""
        echo "Please install Python 3.10+ using your package manager:"
        echo "  Ubuntu/Debian: sudo apt install python3"
        echo "  macOS:         brew install python3"
        echo "  Fedora:        sudo dnf install python3"
        echo ""
        echo "Or copy a pre-configured venv to .smartdrive/${VENV_NAME}"
        echo ""
        exit 1
    fi
    
    echo "Using system Python: $($PYTHON_CMD --version)"
fi

# ============================================================
# Bootstrap Dependencies (CHG-20251229-002)
# ============================================================
# Check for missing dependencies and offer to install them

if [ -f ".smartdrive/scripts/bootstrap_dependencies.py" ]; then
    echo "Checking dependencies..."
    if ! $PYTHON_CMD -B .smartdrive/scripts/bootstrap_dependencies.py --check -q > /dev/null 2>&1; then
        echo ""
        echo "Some Python dependencies are missing."
        $PYTHON_CMD -B .smartdrive/scripts/bootstrap_dependencies.py
        if [ $? -ne 0 ]; then
            echo ""
            echo "Dependencies not installed. GUI may not work correctly."
            read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
        fi
    fi
fi

# ============================================================
# Launch GUI
# ============================================================

# Try new structure first (.smartdrive/), fall back to old (scripts/)
if [ -f ".smartdrive/scripts/gui.py" ]; then
    echo "Launching KeyDrive GUI from .smartdrive/scripts/gui.py"
    echo "Current directory: $(pwd)"
    echo
    $PYTHON_CMD -B .smartdrive/scripts/gui.py
elif [ -f "scripts/gui.py" ]; then
    echo "Launching KeyDrive GUI from scripts/gui.py"
    echo "Current directory: $(pwd)"
    echo
    $PYTHON_CMD -B scripts/gui.py
elif [ -f ".smartdrive/scripts/smartdrive.py" ]; then
    echo "Launching KeyDrive CLI from .smartdrive/scripts/smartdrive.py"
    $PYTHON_CMD -B .smartdrive/scripts/smartdrive.py
else
    echo ""
    echo "ERROR: KeyDrive scripts not found!"
    echo ""
    echo "Expected locations:"
    echo "  - .smartdrive/scripts/gui.py"
    echo "  - scripts/gui.py"
    echo "  - .smartdrive/scripts/smartdrive.py"
    echo ""
    exit 1
fi
