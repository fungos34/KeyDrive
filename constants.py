# SmartDrive Configuration Constants
# This file provides backward compatibility - imports from core modules
# New code should import directly from core.* modules

import sys
from pathlib import Path

# Add core to path
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.constants import Branding, ConfigKeys, CryptoParams, Defaults, FileNames
from core.paths import Paths

# Import from core modules (single source of truth)
from core.version import VERSION

# =============================================================================
# Legacy exports for backward compatibility
# =============================================================================

# Product branding
PRODUCT_NAME = Branding.PRODUCT_NAME
PRODUCT_DESCRIPTION = "Encrypted External Drive with YubiKey + GPG + VeraCrypt"
AUTHOR = f"{PRODUCT_NAME} Project"

# Directory names (from Paths)
SMARTDRIVE_DIR_NAME = Paths.SMARTDRIVE_DIR_NAME
KEYS_DIR_NAME = Paths.KEYS_SUBDIR
SCRIPTS_DIR_NAME = Paths.SCRIPTS_SUBDIR
INTEGRITY_DIR_NAME = Paths.INTEGRITY_SUBDIR

# File extensions and prefixes
KEYFILE_PREFIX = "keyfile"
SEED_PREFIX = "seed"
CONFIG_FILE_NAME = FileNames.CONFIG_JSON

# File names (from FileNames)
BAT_LAUNCHER_NAME = FileNames.BAT_LAUNCHER
GUI_BAT_LAUNCHER_NAME = FileNames.GUI_BAT_LAUNCHER
SH_LAUNCHER_NAME = FileNames.SH_LAUNCHER
GUI_EXE_NAME = FileNames.GUI_EXE
README_NAME = FileNames.README
GUI_README_NAME = FileNames.GUI_README
README_PDF_NAME = FileNames.README_PDF
GUI_README_PDF_NAME = FileNames.GUI_README_PDF

# UI Constants
WINDOW_TITLE = f"{PRODUCT_NAME} Manager"
BANNER_TITLE = f"{PRODUCT_NAME} Manager"

# Security constants (from CryptoParams)
SALT_PREFIX = f"{PRODUCT_NAME}-GPG-PW-Only-v1"
HKDF_INFO = CryptoParams.HKDF_INFO_DEFAULT
