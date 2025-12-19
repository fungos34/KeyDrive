#!/usr/bin/env python3
"""
KeyDrive GUI Launcher
=====================

Simple launcher for the KeyDrive GUI application.
This script can be bundled into an executable using PyInstaller.

Usage:
    python gui_launcher.py
    # or bundled: KeyDriveGUI.exe
"""

import os
import sys
from pathlib import Path

# Add project root and scripts directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPT_DIR = PROJECT_ROOT / "scripts"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Import and run the GUI
try:
    from gui import main

    main()
except ImportError as e:
    print(f"❌ Failed to import GUI module: {e}")
    print("Make sure PyQt6 is installed: pip install PyQt6 PyQt6-Qt6")
    input("Press Enter to exit...")
    sys.exit(1)
except Exception as e:
    print(f"❌ GUI Error: {e}")
    input("Press Enter to exit...")
    sys.exit(1)
    sys.exit(1)
