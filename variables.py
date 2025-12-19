# SmartDrive Variables Configuration
# This file provides backward compatibility and GUI-specific settings
# Core constants are imported from core.* modules (single source of truth)

import sys
from pathlib import Path

# Add core to path
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.constants import THEME_PALETTES, Branding, CryptoParams, FileNames, GUIConfig
from core.paths import Paths

# Import from core modules (single source of truth)
from core.version import VERSION as APP_VERSION

# =============================================================================
# Product Information (from core)
# =============================================================================
PRODUCT_NAME = Branding.PRODUCT_NAME
PRODUCT_DESCRIPTION = "Encrypted External Drive with YubiKey + GPG + VeraCrypt"

# =============================================================================
# File Names (from core.constants.FileNames)
# =============================================================================
BAT_LAUNCHER_NAME = FileNames.BAT_LAUNCHER
GUI_BAT_LAUNCHER_NAME = FileNames.GUI_BAT_LAUNCHER
SH_LAUNCHER_NAME = FileNames.SH_LAUNCHER
GUI_EXE_NAME = FileNames.GUI_EXE

# =============================================================================
# Directory Names (from core.paths.Paths)
# =============================================================================
SMARTDRIVE_DIR_NAME = Paths.SMARTDRIVE_DIR_NAME
KEYS_DIR_NAME = Paths.KEYS_SUBDIR
SCRIPTS_DIR_NAME = Paths.SCRIPTS_SUBDIR
INTEGRITY_DIR_NAME = Paths.INTEGRITY_SUBDIR

# =============================================================================
# Documentation Files (from core.constants.FileNames)
# =============================================================================
README_NAME = FileNames.README
GUI_README_NAME = FileNames.GUI_README
README_PDF_NAME = FileNames.README_PDF
GUI_README_PDF_NAME = FileNames.GUI_README_PDF

# =============================================================================
# UI Elements
# =============================================================================
WINDOW_TITLE = f"{PRODUCT_NAME} Manager"
BANNER_TITLE = f"{PRODUCT_NAME} Manager"

# =============================================================================
# Security Constants (from core.constants.CryptoParams)
# =============================================================================
SALT_PREFIX = f"{PRODUCT_NAME}-GPG-PW-Only-v1"
HKDF_INFO = CryptoParams.HKDF_INFO_DEFAULT

# =============================================================================
# Application Constants
# =============================================================================
APP_NAME = PRODUCT_NAME
ORGANIZATION_NAME = f"{PRODUCT_NAME} Project"

# =============================================================================
# GUI Constants (GUI-specific, not in core)
# =============================================================================
TITLE_MAX_CHARS = 18
TITLE_MIN_SIDE_CHARS = 2
WINDOW_WIDTH = 360
WINDOW_HEIGHT = 380
WINDOW_MARGIN = 20
CORNER_RADIUS = 12

# =============================================================================
# GUI Colors - Theme palette (SSOT)
# =============================================================================

# Backward-compatible export used by GUI. Default remains the SSOT GUI default.
COLORS = THEME_PALETTES[GUIConfig.DEFAULT_THEME].copy()
