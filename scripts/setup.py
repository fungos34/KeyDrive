#!/usr/bin/env python3
"""
DEV-ONLY WRAPPER: Forwards to .smartdrive/scripts/setup.py

This wrapper allows running `python scripts/setup.py` from the repo root during development.
DO NOT deploy this file - it is not part of the runtime.

The actual implementation is in .smartdrive/scripts/setup.py
"""

import sys
from pathlib import Path

# Find .smartdrive relative to this wrapper
_wrapper_dir = Path(__file__).resolve().parent
_repo_root = _wrapper_dir.parent
_smartdrive_scripts = _repo_root / ".smartdrive" / "scripts"

if not _smartdrive_scripts.exists():
    print(f"ERROR: .smartdrive/scripts/ not found at {_smartdrive_scripts}")
    print("This wrapper requires the canonical .smartdrive/ structure.")
    sys.exit(1)

# Add .smartdrive to path and run the real script
sys.path.insert(0, str(_repo_root / ".smartdrive"))
sys.path.insert(0, str(_smartdrive_scripts))

from setup import main

main()
