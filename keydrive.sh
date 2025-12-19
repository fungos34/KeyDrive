#!/bin/bash
# ============================================================
# KeyDrive Launcher for Linux/macOS
# ============================================================
# Run this script to open the KeyDrive Manager menu.
# Usage: ./keydrive.sh
# ============================================================

# Change to script directory
cd "$(dirname "$0")"

# Check if Python 3 is available
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo ""
    echo "ERROR: Python not found"
    echo ""
    echo "Please install Python 3.7+ using your package manager:"
    echo "  Ubuntu/Debian: sudo apt install python3"
    echo "  macOS:         brew install python3"
    echo "  Fedora:        sudo dnf install python3"
    echo ""
    exit 1
fi

# Run the KeyDrive manager
# Try new structure first (.smartdrive/), fall back to old (scripts/)
if [ -f ".smartdrive/scripts/gui.py" ]; then
    $PYTHON_CMD .smartdrive/scripts/gui.py
elif [ -f "scripts/gui.py" ]; then
    $PYTHON_CMD scripts/gui.py
else
    echo ""
    echo "ERROR: KeyDrive GUI not found!"
    echo "Expected: .smartdrive/scripts/gui.py or scripts/gui.py"
    exit 1
fi
