#!/usr/bin/env python3
"""
DEV-ONLY WRAPPER: Forwards to .smartdrive/scripts/gui.py

This wrapper allows running `python scripts/gui.py` from the repo root during development.
DO NOT deploy this file - it is not part of the runtime.
"""

import sys
from pathlib import Path

_wrapper_dir = Path(__file__).resolve().parent
_repo_root = _wrapper_dir.parent
_smartdrive_scripts = _repo_root / ".smartdrive" / "scripts"

if not _smartdrive_scripts.exists():
    print(f"ERROR: .smartdrive/scripts/ not found at {_smartdrive_scripts}")
    sys.exit(1)

sys.path.insert(0, str(_repo_root / ".smartdrive"))
sys.path.insert(0, str(_smartdrive_scripts))

# Import for re-export (allows `from scripts.gui import SettingsDialog`)
from gui import SettingsDialog, SmartDriveGUI, get_script_dir, main, resolve_config_path

# Only run main() when executed directly
if __name__ == "__main__":
    main()
