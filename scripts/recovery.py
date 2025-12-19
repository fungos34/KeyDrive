#!/usr/bin/env python3
"""
DEV-ONLY WRAPPER: Forwards to .smartdrive/scripts/recovery.py

This wrapper allows running `python scripts/recovery.py` from the repo root during development.
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

from recovery import main

main()
