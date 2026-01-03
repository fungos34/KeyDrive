#!/bin/bash
# ============================================================
# KeyDrive Launcher for Linux/macOS
# ============================================================
# Run this script to open the KeyDrive GUI application.
# Automatically creates and activates OS-specific venv if needed.
# CHG-20260103-001: Auto-creates venv and installs deps on first run
# Usage: ./keydrive.sh
# ============================================================

# Change to script directory
cd "$(dirname "$0")"

echo "Starting KeyDrive..."
echo

# ============================================================
# VENV Detection, Creation, and Activation (CHG-20260103-001)
# ============================================================
# Priority:
#   1. OS-specific venv: .smartdrive/.venv-linux or .smartdrive/.venv-mac (auto-create if missing)
#   2. Legacy venv: .smartdrive/.venv (backward compatibility)
#   3. System Python in PATH (used to create venv)
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
    # No bundled venv - need to create one
    echo "No Python environment found. Checking system Python..."
    
    SYSTEM_PYTHON=""
    if command -v python3 &> /dev/null; then
        SYSTEM_PYTHON="python3"
    elif command -v python &> /dev/null; then
        SYSTEM_PYTHON="python"
    else
        echo ""
        echo "===================================================="
        echo "  ERROR: Python not found"
        echo "===================================================="
        echo ""
        echo "Python is required to run KeyDrive."
        echo ""
        echo "Please install Python 3.10+ using your package manager:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
        echo "  macOS:         brew install python3"
        echo "  Fedora:        sudo dnf install python3"
        echo ""
        exit 1
    fi
    
    # System Python available - create venv automatically
    echo ""
    echo "===================================================="
    echo "  First-time setup: Creating Python environment..."
    echo "===================================================="
    echo ""
    echo "This may take a minute. Please wait..."
    echo ""
    
    VENV_DIR=".smartdrive/${VENV_NAME}"
    
    # Create venv
    echo "[1/3] Creating virtual environment at ${VENV_DIR}..."
    $SYSTEM_PYTHON -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: Failed to create virtual environment."
        echo "Please ensure Python 3.10+ is properly installed with venv support."
        echo "  Ubuntu/Debian: sudo apt install python3-venv"
        exit 1
    fi
    echo "      Done!"
    
    # Set up paths
    VENV_ACTIVATE="${VENV_DIR}/bin/activate"
    PYTHON_CMD="${VENV_DIR}/bin/python"
    
    # Activate venv
    source "$VENV_ACTIVATE"
    
    # Install dependencies
    echo ""
    echo "[2/3] Installing dependencies from requirements.txt..."
    echo "      (This may take a few minutes on first run)"
    echo ""
    if [ -f ".smartdrive/requirements.txt" ]; then
        "$PYTHON_CMD" -m pip install --upgrade pip > /dev/null 2>&1
        "$PYTHON_CMD" -m pip install -r ".smartdrive/requirements.txt"
        if [ $? -ne 0 ]; then
            echo ""
            echo "WARNING: Some dependencies may have failed to install."
            echo "The GUI may not work correctly."
            echo ""
            read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
        else
            echo ""
            echo "      Done!"
        fi
    else
        echo "WARNING: requirements.txt not found. Dependencies not installed."
    fi
    
    echo ""
    echo "[3/3] Setup complete!"
    echo ""
    echo "===================================================="
    echo ""
fi

# ============================================================
# Bootstrap Dependencies (CHG-20260103-001)
# ============================================================
# Check for missing dependencies and install them automatically

if [ -f ".smartdrive/scripts/bootstrap_dependencies.py" ]; then
    echo "Checking dependencies..."
    if ! $PYTHON_CMD -B .smartdrive/scripts/bootstrap_dependencies.py --check -q > /dev/null 2>&1; then
        echo ""
        echo "Updating Python dependencies..."
        $PYTHON_CMD -B .smartdrive/scripts/bootstrap_dependencies.py --auto
        if [ $? -ne 0 ]; then
            echo ""
            echo "WARNING: Some dependencies may not be installed correctly."
            read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
        else
            echo "Dependencies updated successfully!"
            echo ""
        fi
    fi
fi

# ============================================================
# Launch GUI
# ============================================================

# Try new structure first (.smartdrive/), fall back to old (scripts/)
if [ -f ".smartdrive/scripts/gui.py" ]; then
    echo "Launching KeyDrive GUI..."
    echo
    $PYTHON_CMD -B .smartdrive/scripts/gui.py
elif [ -f "scripts/gui.py" ]; then
    echo "Launching KeyDrive GUI..."
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
