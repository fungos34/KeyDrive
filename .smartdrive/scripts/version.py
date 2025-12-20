# SmartDrive Version
# This file imports from the single source of truth: core/version.py
# DO NOT define VERSION here - import it instead

import sys
from pathlib import Path

# Add parent directory to path for core module imports
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
from core.paths import Paths
if _script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
    # Deployed on drive: .smartdrive/scripts/version.py
    _deploy_root = _script_dir.parent
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/version.py at repo root
    _project_root = _script_dir.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from core.version import VERSION

__all__ = ["VERSION"]
