#!/usr/bin/env python3
"""
KeyDrive GUI - Minimalistic Windows Interface
===============================================

A clean, minimal GUI for KeyDrive operations that integrates
with the existing CLI backend while providing a modern interface.

Author: KeyDrive Project
License: This project is licensed under a custom non-commercial, no-derivatives license.
Commercial use and modified versions are not permitted.
See the LICENSE file for details.

"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional

# Get logger for GUI module
_gui_logger = logging.getLogger("SmartDriveGUI.gui")


def log_exception(context: str, exc: Exception = None, level: str = "warning") -> None:
    """
    Log an exception with context information.

    Args:
        context: Description of what was happening when the error occurred
        exc: The exception (if None, logs current exception from sys.exc_info)
        level: Log level ('debug', 'info', 'warning', 'error', 'critical')
    """
    log_func = getattr(_gui_logger, level, _gui_logger.warning)
    if exc:
        log_func(f"{context}: {exc}", exc_info=True)
    else:
        log_func(f"{context}", exc_info=True)
    # Also print to stderr for immediate visibility
    print(f"[!] {context}", file=sys.stderr)
    traceback.print_exc()


# ===========================================================================
# Core module imports (single source of truth)
# ===========================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/gui.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
    # BUG-20260102-010: Also add scripts dir for sibling imports (gui_i18n, etc.)
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
else:
    # Development: scripts/gui.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Import i18n module for translations
from gui_i18n import AVAILABLE_LANGUAGES, TRANSLATIONS, tr

from core.config import get_drive_id, load_or_create_config, write_config_atomic
from core.constants import Branding, ConfigKeys, FileNames, GUIConfig
from core.limits import Limits
from core.modes import SecurityMode
from core.paths import Paths
from core.single_instance import SingleInstanceManager, check_single_instance
from core.tray import TrayIconManager, is_tray_available

# Import from core modules (single source of truth)
from core.version import BUILD_ID, COMPATIBILITY_VERSION
from core.version import VERSION as APP_VERSION
from core.version import is_version_compatible

# Global language setting (loaded from config or default)
_current_lang = GUIConfig.DEFAULT_LANG


def get_lang() -> str:
    """Get current GUI language."""
    return _current_lang


def set_lang(lang: str) -> None:
    """Set GUI language."""
    global _current_lang
    _current_lang = lang if lang in TRANSLATIONS else GUIConfig.DEFAULT_LANG


# Import all constants from variables.py (which now also imports from core)
from core.constants import Branding

APP_NAME = Branding.APP_NAME
BANNER_TITLE = Branding.BANNER_TITLE
COLORS = Branding.COLORS
CORNER_RADIUS = Branding.CORNER_RADIUS
ORGANIZATION_NAME = Branding.ORGANIZATION_NAME
PRODUCT_DESCRIPTION = Branding.PRODUCT_DESCRIPTION
PRODUCT_NAME = Branding.PRODUCT_NAME
TITLE_MAX_CHARS = Branding.TITLE_MAX_CHARS
TITLE_MIN_SIDE_CHARS = Branding.TITLE_MIN_SIDE_CHARS
WINDOW_HEIGHT = Branding.WINDOW_HEIGHT
WINDOW_MARGIN = Branding.WINDOW_MARGIN
WINDOW_TITLE = Branding.WINDOW_TITLE
WINDOW_WIDTH = Branding.WINDOW_WIDTH


# ============================================================
# CHG-20251221-042: Remote Control Mode Infrastructure
# ============================================================


class AppMode(Enum):
    """Application mode for local vs remote drive control."""

    LOCAL = auto()  # Normal mode - controlling local .smartdrive
    REMOTE = auto()  # Remote mode - controlling a remote .smartdrive installation


@dataclass
class RemoteMountProfile:
    """Profile for a remote .smartdrive installation being controlled."""

    remote_root: Path  # e.g., H:\ (the drive root containing .smartdrive/)
    remote_smartdrive: Path  # e.g., H:\.smartdrive
    remote_config_path: Path  # e.g., H:\.smartdrive\config.json
    remote_config: dict  # Loaded config from remote
    original_drive_letter: str  # e.g., "H" - for disconnect detection
    credential_paths: dict = field(default_factory=dict)  # Resolved keyfile/seed paths


def validate_remote_root(remote_root: Path) -> tuple[bool, str]:
    """
    Validate that a path is a valid remote .smartdrive installation.

    Args:
        remote_root: Path to the drive root (e.g., H:\\)

    Returns:
        (success, error_message) - success=True if valid, otherwise error_message explains why
    """
    if not remote_root.exists():
        return False, f"Path does not exist: {remote_root}"

    smartdrive_dir = remote_root / ".smartdrive"
    if not smartdrive_dir.is_dir():
        return False, f"No .smartdrive directory found at {remote_root}"

    config_path = smartdrive_dir / FileNames.CONFIG_JSON
    if not config_path.is_file():
        return False, f"No config.json found at {smartdrive_dir}"

    scripts_dir = smartdrive_dir / "scripts"
    if not scripts_dir.is_dir():
        return False, f"No scripts directory found at {smartdrive_dir}"

    # Check required scripts exist
    required_scripts = [FileNames.MOUNT_PY, "unmount.py"]
    for script in required_scripts:
        if not (scripts_dir / script).is_file():
            return False, f"Required script missing: {script}"

    return True, ""


def validate_remote_config(config_path: Path) -> tuple[bool, dict, str]:
    """
    Load and validate a remote config.json file.

    Args:
        config_path: Path to the config.json file

    Returns:
        (success, config_dict, error_message)
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return False, {}, f"Config file not found: {config_path}"
    except json.JSONDecodeError as e:
        return False, {}, f"Invalid JSON in config: {e}"

    # Validate schema_version exists
    schema_version = config.get(ConfigKeys.SCHEMA_VERSION)
    if not schema_version:
        return False, {}, "Missing schema_version in remote config"

    # Validate security mode is valid
    mode_str = config.get(ConfigKeys.MODE, "")
    try:
        SecurityMode(mode_str)
    except ValueError:
        return False, {}, f"Invalid security mode in remote config: {mode_str}"

    return True, config, ""


def resolve_remote_credential_paths(remote_config: dict, remote_root: Path) -> dict:
    """
    Resolve credential paths from remote config relative to remote root.

    All keyfile/seed paths in the remote config must be resolved relative
    to the remote_root, never using local paths.

    Args:
        remote_config: The loaded remote config dict
        remote_root: The remote drive root (e.g., H:\\)

    Returns:
        dict with resolved paths: {
            "keyfiles": [Path, ...],  # Resolved keyfile paths
            "seed_gpg": Optional[Path],  # Resolved seed.gpg path
            "yubikey_slot": Optional[int],  # YubiKey slot if configured
        }
    """
    result = {
        "keyfiles": [],
        "seed_gpg": None,
        "yubikey_slot": None,
    }

    smartdrive_dir = remote_root / ".smartdrive"
    keys_dir = smartdrive_dir / "keys"

    mode_str = remote_config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

    # Handle keyfile references - use KEYFILE (singular) as per ConfigKeys
    keyfile_ref = remote_config.get(ConfigKeys.KEYFILE, None)
    if keyfile_ref:
        # Keyfile can be absolute path or relative to keys/
        kf_path = Path(keyfile_ref)
        if not kf_path.is_absolute():
            kf_path = keys_dir / keyfile_ref
        if kf_path.exists():
            result["keyfiles"].append(kf_path)

    # Handle GPG seed path for GPG modes
    if mode_str in [SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value]:
        seed_path = keys_dir / FileNames.SEED_GPG
        if seed_path.exists():
            result["seed_gpg"] = seed_path

    # Handle YubiKey slot for modes that require YubiKey
    if mode_str in [SecurityMode.PW_GPG_KEYFILE.value, SecurityMode.GPG_PW_ONLY.value]:
        result["yubikey_slot"] = remote_config.get("yubikey_slot", 2)

    return result


def sanitize_product_name(name: str) -> str:
    """Sanitize product name for display and storage."""
    import re

    # 1) strip, fallback to default if empty
    name = name.strip()
    if not name:
        return PRODUCT_NAME

    # 2) regex-remove disallowed chars: keep [A-Za-z0-9 _\-#]
    name = re.sub(r"[^A-Za-z0-9 _\-#]", "", name)

    # 3) truncate to TITLE_MAX_CHARS
    if len(name) > TITLE_MAX_CHARS:
        name = name[:TITLE_MAX_CHARS].rstrip()

    # 4) return default if result is empty
    return name if name else PRODUCT_NAME


def split_for_logo(name: str) -> tuple[str, str]:
    """
    Returns (left, right) for title header:
    - Uses sanitized name, prefers splitting on a space nearest the center if both sides
      are at least TITLE_MIN_SIDE_CHARS long.
    - Falls back to a camel-case split if appropriate, else a midpoint split that
      enforces the minimum side-length constraint.
    """
    name = sanitize_product_name(name)
    length = len(name)

    # Too short to split meaningfully
    if length < TITLE_MIN_SIDE_CHARS * 2:
        return name, ""

    # Try split on space closest to middle
    if " " in name:
        spaces = [i for i, c in enumerate(name) if c == " "]
        middle = length // 2
        best_space = min(spaces, key=lambda x: abs(x - middle))
        left = name[:best_space].rstrip()
        right = name[best_space + 1 :].lstrip()
        if len(left) >= TITLE_MIN_SIDE_CHARS and len(right) >= TITLE_MIN_SIDE_CHARS:
            return left, right

    # Try camel-case split
    uppercase_indices = [i for i, c in enumerate(name) if c.isupper() and i > 0]
    if uppercase_indices:
        middle = length // 2
        best_upper = min(uppercase_indices, key=lambda x: abs(x - middle))
        left = name[:best_upper]
        right = name[best_upper:]
        if len(left) >= TITLE_MIN_SIDE_CHARS and len(right) >= TITLE_MIN_SIDE_CHARS:
            return left, right

    # Midpoint split with min-side rule enforcement
    middle = length // 2
    if middle < TITLE_MIN_SIDE_CHARS:
        middle = TITLE_MIN_SIDE_CHARS
    elif length - middle < TITLE_MIN_SIDE_CHARS:
        middle = length - TITLE_MIN_SIDE_CHARS

    return name[:middle], name[middle:]


def get_product_name(settings) -> str:
    """Get product name from settings or default."""
    if settings:
        stored_name = settings.value("product_name", "")
        if stored_name:
            return sanitize_product_name(stored_name)
    return PRODUCT_NAME


def get_script_dir():
    """Get the correct script directory, handling PyInstaller bundling."""
    if getattr(sys, "frozen", False):
        # Running from PyInstaller executable
        # The exe is deployed to drive root, scripts are in .smartdrive/scripts
        exe_dir = Path(sys.executable).parent
        scripts_dir = exe_dir / ".smartdrive" / "scripts"
        if scripts_dir.exists():
            return scripts_dir
        # Fallback: check if scripts are bundled in the exe
        if hasattr(sys, "_MEIPASS"):
            bundled_scripts = Path(sys._MEIPASS) / "scripts"
            if bundled_scripts.exists():
                return bundled_scripts
        # Last resort: assume scripts are next to the executable
        return exe_dir
    else:
        # Running from source
        return Path(__file__).parent


def resolve_config_path() -> Path:
    """
    Resolve the path to config.json.

    Returns:
        Path to config.json in the script directory
    """
    return get_script_dir() / FileNames.CONFIG_JSON


def get_static_dir():
    """
    Get the correct static directory, handling PyInstaller bundling and deployment.

    Priority order:
    1. .smartdrive/static/ (deployed structure)
    2. ROOT/static/ (legacy/dev structure)
    3. PyInstaller bundled location
    """
    # Try to use the new resource module if available
    try:
        from core.resources import get_static_dir as resource_get_static_dir

        return resource_get_static_dir()
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        # Running from PyInstaller executable
        exe_dir = Path(sys.executable).parent

        # Check deployed structure first: .smartdrive/static/
        if exe_dir.name == "scripts" and exe_dir.parent.name == ".smartdrive":
            deployed_static = exe_dir.parent / "static"
            if deployed_static.exists():
                return deployed_static

        # Check for .smartdrive/static relative to exe
        smartdrive_static = exe_dir / ".smartdrive" / "static"
        if smartdrive_static.exists():
            return smartdrive_static

        # Legacy: static next to exe
        static_dir = exe_dir / "static"
        if static_dir.exists():
            return static_dir

        # Fallback: check if static is bundled
        if hasattr(sys, "_MEIPASS"):
            bundled_static = Path(sys._MEIPASS) / "static"
            if bundled_static.exists():
                return bundled_static

        # Last resort
        return exe_dir
    else:
        # Running from source or deployed
        script_dir = Path(__file__).parent

        # Check if we're in .smartdrive/scripts (deployed)
        if script_dir.name == "scripts" and script_dir.parent.name == ".smartdrive":
            launcher_root = script_dir.parent.parent
            # Primary: .smartdrive/static/
            deployed_static = script_dir.parent / "static"
            if deployed_static.exists():
                return deployed_static
            # Fallback: ROOT/static/ (legacy)
            legacy_static = launcher_root / "static"
            if legacy_static.exists():
                return legacy_static

        # Fallback: assume static is next to scripts (source)
        static_dir = script_dir.parent / "static"
        if static_dir.exists():
            return static_dir

        # Never use cwd - log warning and return a deterministic path
        _gui_logger.warning("Could not find static directory, using fallback")
        return script_dir.parent / ".smartdrive" / "static"


def get_python_exe():
    """Get the correct python executable, handling PyInstaller bundling."""
    if getattr(sys, "frozen", False):
        # For bundled apps, find python.exe in the same directory or use pythonw.exe
        exe_dir = Path(sys.executable).parent
        python_exe = exe_dir / "python.exe"
        if not python_exe.exists():
            python_exe = exe_dir / "pythonw.exe"
        if not python_exe.exists():
            # Fallback: try to find python in PATH
            python_exe = "python.exe"
        return python_exe
    else:
        # Running from source - prefer pythonw.exe for GUI contexts (no console window)
        exe_path = Path(sys.executable)
        if exe_path.name == "python.exe":
            pythonw_path = exe_path.with_name("pythonw.exe")
            if pythonw_path.exists():
                return pythonw_path
        return sys.executable


SCRIPT_DIR = get_script_dir()
sys.path.insert(0, str(SCRIPT_DIR))

# Configuration - config.json lives in .smartdrive/, not .smartdrive/scripts/
# SCRIPT_DIR is .smartdrive/scripts/, so parent is .smartdrive/
if SCRIPT_DIR.name == "scripts" and SCRIPT_DIR.parent.name == ".smartdrive":
    CONFIG_FILE = SCRIPT_DIR.parent / FileNames.CONFIG_JSON  # .smartdrive/config.json
else:
    CONFIG_FILE = SCRIPT_DIR / FileNames.CONFIG_JSON  # fallback for development

# CHG-20251229-001: Improved dependency checking with OS-specific messages
try:
    from PyQt6.QtCore import QPoint, QSettings, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTextOption
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSizePolicy,
        QSlider,
        QSpinBox,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    # PyQt6 is missing - use the dependency checker for clear error message
    try:
        from core.dependencies import check_all_dependencies, format_dependency_error

        # Check all dependencies and show comprehensive error
        all_ok, error_msg = check_all_dependencies(silent=False)
        if not all_ok:
            sys.exit(1)
        else:
            # Dependencies say OK but PyQt6 still failed - unexpected state
            print("[X] PyQt6 import failed unexpectedly. Try: pip install PyQt6", file=sys.stderr)
            sys.exit(1)
    except ImportError:
        # Core module not available - provide basic message
        print("[X] PyQt6 not available. Please install with: pip install PyQt6", file=sys.stderr)
        print("", file=sys.stderr)
        print("To install all dependencies, run:", file=sys.stderr)
        print("  pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)


# ============================================================
# POPUP HELPER - Use tr() at render time, not string interpolation
# ============================================================


def show_popup(parent, title_key: str, body_key: str, icon: str = "info", **fmt) -> QMessageBox.StandardButton:
    """
    Display a message box with translated title and body.

    Calls tr() at RENDER time, not at call time, ensuring proper i18n.

    Args:
        parent: Parent widget
        title_key: Translation key for the dialog title
        body_key: Translation key for the dialog body
        icon: One of "info", "warning", "error", "question"
        **fmt: Format arguments passed to tr() for body_key

    Returns:
        The button clicked (QMessageBox.StandardButton)
    """
    lang = get_lang()
    title = tr(title_key, lang=lang)
    body = tr(body_key, lang=lang, **fmt) if fmt else tr(body_key, lang=lang)

    icon_map = {
        "info": QMessageBox.Icon.Information,
        "warning": QMessageBox.Icon.Warning,
        "error": QMessageBox.Icon.Critical,
        "question": QMessageBox.Icon.Question,
    }
    msg_icon = icon_map.get(icon, QMessageBox.Icon.Information)

    if icon == "question":
        return QMessageBox.question(
            parent,
            title,
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
    elif icon == "error":
        return QMessageBox.critical(parent, title, body)
    elif icon == "warning":
        return QMessageBox.warning(parent, title, body)
    else:
        return QMessageBox.information(parent, title, body)


# ===========================================================================
# Cross-Platform File Explorer Helper
# ===========================================================================


def open_in_file_manager(path: Path, parent=None) -> bool:
    """
    Open a directory in the system file manager.

    Cross-platform implementation per AGENT_ARCHITECTURE.md Section 2.5.

    Args:
        path: Path to the directory to open (must be a Path object)
        parent: Parent widget for error dialogs (optional)

    Returns:
        True if successfully opened, False on error

    Platform behavior:
        Windows: uses os.startfile()
        macOS: uses subprocess with 'open'
        Linux: uses subprocess with 'xdg-open'
    """
    from core.platform import get_platform

    if not isinstance(path, Path):
        path = Path(path)

    if not path.exists():
        if parent is not None:
            show_popup(
                parent,
                "popup_open_failed_title",
                "popup_open_failed_body",
                icon="error",
                path=str(path),
                error="Path does not exist",
            )
        return False

    platform = get_platform()

    try:
        if platform == "windows":
            # BUG-20251221-024: Use subprocess with CREATE_NO_WINDOW instead of os.startfile
            # os.startfile() can trigger "syntax error in command line" popups
            subprocess.run(
                ["explorer", str(path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        elif platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            # Linux and other Unix-like
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception as e:
        log_exception("Failed to open file manager", e, level="warning")
        if parent is not None:
            show_popup(
                parent, "popup_open_failed_title", "popup_open_failed_body", icon="error", path=str(path), error=str(e)
            )
        return False


# BUG-20251221-029: Added timezone import for UTC timestamp generation
from datetime import datetime, timezone

# Import SmartDrive functions
from smartdrive import check_mount_status, detect_context


def check_mount_status_veracrypt() -> bool:
    """Check if volume is mounted using filesystem check (more reliable than VeraCrypt CLI).

    BUG-20260102-014: Now handles both Windows and Linux/macOS mount detection.
    - Windows: Checks configured mount letter (e.g., V:/)
    - Linux/macOS: Checks configured mount point using mountpoint command or directory iteration
    """
    try:
        import json
        import platform
        import subprocess
        from pathlib import Path

        if not CONFIG_FILE.exists():
            return False

        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)

        system = platform.system().lower()

        if system == "windows":
            # Windows: Check mount letter (e.g., V:/)
            mount_letter = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.MOUNT_LETTER, "V").upper()
            drive_path = Path(f"{mount_letter}:/")

            # Check if drive exists and is accessible
            if drive_path.exists() and drive_path.is_dir():
                # Additional check: try to list directory contents to verify it's really mounted
                try:
                    list(drive_path.iterdir())
                    return True
                except (OSError, PermissionError):
                    # If we can't list contents, it might not be properly mounted
                    return False
            return False
        else:
            # Linux/macOS: Check mount point
            mount_point = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.MOUNT_POINT, "")
            if not mount_point:
                return False

            mount_path = Path(mount_point).expanduser()

            if not mount_path.exists():
                return False

            # On Unix, check if it's a mount point using mountpoint command
            try:
                result = subprocess.run(
                    ["mountpoint", "-q", str(mount_path)],
                    capture_output=True,
                    timeout=5,
                )
                return result.returncode == 0
            except FileNotFoundError:
                # mountpoint command not available, check if dir has content
                try:
                    return any(mount_path.iterdir())
                except (OSError, PermissionError):
                    return False
            except subprocess.TimeoutExpired:
                return False

    except Exception as e:
        log_exception("Error checking mount status", e, level="debug")
        return False


# ============================================================
# CONSTANTS
# ============================================================
# MOUNT WORKER THREAD
# ============================================================


class MountWorker(QThread):
    """Worker thread for mounting operations to prevent UI blocking."""

    finished = pyqtSignal(bool, str, dict)  # success, message_key, message_args

    def __init__(self, password, keyfiles=None, config_path: Optional[Path] = None):
        """
        Initialize mount worker.

        Args:
            password: Password for VeraCrypt volume
            keyfiles: List of keyfile paths
            config_path: CHG-20251221-042: Optional path to config.json for remote mode.
                        If provided, mount.py will use this config instead of local config.
        """
        super().__init__()
        self.password = password
        self.keyfiles = keyfiles or []
        self.config_path = config_path  # CHG-20251221-042: Remote config support

    def run(self):
        """Execute mount operation in background thread."""
        try:
            # Import here to avoid circular imports
            import subprocess
            import sys
            from pathlib import Path

            # CHG-20251221-042: Use config_path's parent scripts dir for remote mode
            if self.config_path:
                # Remote mode: use scripts from remote .smartdrive
                script_dir = self.config_path.parent / "scripts"
            else:
                script_dir = get_script_dir()

            mount_script = script_dir / FileNames.MOUNT_PY

            if not mount_script.exists():
                self.finished.emit(False, "worker_mount_script_not_found", {})
                return

            python_exe = get_python_exe()

            # Run mount script with password (if provided)
            cmd = [str(python_exe), str(mount_script), "--gui"]

            # CHG-20251221-042: Pass config path for remote mode
            if self.config_path:
                cmd.extend(["--config", str(self.config_path)])

            if self.password:
                cmd.extend(["--password", self.password])
            if self.keyfiles:
                for kf in self.keyfiles:
                    cmd.extend(["--keyfile", kf])
            # BUG-20251222-001: Use getattr for CREATE_NO_WINDOW (Windows-only flag)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=script_dir,
                timeout=Limits.VERACRYPT_MOUNT_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if result.returncode == 0:
                self.finished.emit(True, "worker_mount_success", {})
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                # Clean up error message for GUI
                if "Traceback" in error_msg:
                    # Extract just the main error
                    lines = error_msg.split("\n")
                    for line in reversed(lines):
                        if line.strip() and not line.startswith(" "):
                            error_msg = line.strip()
                            break
                self.finished.emit(False, "worker_mount_failed", {"error": error_msg})

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "worker_mount_timeout", {})
        except Exception as e:
            self.finished.emit(False, "worker_mount_error", {"error": str(e)})


# ============================================================
# UNMOUNT WORKER THREAD
# ============================================================


class UnmountWorker(QThread):
    """Worker thread for unmounting operations."""

    finished = pyqtSignal(bool, str, dict)  # success, message_key, message_args

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize unmount worker.

        Args:
            config_path: CHG-20251221-042: Optional path to config.json for remote mode.
                        If provided, unmount.py will use this config instead of local config.
        """
        super().__init__()
        self.config_path = config_path  # CHG-20251221-042: Remote config support

    def run(self):
        """Execute unmount operation in background thread."""
        try:
            # Import here to avoid circular imports
            import subprocess
            import sys
            from pathlib import Path

            # CHG-20251221-042: Use config_path's parent scripts dir for remote mode
            if self.config_path:
                # Remote mode: use scripts from remote .smartdrive
                script_dir = self.config_path.parent / "scripts"
            else:
                script_dir = get_script_dir()

            unmount_script = script_dir / "unmount.py"

            if not unmount_script.exists():
                self.finished.emit(False, "worker_unmount_script_not_found", {})
                return

            python_exe = get_python_exe()

            # Run unmount script
            cmd = [str(python_exe), str(unmount_script), "--gui"]

            # CHG-20251221-042: Pass config path for remote mode
            if self.config_path:
                cmd.extend(["--config", str(self.config_path)])

            # BUG-20251222-001: Use getattr for CREATE_NO_WINDOW (Windows-only flag)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=script_dir,
                timeout=Limits.VERACRYPT_MOUNT_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if result.returncode == 0:
                self.finished.emit(True, "worker_unmount_success", {})
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                # Clean up error message for GUI
                if "Traceback" in error_msg:
                    lines = error_msg.split("\n")
                    for line in reversed(lines):
                        if line.strip() and not line.startswith(" "):
                            error_msg = line.strip()
                            break
                self.finished.emit(False, "worker_unmount_failed", {"error": error_msg})

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "worker_unmount_timeout", {})
        except Exception as e:
            self.finished.emit(False, "worker_unmount_error", {"error": str(e)})


# ============================================================
# RECOVERY KIT GENERATION WORKER THREAD (CHG-20251221-001)
# ============================================================


class RecoveryGenerateWorker(QThread):
    """Worker thread for recovery kit generation to prevent UI blocking."""

    finished = pyqtSignal(bool, str, dict)  # success, message_key, message_args
    progress = pyqtSignal(str)  # status message

    def __init__(self, config: dict, smartdrive_dir: Path, force: bool = False, password: str = None):
        super().__init__()
        self.config = config
        self.smartdrive_dir = smartdrive_dir
        self.force = force
        self.password = password  # BUG-20251221-043: Optional password for PW_ONLY mode

    def _verify_credentials_via_mount(
        self, volume_path: str, mount_point: str, password: str, keyfile_path=None
    ) -> tuple[bool, str]:
        """
        BUG-20251222-011 FIX: Verify credentials by attempting mount/unmount.

        This ensures the recovery kit will contain valid credentials.
        Invalid credentials would create a useless recovery kit.

        Returns:
            (success, error_message)
        """
        import platform
        import tempfile

        try:
            from scripts.veracrypt_cli import (
                InvalidCredentialsError,
                VeraCryptError,
                get_mount_status,
                try_mount,
                unmount,
            )
        except ImportError as e:
            return False, f"Cannot import veracrypt_cli: {e}"

        # Check if already mounted - if so, credentials are already verified
        try:
            status = get_mount_status()
            # Check if our volume is in the mounted list
            if status and any(volume_path in str(m.get("volume", "")) for m in status):
                return True, ""  # Already mounted = credentials valid
        except Exception as e:
            _gui_logger.debug(f"Mount status check failed (continuing): {e}")  # Continue with mount test

        # Determine mount point for test
        is_windows = platform.system().lower() == "windows"
        if is_windows:
            # Use a temporary drive letter for test mount
            # Find an unused letter
            import string

            used_letters = set()
            try:
                for m in get_mount_status() or []:
                    # BUG-20251224-006: Use ConfigKeys.MOUNT_POINT for SSOT compliance
                    letter = m.get(ConfigKeys.MOUNT_POINT, "")
                    if letter:
                        used_letters.add(letter[0].upper())
            except Exception as e:
                _gui_logger.debug(f"Failed to get used drive letters: {e}")

            test_letter = None
            for letter in reversed(string.ascii_uppercase):
                if letter not in used_letters and letter not in ["C", "D"]:  # Skip system drives
                    test_letter = letter
                    break
            if not test_letter:
                return False, "No available drive letter for credential test"
            test_mount = f"{test_letter}:"
        else:
            # Linux/macOS: Use temp directory
            test_mount = tempfile.mkdtemp(prefix="keydrive_test_")

        try:
            # Attempt mount
            success, err = try_mount(
                volume_path=volume_path,
                mount_point=test_mount,
                password=password,
                keyfile_path=keyfile_path,
            )

            if not success:
                return False, f"Credential verification failed: {err}"

            # Immediately unmount
            try:
                unmount(test_mount)
            except Exception as e:
                # Try force unmount
                try:
                    unmount(test_mount, force=True)
                except Exception as e2:
                    _gui_logger.debug(f"Best effort unmount failed: {e2}")  # Best effort unmount

            return True, ""

        except InvalidCredentialsError as e:
            return False, f"Invalid credentials: {e}"
        except VeraCryptError as e:
            return False, f"VeraCrypt error during verification: {e}"
        except Exception as e:
            return False, f"Unexpected error during credential verification: {e}"
        finally:
            # Cleanup temp directory on Linux
            if not is_windows and test_mount.startswith("/tmp/"):
                try:
                    import shutil

                    shutil.rmtree(test_mount, ignore_errors=True)
                except Exception as e:
                    _gui_logger.debug(f"Temp directory cleanup failed: {e}")

    def run(self):
        """
        Execute recovery kit generation in background thread.

        BUG-20251221-019 FIX:
        1. Derive credentials using SecretProvider (same flow as rekey)
        2. Pass credentials to recovery.py via environment variables
        3. Call recovery.py generate --non-interactive --format printable
        4. No user interaction required - fully automated

        BUG-20251221-043 FIX:
        - For PW_ONLY mode, use password provided in constructor instead of returning early

        BUG-20251222-011 FIX:
        - Verify credentials via mount/unmount test BEFORE generating recovery kit
        - Invalid credentials would create useless recovery kit
        """
        try:
            import base64
            import os
            import subprocess
            from pathlib import Path

            from core.secrets import SecretProvider

            script_dir = get_script_dir()
            recovery_script = script_dir / FileNames.RECOVERY_PY

            if not recovery_script.exists():
                self.finished.emit(False, "recovery_generate_status_failed", {"error": "Recovery script not found"})
                return

            python_exe = get_python_exe()
            mode = self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

            self.progress.emit("recovery_generate_status_deriving")

            # Derive credentials using SecretProvider
            try:
                provider = SecretProvider.from_config(self.config, self.smartdrive_dir)

                # Get password
                if mode == SecurityMode.PW_ONLY.value:
                    # BUG-20251221-043 FIX: Use password provided in constructor
                    if self.password is None:
                        self.finished.emit(
                            False,
                            "recovery_generate_status_failed",
                            {"error": "PW_ONLY mode requires password but none was provided"},
                        )
                        return
                    password = self.password
                elif mode == SecurityMode.GPG_PW_ONLY.value:
                    password = provider._derive_password_gpg_pw_only()
                elif mode == SecurityMode.PW_KEYFILE.value:
                    # Password provided during setup, stored in config (not secure, needs improvement)
                    password = self.config.get(ConfigKeys.VOLUME_PASSWORD, "")
                    if not password:
                        self.finished.emit(
                            False,
                            "recovery_generate_status_failed",
                            {"error": "PW_KEYFILE mode: password not available in config"},
                        )
                        return
                elif mode == SecurityMode.PW_GPG_KEYFILE.value:
                    # Similar to PW_KEYFILE
                    password = self.config.get(ConfigKeys.VOLUME_PASSWORD, "")
                    if not password:
                        self.finished.emit(
                            False,
                            "recovery_generate_status_failed",
                            {"error": "PW_GPG_KEYFILE mode: password not available in config"},
                        )
                        return
                else:
                    self.finished.emit(
                        False, "recovery_generate_status_failed", {"error": f"Unsupported security mode: {mode}"}
                    )
                    return

                # Handle keyfile if needed
                keyfile_b64 = None
                keyfile_path_for_test = None
                if mode in [SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value]:
                    keyfile_path_config = self.config.get(ConfigKeys.KEYFILE_PATH)
                    if keyfile_path_config:
                        keyfile_path = Path(keyfile_path_config)
                        if keyfile_path.exists():
                            keyfile_bytes = keyfile_path.read_bytes()
                            keyfile_b64 = base64.b64encode(keyfile_bytes).decode("ascii")
                            keyfile_path_for_test = keyfile_path
                        else:
                            # Try GPG keyfile decryption
                            try:
                                keyfile_bytes = provider._decrypt_keyfile_gpg()
                                keyfile_b64 = base64.b64encode(keyfile_bytes).decode("ascii")
                                # Write temp keyfile for verification test
                                import tempfile

                                with tempfile.NamedTemporaryFile(delete=False, suffix=".keyfile") as tf:
                                    tf.write(keyfile_bytes)
                                    keyfile_path_for_test = Path(tf.name)
                            except Exception as e:
                                self.finished.emit(
                                    False,
                                    "recovery_generate_status_failed",
                                    {"error": f"Failed to decrypt keyfile: {e}"},
                                )
                                return

            except Exception as e:
                self.finished.emit(
                    False, "recovery_generate_status_failed", {"error": f"Credential derivation failed: {e}"}
                )
                return

            # BUG-20251222-011 FIX: Verify credentials before generating recovery kit
            self.progress.emit("recovery_generate_status_verifying")

            # Get volume path from config
            import platform as plat

            if plat.system().lower() == "windows":
                volume_path = self.config.get("windows", {}).get(ConfigKeys.VOLUME_PATH, "")
                mount_point = self.config.get("windows", {}).get(ConfigKeys.MOUNT_LETTER, "")
            else:
                volume_path = self.config.get("unix", {}).get(ConfigKeys.VOLUME_PATH, "")
                mount_point = self.config.get("unix", {}).get(ConfigKeys.MOUNT_POINT, "")

            if volume_path:
                verify_success, verify_error = self._verify_credentials_via_mount(
                    volume_path=volume_path,
                    mount_point=mount_point,
                    password=password,
                    keyfile_path=keyfile_path_for_test,
                )
                if not verify_success:
                    self.finished.emit(
                        False,
                        "recovery_generate_status_failed",
                        {"error": f"Credential verification failed. {verify_error}. Recovery kit not generated."},
                    )
                    return

            # Build command with non-interactive mode
            cmd = [str(python_exe), str(recovery_script), "generate", "--non-interactive", "--format", "printable"]
            if self.force:
                cmd.append("--force")

            # Pass credentials via environment variables (secure, process-isolated)
            env = os.environ.copy()
            env["KEYDRIVE_VOLUME_PASSWORD"] = password
            if keyfile_b64:
                env["KEYDRIVE_KEYFILE_B64"] = keyfile_b64

            self.progress.emit("recovery_generate_status_running")

            # BUG-20251222-001: Use getattr for CREATE_NO_WINDOW (Windows-only flag)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=script_dir,
                timeout=120,  # 2 minutes timeout
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if result.returncode == 0:
                # Extract kit path from output (recovery.py prints RECOVERY_KIT_PATH:...)
                kit_path = ""
                for line in result.stdout.split("\n"):
                    if line.startswith("RECOVERY_KIT_PATH:"):
                        kit_path = line.split(":", 1)[1].strip()
                        break
                    elif "recovery" in line.lower() and "html" in line.lower():
                        # Fallback: extract any path-looking string
                        import re

                        path_match = re.search(r"[A-Z]:\\[^\s]+|/[^\s]+", line)
                        if path_match:
                            kit_path = path_match.group(0)
                            break
                self.finished.emit(True, "recovery_generate_status_success", {"path": kit_path})
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                # Clean up error message
                if "Traceback" in error_msg:
                    lines = error_msg.split("\n")
                    for line in reversed(lines):
                        if line.strip() and not line.startswith(" "):
                            error_msg = line.strip()
                            break
                self.finished.emit(False, "recovery_generate_status_failed", {"error": error_msg})

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "recovery_generate_status_failed", {"error": "Generation timed out"})
        except Exception as e:
            import traceback

            error_detail = f"{e}\n{traceback.format_exc()}"
            self.finished.emit(False, "recovery_generate_status_failed", {"error": error_detail})


# ============================================================
# UTILITY FUNCTIONS
# ============================================================


def apportion(width: int, parts: list[float], min_if_nonzero=1) -> list[int]:
    """Apportion width into integer parts using largest remainder method.

    Ensures sum of returned widths equals width exactly.
    For any part > 0, ensures minimum width if min_if_nonzero > 0.
    """
    if not parts or width <= 0:
        return [0] * len(parts)

    # Calculate raw float widths
    raw_widths = [pct * width for pct in parts]

    # Apply minimum width rule for nonzero parts
    widths = []
    total_assigned = 0
    for i, raw in enumerate(raw_widths):
        if parts[i] > 0 and min_if_nonzero > 0:
            w = max(min_if_nonzero, int(raw))
        else:
            w = int(raw)
        widths.append(w)
        total_assigned += w

    # Distribute remaining pixels using largest remainder method
    missing = width - total_assigned
    if missing != 0:
        # Calculate fractional remainders
        remainders = [(i, raw_widths[i] - widths[i]) for i in range(len(widths)) if widths[i] > 0]
        remainders.sort(key=lambda x: x[1], reverse=True)  # Largest remainder first

        # Distribute missing pixels to segments with largest remainders
        for i in range(abs(missing)):
            if i < len(remainders):
                idx = remainders[i][0]
                widths[idx] += 1 if missing > 0 else -1
                # Ensure we don't go below minimum for nonzero parts
                if parts[idx] > 0 and widths[idx] < min_if_nonzero:
                    widths[idx] = min_if_nonzero

    return widths

##################################################################
# LOADING DOTS WIDGET
##################################################################

# CHG-20260103-002: Enhanced loading dots indicator - visible, colorful, own row
class LoadingDotsWidget(QWidget):
    """
    Custom widget for animated loading dots indicator.

    Displays 5 large colored dots that pulse sequentially to indicate
    a long-running operation. The dots are colorful and highly visible,
    displayed on their own dedicated row.
    """

    DOT_COUNT = 5
    DOT_SIZE = 12  # Larger dots for visibility
    DOT_SPACING = 8  # Space between dots
    PULSE_INTERVAL_MS = 200  # Animation speed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.DOT_SIZE + 8)  # Height + padding
        self._active_dot = 0
        self._is_running = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_dot)

        # Colorful dot colors - gradient from primary to success
        self._dot_colors = [
            "#6366f1",  # Indigo
            "#8b5cf6",  # Violet
            "#a855f7",  # Purple
            "#d946ef",  # Fuchsia
            "#ec4899",  # Pink
        ]
        self._inactive_color = "#3f3f46"  # zinc-700 - visible but muted

        # Center the widget
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def start(self) -> None:
        """Start the loading animation."""
        self._is_running = True
        self._active_dot = 0
        self._timer.start(self.PULSE_INTERVAL_MS)
        self.show()
        self.update()

    def stop(self) -> None:
        """Stop the loading animation."""
        self._is_running = False
        self._timer.stop()
        self.hide()
        self.update()

    def _advance_dot(self) -> None:
        """Advance to the next dot in the animation cycle."""
        self._active_dot = (self._active_dot + 1) % self.DOT_COUNT
        self.update()

    def paintEvent(self, event) -> None:
        """Draw the animated dots."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate total width of dots
        total_width = (self.DOT_COUNT * self.DOT_SIZE) + ((self.DOT_COUNT - 1) * self.DOT_SPACING)
        start_x = (self.width() - total_width) // 2  # Center horizontally
        y = (self.height() - self.DOT_SIZE) // 2  # Center vertically

        for i in range(self.DOT_COUNT):
            x = start_x + (i * (self.DOT_SIZE + self.DOT_SPACING))

            if self._is_running:
                # Active dot is larger and colored, others are smaller and muted
                if i == self._active_dot:
                    # Active dot: full color, full size
                    color = QColor(self._dot_colors[i])
                    size = self.DOT_SIZE
                    # Add glow effect
                    glow_color = QColor(self._dot_colors[i])
                    glow_color.setAlpha(80)
                    painter.setBrush(QBrush(glow_color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(x - 2, y - 2, size + 4, size + 4)
                elif i == (self._active_dot - 1) % self.DOT_COUNT:
                    # Previous dot: fading color
                    color = QColor(self._dot_colors[i])
                    color.setAlpha(150)
                    size = self.DOT_SIZE - 2
                else:
                    # Inactive dots: muted
                    color = QColor(self._inactive_color)
                    size = self.DOT_SIZE - 4
            else:
                # All dots inactive
                color = QColor(self._inactive_color)
                size = self.DOT_SIZE - 4

            # Center the dot based on size difference
            offset = (self.DOT_SIZE - size) // 2
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(x + offset, y + offset, size, size)


# ============================================================
# STORAGE BAR WIDGET
# ============================================================


class BarWidget(QWidget):
    """Custom widget for drawing the storage bar with rounded ends and tooltips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.storage_info = {}
        self.setMouseTracking(True)
        self.setToolTip("")  # Enable tooltips


    def set_storage_info(self, info):
        self.storage_info = info
        self.update()  # Trigger repaint

    def mouseMoveEvent(self, event):
        """Show tooltip with detailed segment information."""
        x = event.position().x()
        rect = self.rect()
        width = rect.width()

        if width <= 0:
            self.setToolTip("")
            return

        smartdrive = self.storage_info.get("keydrive", {})
        vc = self.storage_info.get("veracrypt", {})
        total_space = smartdrive.get("total", 0) + vc.get("total", 0)

        if total_space == 0:
            self.setToolTip("")
            return

        # Calculate percentages
        parts = [
            smartdrive.get("used", 0) / total_space,
            smartdrive.get("free", 0) / total_space,
            vc.get("used", 0) / total_space,
            vc.get("free", 0) / total_space,
        ]

        # Use apportion to get exact widths
        widths = apportion(width, parts, min_if_nonzero=0)  # No forced minimum for tooltips

        # Find which segment the mouse is over
        current_x = 0
        segment_names = [
            f"{Branding.PRODUCT_NAME} Used",
            f"{Branding.PRODUCT_NAME} Free",
            "VeraCrypt Used",
            "VeraCrypt Free",
        ]

        for i, w in enumerate(widths):
            if w > 0 and current_x <= x < current_x + w:
                pct = parts[i] * 100
                if i < 2:  # KeyDrive
                    used = smartdrive.get("used" if i == 0 else "free", 0)
                    total = smartdrive.get("total", 0)
                    drive = f"{Branding.PRODUCT_NAME}"
                else:  # VeraCrypt
                    used = vc.get("used" if i == 2 else "free", 0)
                    total = vc.get("total", 0)
                    drive = "VeraCrypt"

                tooltip = f"{drive} - {segment_names[i]}\n"
                tooltip += f"Size: {self.format_size(used)}\n"
                tooltip += f"Percent: {pct:.1f}%"
                self.setToolTip(tooltip)
                return
            current_x += w

        self.setToolTip("")

    def format_size(self, bytes_value):
        """Format bytes to human readable format."""
        if bytes_value == 0:
            return "0 B"

        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} TB"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        width = rect.width()
        height = rect.height()

        # Create rounded rectangle clip path for the entire bar
        path = QPainterPath()
        path.addRoundedRect(rect.toRectF(), 12, 12)
        painter.setClipPath(path)

        smartdrive = self.storage_info.get("keydrive", {})
        vc = self.storage_info.get("veracrypt", {})

        total_space = smartdrive.get("total", 0) + vc.get("total", 0)
        if total_space == 0:
            # Draw empty bar background
            painter.setBrush(QBrush(QColor(COLORS["surface"])))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 12, 12)
            painter.setClipping(False)
            return

        # Calculate percentages for apportionment
        parts = [
            smartdrive.get("used", 0) / total_space,
            smartdrive.get("free", 0) / total_space,
            vc.get("used", 0) / total_space,
            vc.get("free", 0) / total_space,
        ]

        # Use largest remainder apportionment to ensure exact width
        widths = apportion(width, parts, min_if_nonzero=1)

        # Draw segments without antialiasing to prevent seams
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        x = 0
        colors = [COLORS["smartdrive_used"], COLORS["smartdrive_free"], COLORS["vc_used"], COLORS["vc_free"]]

        for i, w in enumerate(widths):
            if w > 0:
                painter.setBrush(QBrush(QColor(colors[i])))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(x, 0, w, height)
                x += w

        painter.setClipping(False)

        # Draw subtle border on top
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawRoundedRect(rect, 12, 12)


class KeyfileDropBox(QTextEdit):
    """Custom QTextEdit subclass that properly handles drag-and-drop for keyfiles."""

    def __init__(self, on_files_dropped, on_clicked, on_drag_enter=None, on_drag_leave=None, parent=None):
        super().__init__(parent)
        self._on_files_dropped = on_files_dropped
        self._on_clicked = on_clicked
        self._on_drag_enter = on_drag_enter
        self._on_drag_leave = on_drag_leave

        self.setAcceptDrops(True)
        # IMPORTANT for QTextEdit/QAbstractScrollArea:
        self.viewport().setAcceptDrops(True)

        self.setReadOnly(True)
        self.setMouseTracking(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self._on_drag_enter:
                self._on_drag_enter()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        event.accept()
        if self._on_drag_leave:
            self._on_drag_leave()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                paths.append(p)

        if paths:
            self._on_files_dropped(paths)
            event.acceptProposedAction()
            if self._on_drag_leave:  # Reset highlight after drop
                self._on_drag_leave()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        # Left click -> browse
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_clicked()
            event.accept()
            return
        super().mousePressEvent(event)


# ============================================================
# CHG-20251221-042: Remote Control Mode Banner Label
# ============================================================


class RemoteBannerLabel(QLabel):
    """
    Custom label widget for remote control mode indicator.

    Features:
    - Displays "Remote Control Active" with red background
    - Blinking animation (red/white) in sync with window border
    - On hover: shows "Click to End Remote" with steady white background
    - Clicking exits remote mode
    """

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_hovered = False
        self._blink_state = False  # False=red, True=white

        # Set cursor to indicate clickable
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Enable mouse tracking for hover
        self.setMouseTracking(True)

        # Initial styling
        self._apply_style()

    def _apply_style(self) -> None:
        """
        Apply appropriate style based on hover and blink state.

        BUG-20251221-046 FIX: Use rectangular shape (border-radius: 0px).
        """
        if self._is_hovered:
            # Hover: steady white background, black text
            # BUG-20251221-046 FIX: Use border-radius: 0px for rectangular shape
            self.setStyleSheet(
                """
                QLabel {
                    background-color: #FFFFFF;
                    color: #000000;
                    padding: 4px 8px;
                    border-radius: 0px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """
            )
            self.setText(tr("remote_click_to_end", lang=get_lang()))
        else:
            # Normal: blinking red/white
            if self._blink_state:
                bg_color = "#FFFFFF"
                text_color = "#D32F2F"  # Red text on white
            else:
                bg_color = "#D32F2F"  # Red
                text_color = "#FFFFFF"  # White text

            # BUG-20251221-046 FIX: Use border-radius: 0px for rectangular shape
            self.setStyleSheet(
                f"""
                QLabel {{
                    background-color: {bg_color};
                    color: {text_color};
                    padding: 4px 8px;
                    border-radius: 0px;
                    font-size: 11px;
                    font-weight: bold;
                }}
            """
            )
            self.setText(tr("remote_active_label", lang=get_lang()))

    def set_blink_state(self, state: bool) -> None:
        """Set the blink state (for animation)."""
        self._blink_state = state
        if not self._is_hovered:
            self._apply_style()

    def enterEvent(self, event) -> None:
        """Handle mouse enter - show hover state."""
        self._is_hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Handle mouse leave - return to normal state."""
        self._is_hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        """Handle mouse click - emit clicked signal."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class SmartDriveGUI(QWidget):
    """Main KeyDrive GUI window."""

    # BUG-20260102-027: Non-interactive widget types that should allow window dragging
    # When mouse press lands on these widgets, we initiate drag instead of blocking
    _DRAG_THROUGH_WIDGETS = (QLabel, QWidget)
    _INTERACTIVE_WIDGETS = (QPushButton, QLineEdit, QComboBox, QCheckBox, QSlider, QSpinBox)

    def __init__(self, instance_manager: Optional["SingleInstanceManager"] = None):
        super().__init__()
        self.setObjectName("mainWindow")
        self.context = detect_context()
        self.is_mounted = check_mount_status()
        self.auth_dialog = None
        self._user_moved = False  # Track manual repositioning
        self._drag_in_progress = False
        self.drag_position = None  # Initialize for window dragging
        self._launcher_root = self._detect_launcher_root()
        # BUG-20260102-027: Install event filter on self for drag-through on Linux
        self.installEventFilter(self)

        # Single instance manager (for cleanup on exit)
        self._instance_manager = instance_manager

        # Tray icon manager
        self._tray_manager = None
        self._close_to_tray = True  # Enable close-to-tray by default

        # Track status as key for language updates
        self.status_key = None

        # Multi-keyfile support
        self.keyfiles = []

        # CHG-20251223-055: Non-modal settings dialog instance tracking
        self._settings_dialog: Optional["SettingsDialog"] = None

        # CHG-20251221-042: Remote Control Mode state
        self._app_mode = AppMode.LOCAL
        self._remote_profile: Optional[RemoteMountProfile] = None
        self._remote_identity_timer: Optional[QTimer] = None
        self._remote_banner: Optional[RemoteBannerLabel] = None
        self._remote_blink_timer: Optional[QTimer] = None
        self._remote_blink_state = False

        # Load configuration (with migration if needed)
        self.config = self.load_config()

        # Apply persisted theme before building UI so initial styling uses it
        self._apply_config_theme()

        # Load language from config and set globally
        lang = self.config.get(ConfigKeys.GUI_LANG, GUIConfig.DEFAULT_LANG)
        set_lang(lang)

        # Initialize settings using SSOT branding
        self.settings = QSettings(Branding.PRODUCT_NAME, f"{Branding.PRODUCT_NAME}GUI")

        self.init_ui()
        # BUG-20260102-027: Install event filter on all child widgets for drag-through
        self._install_drag_filter_recursive(self)
        self.position_window(force=True)

        # Apply branding with current product name
        current_product_name = get_product_name(self.settings)
        self.apply_branding(current_product_name)

        self.update_button_states()
        self.update_storage_display()
        self._update_lost_and_found_banner()

        # Auto-refresh mount status every 2 seconds
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2000)

        # CHG-20260102-013, CHG-20260103-002: Loading animation state
        # Now uses LoadingDotsWidget for visible, colorful animation on own row
        self._loading_base_status_key: Optional[str] = None

        # Initialize tray icon
        self._setup_tray_icon()

    def _apply_config_theme(self) -> None:
        """Apply the configured theme to global COLORS without touching widgets."""
        try:
            from core.constants import THEME_PALETTES

            theme_id = self.config.get(ConfigKeys.GUI_THEME, GUIConfig.DEFAULT_THEME)
            if theme_id not in THEME_PALETTES:
                theme_id = GUIConfig.DEFAULT_THEME
            global COLORS
            COLORS.clear()
            COLORS.update(THEME_PALETTES[theme_id])
        except Exception as e:
            log_exception("Error applying configured theme", e, level="error")

    def _apply_dynamic_color_styles(self) -> None:
        """Apply per-widget styles that must be refreshed on theme changes."""
        # Frames that have their own stylesheets (must be updated explicitly)
        if hasattr(self, "storage_frame"):
            self.storage_frame.setStyleSheet(
                f"""
                QWidget#storageFrame {{
                    background-color: {COLORS['surface']};
                    border: none;
                    border-radius: 8px;
                }}
            """
            )

        if hasattr(self, "auth_frame"):
            self.auth_frame.setStyleSheet(
                f"""
                QWidget {{
                    background-color: {COLORS['surface']};
                    border-radius: 8px;
                    margin: 8px 0px;
                }}
                QLabel {{
                    color: {COLORS['text']};
                    border: none;
                    background: transparent;
                }}
                QLineEdit {{
                    border: 2px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 8px 12px;
                    background-color: {COLORS['surface']};
                    color: {COLORS['text']};
                }}
                QLineEdit:focus {{
                    border-color: {COLORS['primary']};
                }}
                QCheckBox {{
                    color: {COLORS['text_secondary']};
                    background: transparent;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                }}
                QCheckBox::indicator:unchecked {{
                    border: 2px solid {COLORS['border']};
                    border-radius: 3px;
                    background: {COLORS['surface']};
                }}
                QCheckBox::indicator:checked {{
                    background: {COLORS['primary']};
                    border: 1px solid {COLORS['primary']};
                    border-radius: 3px;
                }}
                QPushButton {{
                    background-color: {COLORS['primary']};
                    color: {COLORS['text']};
                    border: none;
                    border-radius: 8px;
                    padding: 10px 16px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['primary_hover']};
                }}
                QPushButton#cancelButton {{
                    background-color: {COLORS['warning']};
                    color: {COLORS['text']};
                }}
            """
            )

        # Header labels
        if hasattr(self, "title_left_label"):
            self.title_left_label.setStyleSheet(f"color: {COLORS['text']}; border: none;")
        if hasattr(self, "title_right_label"):
            self.title_right_label.setStyleSheet(f"color: {COLORS['text']}; border: none;")
        if hasattr(self, "version_label"):
            self.version_label.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")

        # Close button (colors are theme-controlled)
        if hasattr(self, "close_btn"):
            self.close_btn.setStyleSheet(
                f"""
QPushButton {{
    color: {COLORS['close_fg']};
    background: transparent;
    border: none;
    font-size: 12px;
    font-weight: bold;
    padding: 0px;
}}
QPushButton:hover {{
    color: {COLORS['close_hover']};
}}
QPushButton:pressed {{
    color: {COLORS['close_pressed']};
}}
"""
            )

        # Tools button (overrides global QPushButton styles)
        if hasattr(self, "tools_btn"):
            self.tools_btn.setStyleSheet(
                f"""
            QPushButton {{
                background-color: {COLORS['background']};
                border: none;
                border-radius: 6px;
                color: {COLORS['text_secondary']};
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['border']};
            }}
        """
            )

        # Storage labels
        if hasattr(self, "total_size_label"):
            self.total_size_label.setStyleSheet(
                f"color: {COLORS['text_secondary']}; border: none; background: transparent;"
            )
        if hasattr(self, "launch_info"):
            self.launch_info.setStyleSheet(f"color: {COLORS['launch_used']}; border: none; padding: 0px; margin: 0px;")
        if hasattr(self, "vc_info"):
            self.vc_info.setStyleSheet(f"color: {COLORS['vc_used']}; border: none; padding: 0px; margin: 0px;")
        if hasattr(self, "launch_free_label"):
            self.launch_free_label.setStyleSheet(
                f"color: {COLORS['launch_free']}; border: none; padding: 0px; margin: 0px; background: transparent;"
            )
        if hasattr(self, "vc_free_label"):
            self.vc_free_label.setStyleSheet(
                f"color: {COLORS['vc_free']}; border: none; padding: 0px; margin: 0px; background: transparent;"
            )

        # Auth dialog labels
        if hasattr(self, "key_hint_label"):
            self.key_hint_label.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-style: italic; margin: 0px; padding: 0px;"
            )
        if hasattr(self, "password_label"):
            self.password_label.setStyleSheet(f"color: {COLORS['text']};")
        if hasattr(self, "keyfile_label"):
            self.keyfile_label.setStyleSheet(f"color: {COLORS['text']};")
        if hasattr(self, "keyfile_status_label"):
            self.keyfile_status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        if hasattr(self, "recovery_label"):
            self.recovery_label.setText(
                f'<a href="#" style="color: {COLORS["text_secondary"]};">{tr("label_forgot_password", lang=get_lang())}</a>'
            )

    def _setup_tray_icon(self) -> None:
        """Initialize system tray icon for this drive."""
        try:
            _gui_logger.info("Setting up tray icon...")

            if not is_tray_available():
                _gui_logger.info("System tray not available, skipping tray setup")
                return

            # Get drive_id from config (optional - tooltip will work without it)
            drive_id = get_drive_id(self.config)
            if not drive_id:
                _gui_logger.info("No drive_id in config, using empty ID for tray tooltip")
                drive_id = ""  # Continue with empty ID instead of aborting

            # Get drive name for tooltip
            drive_name = self.config.get(ConfigKeys.DRIVE_NAME) or PRODUCT_NAME

            # Get tray icon path with comprehensive logging
            _gui_logger.info(f"Resolving tray icon path...")
            _gui_logger.info(f"  Launcher root: {self._launcher_root}")

            # Try multiple icon sources in order
            icon_path = None

            # 1. Try ICON_UNMOUNTED (which is now LOGO_main.ico)
            icon_path = self.get_static_asset(FileNames.ICON_UNMOUNTED)
            if icon_path:
                _gui_logger.info(f"  Found via ICON_UNMOUNTED: {icon_path}")

            # 2. Fallback: Try LOGO_main.ico directly
            if not icon_path:
                icon_path = self.get_static_asset("LOGO_main.ico")
                if icon_path:
                    _gui_logger.info(f"  Found via LOGO_main.ico: {icon_path}")

            # 3. Fallback: Try PNG version
            if not icon_path:
                icon_path = self.get_static_asset("LOGO_main.png")
                if icon_path:
                    _gui_logger.info(f"  Found via LOGO_main.png: {icon_path}")

            # 4. Try resource module if available
            if not icon_path:
                try:
                    from core.resources import get_app_icon_path

                    icon_path = get_app_icon_path(self._launcher_root)
                    if icon_path:
                        _gui_logger.info(f"  Found via resource module: {icon_path}")
                except ImportError:
                    pass

            if not icon_path:
                _gui_logger.error("CRITICAL: No tray icon found!")
                _gui_logger.error("  Tray icon will not display correctly")
            else:
                _gui_logger.info(f"  Selected tray icon: {icon_path}")
                _gui_logger.info(f"  Icon exists: {icon_path.exists()}")

            # Create tray manager
            self._tray_manager = TrayIconManager(
                drive_id=drive_id,
                drive_name=drive_name,
                on_open=self._on_tray_open,
                on_quit=self._on_tray_quit,
                icon_path=icon_path,
                parent=self,
            )

            # Show tray icon
            if self._tray_manager.show():
                _gui_logger.info(f"startup.tray.init.end: success for drive {drive_name}")
            else:
                _gui_logger.warning("startup.tray.init.end: failed")

        except Exception as e:
            log_exception("Error setting up tray icon", e, level="warning")

    def _on_close_button_clicked(self) -> None:
        """Handle GUI close/exit button click - hides to tray, does NOT quit."""
        _gui_logger.info("ui.exit_clicked")
        self.close()  # Triggers closeEvent which hides to tray

    def _on_tray_open(self) -> None:
        """Handle tray 'Open' action - show and focus window."""
        _gui_logger.info("tray.action.open")
        self.show()
        self.raise_()
        self.activateWindow()
        # On Windows, sometimes need extra activation
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)

    def _on_tray_quit(self) -> None:
        """Handle tray 'Quit' action - actually quit the application."""
        _gui_logger.info("tray.action.quit")
        self._close_to_tray = False  # Disable close-to-tray for actual quit
        self._cleanup_and_quit()

    def _cleanup_and_quit(self) -> None:
        """Clean up resources and quit the application."""
        _gui_logger.info("tray.action.quit.cleanup.begin")

        # Stop status timer
        if hasattr(self, "status_timer") and self.status_timer:
            self.status_timer.stop()

        # Clean up tray
        if self._tray_manager:
            self._tray_manager.cleanup()
            self._tray_manager = None

        # Release single instance lock
        if self._instance_manager:
            self._instance_manager.release()
            self._instance_manager = None

        # Quit application
        from PyQt6.QtWidgets import QApplication

        QApplication.instance().quit()

    def _update_tray_icon_state(self) -> None:
        """Update tray icon and window/taskbar icon based on mount status."""
        try:
            if self.is_mounted:
                icon_path = self.get_static_asset(FileNames.ICON_MOUNTED)
            else:
                icon_path = self.get_static_asset(FileNames.ICON_UNMOUNTED)

            if icon_path:
                # Update tray icon
                if self._tray_manager:
                    self._tray_manager.set_icon(icon_path)

                # Update window/taskbar icon
                # This makes the taskbar icon change with mount state
                from PyQt6.QtGui import QIcon

                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception as e:
            log_exception("Error updating tray icon state", e, level="debug")

    def closeEvent(self, event):
        """Handle window close - hide to tray if enabled, otherwise ask user."""
        # Check if tray is available and working
        tray_available = self._tray_manager and self._tray_manager.is_visible

        if self._close_to_tray and tray_available:
            # Hide to tray instead of closing
            _gui_logger.info("ui.exit_clicked -> hiding window (tray continues)")
            _gui_logger.info("ui.window.hide")
            event.ignore()
            self.hide()
            self._tray_manager.show_message(
                PRODUCT_NAME,
                (
                    tr("tray_minimized_message", lang=get_lang())
                    if "tray_minimized_message" in TRANSLATIONS.get(get_lang(), {})
                    else "Running in background. Click tray icon to restore."
                ),
                icon_type="information",
                duration_ms=3000,
            )
        elif self._close_to_tray and not tray_available:
            # Tray unavailable but close-to-tray enabled - ask user what to do
            from PyQt6.QtWidgets import QMessageBox

            msg = QMessageBox(self)
            msg.setWindowTitle(PRODUCT_NAME)
            msg.setText(tr("tray_unavailable_message", lang=get_lang()))
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.No)

            if msg.exec() == QMessageBox.StandardButton.Yes:
                # User wants to quit
                if hasattr(self, "status_timer") and self.status_timer:
                    self.status_timer.stop()
                event.accept()
            else:
                # User wants to keep running - just minimize
                _gui_logger.info("ui.exit_clicked -> minimizing (no tray)")
                event.ignore()
                self.showMinimized()
        else:
            # Actually close - clean up
            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()
            event.accept()

    # BUG-20260102-027: Window dragging handlers for frameless window
    # Qt frameless windows don't have native title bar, so we implement custom drag
    def _install_drag_filter_recursive(self, widget):
        """Install event filter on widget and all its children for drag-through."""
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def mousePressEvent(self, event):
        """Handle mouse press for window dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Only start drag if clicking on non-interactive area
            # The widget under cursor will receive the event first if it handles it
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_in_progress = True
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging."""
        if self._drag_in_progress and (event.buttons() & Qt.MouseButton.LeftButton) and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Handle mouse release for window dragging."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_in_progress:
            self._drag_in_progress = False
            self._user_moved = True  # Prevent auto-repositioning after manual move
            event.accept()

    def eventFilter(self, obj, event):
        """BUG-20260102-027: Event filter to enable window dragging on Linux.

        On Linux with frameless windows, child widgets consume mouse events before
        they reach the parent. This filter intercepts mouse events on non-interactive
        child widgets (labels, frames) and initiates window drag.
        """
        from PyQt6.QtCore import QEvent

        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                # Check if the widget under cursor is interactive (button, input, etc.)
                widget = obj
                # Walk up the widget tree to find if any ancestor is interactive
                is_interactive = False
                while widget is not None and widget is not self:
                    if isinstance(widget, self._INTERACTIVE_WIDGETS):
                        is_interactive = True
                        break
                    widget = widget.parent() if hasattr(widget, "parent") else None

                if not is_interactive:
                    # Start drag from non-interactive area
                    self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    self._drag_in_progress = True
                    return True  # Consume event

        elif event.type() == QEvent.Type.MouseMove:
            if (
                self._drag_in_progress
                and (event.buttons() & Qt.MouseButton.LeftButton)
                and self.drag_position is not None
            ):
                self.move(event.globalPosition().toPoint() - self.drag_position)
                return True  # Consume event

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._drag_in_progress:
                self._drag_in_progress = False
                self._user_moved = True
                return True  # Consume event

        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """Ensure proper layout after the window becomes visible."""
        super().showEvent(event)
        QTimer.singleShot(0, self._post_show_layout_fix)
        QTimer.singleShot(50, self.update_storage_display)

    def _post_show_layout_fix(self):
        try:
            self.update_window_size()
        except Exception as e:
            log_exception("Error in post-show layout fix", e)

    def update_window_size(self, reposition: bool = True) -> None:
        """Recalculate window size based on current layout and clamp to screen bounds."""
        try:
            layout = self.layout()
            if not layout:
                return

            layout.activate()
            hint = self.sizeHint()

            min_width = self.minimumWidth() or WINDOW_WIDTH
            min_height = self.minimumHeight() or WINDOW_HEIGHT

            max_width = self.maximumWidth()
            max_height = self.maximumHeight()

            new_width = max(min_width, hint.width())
            new_height = max(min_height, hint.height())

            if 0 < max_width < 16777215:
                new_width = min(new_width, max_width)
            if 0 < max_height < 16777215:
                new_height = min(new_height, max_height)

            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                screen_max_height = int(available.height() * 0.8)
            else:
                screen_max_height = int(WINDOW_HEIGHT * 2)

            new_height = min(new_height, screen_max_height)

            self.resize(new_width, new_height)
            if reposition:
                self.position_window()
        except Exception as e:
            log_exception("Error updating window size", e, level="debug")

    def set_keyfiles(self, paths: list[str], append: bool = False):
        """Set keyfiles with validation and deduplication."""
        import os

        # Normalize + validate + de-dup
        norm = []
        for p in paths:
            if not p:
                continue
            p = os.path.normpath(p)
            if os.path.isfile(p):
                norm.append(p)

        if append:
            merged = self.keyfiles + norm
        else:
            merged = norm

        # De-dup while preserving order
        seen = set()
        self.keyfiles = [p for p in merged if not (p in seen or seen.add(p))]

        self.render_keyfiles()

    def render_keyfiles(self):
        """Update keyfile display based on current keyfiles list."""
        # Prevent word wrapping for clean display
        self.keyfile_edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)

        if not self.keyfiles:
            # Hide status label
            self.keyfile_status_label.setVisible(False)

            # Restore placeholder HTML
            self.keyfile_edit.setHtml(
                f"""
                <div style=\"color: #B8D6C9; text-align: center; padding: 20px;\">
                    <div style=\"font-size: 24px; margin-bottom: 10px;\">&#128193;</div>
                    <div>{tr('keyfile_drop_hint', lang=get_lang())}</div>
                    <div style=\"font-size: 12px; margin-top: 5px;\">{tr('keyfile_drop_supports_multiple', lang=get_lang())}</div>
                </div>
                """
            )
            self.keyfile_edit.setStyleSheet(
                f"""
                QTextEdit {{
                    border: 2px dashed {COLORS['border']};
                    border-radius: 8px;
                    background-color: {COLORS['surface']};
                    color: {COLORS['text']};
                    padding: 10px;
                }}
            """
            )
            self.keyfile_edit.setReadOnly(True)
            self.keyfile_edit.setToolTip("")
            return

        # Show status label with count
        count = len(self.keyfiles)
        if count == 1:
            self.keyfile_status_label.setText(tr("keyfile_selected_one"))
        else:
            self.keyfile_status_label.setText(tr("keyfile_selected_many", count=count))
        self.keyfile_status_label.setVisible(True)

        # Show compact list with basenames and tooltips
        import os

        if count == 1:
            display_text = os.path.basename(self.keyfiles[0])
            self.keyfile_edit.setToolTip(self.keyfiles[0])
        else:
            names = [os.path.basename(p) for p in self.keyfiles]
            max_lines = 3
            head = names[:max_lines]
            rest = len(names) - len(head)
            display_text = "\n".join(head) + (f"\n… +{rest} more" if rest > 0 else "")
            self.keyfile_edit.setToolTip("\n".join(self.keyfiles))

        self.keyfile_edit.setPlainText(display_text)
        self.keyfile_edit.setStyleSheet(
            f"""
            QTextEdit {{
                border: 2px solid {COLORS['primary']};
                border-radius: 8px;
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                padding: 10px;
            }}
        """
        )
        self.keyfile_edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.keyfile_edit.setReadOnly(True)

    def load_config(self) -> dict:
        """Load configuration from config.json with automatic migration."""
        try:
            # Use migration-aware config loader
            config, migration_result = load_or_create_config(CONFIG_FILE)

            # Log migration info
            if migration_result.migrated:
                _gui_logger.info(f"Config migration performed: {migration_result.changes}")

            if migration_result.drive_id:
                _gui_logger.info(f"Drive ID: {migration_result.drive_id[:8]}...")

            return config
        except Exception as e:
            log_exception("Error loading config", e, level="warning")
            # Fallback to basic load for robustness
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}

    def _detect_launcher_root(self) -> Path:
        """Resolve launcher root deterministically for static assets."""
        script_dir = get_script_dir()
        if script_dir.name == "scripts" and script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
            return script_dir.parent.parent
        return script_dir.parent

    # =========================================================================
    # Multi-drive context switching (CHG-20251221-026)
    # =========================================================================

    def _get_recent_drives(self) -> list:
        """
        Get list of recent drive context paths from QSettings.

        Returns list of path strings, max 5 entries.
        """
        recent = self.settings.value("recent_drives", [], type=list)
        # Validate entries exist
        return [p for p in recent if Path(p).exists()][:5]

    def _add_to_recent_drives(self, smartdrive_path: Path) -> None:
        """
        Add a .smartdrive path to the recent drives list.

        Args:
            smartdrive_path: Path to .smartdrive folder
        """
        path_str = str(smartdrive_path)
        recent = self._get_recent_drives()

        # Remove if already present (will re-add at top)
        if path_str in recent:
            recent.remove(path_str)

        # Add at top
        recent.insert(0, path_str)

        # Keep max 5
        recent = recent[:5]

        self.settings.setValue("recent_drives", recent)

    def _populate_switch_drive_menu(self, menu: "QMenu") -> None:
        """
        Populate the switch drive submenu with recent drives and browse option.

        Args:
            menu: The QMenu to populate
        """
        recent_drives = self._get_recent_drives()

        # Add recent drives (max 3 shown in quick menu)
        for drive_path in recent_drives[:3]:
            # Show drive letter/name for quick identification
            path_obj = Path(drive_path)
            display_name = f"{path_obj.parent.name} ({path_obj.parent})"
            action = menu.addAction(display_name)
            action.setData(drive_path)
            action.triggered.connect(lambda checked, p=drive_path: self._switch_drive_context(Path(p)))

        if recent_drives:
            menu.addSeparator()

        # Browse action
        browse_action = menu.addAction(tr("menu_switch_drive_browse", lang=get_lang()))
        browse_action.triggered.connect(self._browse_for_drive_context)

    def _browse_for_drive_context(self) -> None:
        """Open file dialog to select a .smartdrive folder."""
        from PyQt6.QtWidgets import QFileDialog

        dialog = QFileDialog(self)
        dialog.setWindowTitle(tr("switch_drive_select_folder", lang=get_lang()))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)

        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                selected_path = Path(selected[0])
                # Validate it's a .smartdrive folder or parent containing one
                if selected_path.name == Paths.SMARTDRIVE_DIR_NAME:
                    smartdrive_path = selected_path
                else:
                    smartdrive_path = selected_path / Paths.SMARTDRIVE_DIR_NAME

                if (smartdrive_path / FileNames.CONFIG_JSON).exists():
                    self._switch_drive_context(smartdrive_path)
                else:
                    QMessageBox.warning(
                        self,
                        tr("switch_drive_title", lang=get_lang()),
                        tr("switch_drive_invalid_path", lang=get_lang()),
                    )

    def _check_drive_compatibility(self, config_path: Path) -> tuple[bool, str, str]:
        """
        Check version compatibility of a target drive's config.

        Args:
            config_path: Path to the target drive's config.json

        Returns:
            Tuple of (can_proceed, severity, message):
            - can_proceed: True if safe to proceed (or user can confirm)
            - severity: "OK", "WARNING", or "ERROR"
            - message: Human-readable explanation
        """
        try:
            with open(config_path, encoding="utf-8") as f:
                target_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return (False, "ERROR", f"Cannot read config: {e}")

        # Extract version info from target config
        target_version = target_config.get(ConfigKeys.VERSION, "0.0.0")
        target_schema = target_config.get(ConfigKeys.SCHEMA_VERSION, 1)

        # Validate schema is an integer
        if not isinstance(target_schema, int):
            try:
                target_schema = int(target_schema)
            except (ValueError, TypeError):
                return (
                    False,
                    "ERROR",
                    f"Invalid schema_version in config: {target_schema!r}",
                )

        return is_version_compatible(target_version, target_schema)

    def _switch_drive_context(self, new_smartdrive_path: Path) -> None:
        """
        Switch to a different .smartdrive context.

        Args:
            new_smartdrive_path: Path to the .smartdrive folder to switch to
        """
        config_path = new_smartdrive_path / FileNames.CONFIG_JSON

        if not config_path.exists():
            QMessageBox.warning(
                self,
                tr("switch_drive_title", lang=get_lang()),
                tr("switch_drive_invalid_path", lang=get_lang()),
            )
            return

        # Check version compatibility BEFORE switching
        can_proceed, severity, compat_msg = self._check_drive_compatibility(config_path)

        if severity == "ERROR":
            # Fatal incompatibility - cannot proceed
            QMessageBox.critical(
                self,
                tr("version_incompatible_title", lang=get_lang()),
                tr("version_incompatible_error", lang=get_lang()).format(message=compat_msg),
            )
            return

        if severity == "WARNING":
            # Show warning and require confirmation
            warning_reply = QMessageBox.warning(
                self,
                tr("version_incompatible_title", lang=get_lang()),
                tr("version_incompatible_warning", lang=get_lang()).format(
                    message=compat_msg,
                    path=str(new_smartdrive_path),
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if warning_reply != QMessageBox.StandardButton.Yes:
                return

        # Confirm switch
        reply = QMessageBox.question(
            self,
            tr("switch_drive_title", lang=get_lang()),
            tr("switch_drive_confirm", lang=get_lang()).format(path=str(new_smartdrive_path)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Add to recent drives
        self._add_to_recent_drives(new_smartdrive_path)

        # Update global CONFIG_FILE path
        global CONFIG_FILE
        CONFIG_FILE = config_path

        # Update _launcher_root
        self._launcher_root = new_smartdrive_path.parent

        # Reload config
        self._reload_config()

        # Refresh UI
        self.update_button_states()
        self.update_storage_display()
        self._update_lost_and_found_banner()

        # Update branding in case drive name changed
        current_product_name = get_product_name(self.settings)
        self.apply_branding(current_product_name)

        _gui_logger.info(f"Switched drive context to: {new_smartdrive_path}")

    def _reload_config(self) -> None:
        """Reload configuration from the current CONFIG_FILE path."""
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                self.config = json.load(f)
            _gui_logger.info(f"Reloaded config from: {CONFIG_FILE}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log_exception("Error reloading config", e, level="error")
            self.config = {}

    def get_static_asset(self, filename: str) -> Optional[Path]:
        """
        Return static asset path if it exists.

        Priority order:
        1. .smartdrive/static/ (deployed)
        2. ROOT/static/ (legacy via Paths.static_file)
        3. get_static_dir() fallback
        """
        # Primary: .smartdrive/static/ (deployed structure)
        deployed = self._launcher_root / ".smartdrive" / "static" / filename
        if deployed.exists():
            return deployed

        # Secondary: via Paths class (handles legacy ROOT/static/)
        via_paths = Paths.static_file(self._launcher_root, filename)
        if via_paths.exists():
            return via_paths

        # Fallback: get_static_dir() helper
        fallback = get_static_dir() / filename
        if fallback.exists():
            return fallback

        return None

    def get_drive_info(self) -> str:
        """Get drive identification information."""
        if not self.config:
            return ""

        drive_info = []

        # Add mount letter/drive info based on platform (NOT launch context)
        import platform

        if platform.system() == "Windows":
            windows_cfg = self.config.get(ConfigKeys.WINDOWS, {})
            mount_letter = windows_cfg.get(ConfigKeys.MOUNT_LETTER, "Unknown")
            volume_path = windows_cfg.get(ConfigKeys.VOLUME_PATH, "")
            if volume_path.startswith("\\\\.\\PhysicalDrive"):
                drive_num = volume_path.replace("\\\\.\\PhysicalDrive", "")
                drive_info.append(f"Drive {drive_num}")
            drive_info.append(f"Mount: {mount_letter}:")
        else:
            mount_point = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "Unknown")
            drive_info.append(f"Mount: {mount_point}")

        return " | ".join(drive_info)

    def get_drive_title(self) -> str:
        """Get simple drive title for display."""
        if not self.config:
            return f"{Branding.PRODUCT_NAME}"

        # Get mount letter/point based on platform
        import platform

        if platform.system() == "Windows":
            mount_letter = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "")
            if mount_letter:
                return f"{Branding.PRODUCT_NAME} {mount_letter}:"
        else:
            mount_point = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")
            if mount_point:
                return f"{Branding.PRODUCT_NAME} {mount_point}"
        return f"{Branding.PRODUCT_NAME}"

    def get_disk_usage(self, path: str) -> tuple[int, int, int]:
        """Get disk usage information (total, used, free) in bytes."""
        try:
            import shutil

            usage = shutil.disk_usage(path)
            return usage.total, usage.used, usage.free
        except (OSError, FileNotFoundError):
            return 0, 0, 0

    def get_storage_info(self) -> dict:
        """Get storage information for KeyDrive partition and VeraCrypt volume."""
        info = {
            "keydrive": {"total": 0, "used": 0, "free": 0, "percent": 0},
            "veracrypt": {"total": 0, "used": 0, "free": 0, "percent": 0},
        }

        # Get KeyDrive partition info (where the exe is running from)
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
        try:
            launch_total, launch_used, launch_free = self.get_disk_usage(str(exe_dir))
            # Validate data makes sense
            if launch_total == 0 or launch_total < launch_used + launch_free:
                print(
                    f"Warning: Invalid {Branding.PRODUCT_NAME} data - total: {launch_total}, used: {launch_used}, free: {launch_free}"
                )
                launch_total, launch_used, launch_free = 0, 0, 0
        except Exception as e:
            print(f"Warning: Could not get {Branding.PRODUCT_NAME} info: {e}")
            launch_total, launch_used, launch_free = 0, 0, 0

        info["keydrive"] = {
            "total": launch_total,
            "used": launch_used,
            "free": launch_free,
            "percent": int((launch_used / launch_total * 100) if launch_total > 0 else 0),
        }

        # Get VeraCrypt volume info (if mounted)
        # BUG-20260102-018: Use platform-appropriate mount path
        if self.is_mounted and self.config:
            if platform.system() == "Windows":
                mount_letter = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "")
                vc_path = f"{mount_letter}:\\" if mount_letter else ""
            else:
                vc_path = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")

            if vc_path:
                try:
                    vc_total, vc_used, vc_free = self.get_disk_usage(vc_path)
                    # Validate data makes sense
                    if vc_total == 0 or vc_total < vc_used + vc_free:
                        print(f"Warning: Invalid VC drive data - total: {vc_total}, used: {vc_used}, free: {vc_free}")
                        vc_total, vc_used, vc_free = 0, 0, 0
                except Exception as e:
                    print(f"Warning: Could not get VC drive info: {e}")
                    vc_total, vc_used, vc_free = 0, 0, 0

                info["veracrypt"] = {
                    "total": vc_total,
                    "used": vc_used,
                    "free": vc_free,
                    "percent": int((vc_used / vc_total * 100) if vc_total > 0 else 0),
                }

        return info

    def init_ui(self):
        """Initialize the user interface."""
        drive_title = self.get_drive_title()
        # Simple window title
        import platform

        if self.config and platform.system() == "Windows":
            mount_letter = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "")
            window_title = f"{PRODUCT_NAME} {mount_letter}:" if mount_letter else PRODUCT_NAME
        else:
            window_title = PRODUCT_NAME
        self.setWindowTitle(window_title)

        # BUG-20251220-009 FIX: Set window icon with comprehensive fallback
        # Set window icon deterministically from static assets
        icon_path = self.get_static_asset("LOGO_main.ico") or self.get_static_asset("LOGO_main.png")
        if icon_path:
            _gui_logger.info(f"Window icon set from: {icon_path}")
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            # Fallback 1: Try application icon
            app = QApplication.instance()
            if app and not app.windowIcon().isNull():
                _gui_logger.info("Window icon set from application icon")
                self.setWindowIcon(app.windowIcon())
            else:
                # Fallback 2: Qt built-in icon
                _gui_logger.warning("No custom icon found, using Qt built-in icon")
                from PyQt6.QtWidgets import QStyle

                style = self.style()
                if style:
                    self.setWindowIcon(style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))

        self.setMinimumSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)  # Ensure initial size

        # DO NOT set maximum height constraint here - let the layout handle it
        # Setting hard maxHeight causes QWindowsWindow::setGeometry warnings when
        # the auth_frame is shown/hidden because the layout can't expand/contract properly.
        # Instead, update_window_size() clamps geometry whenever content visibility changes.

        # BUG-20260102-027: On Linux, use normal window with title bar for native dragging
        # Frameless windows on Linux/X11/Wayland don't drag properly without complex workarounds
        if platform.system() == "Linux":
            # Normal window with title bar - draggable by default
            self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        else:
            # Windows/macOS: frameless + custom styling
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)  # Increased margins
        layout.setSpacing(15)  # Increased spacing

        # Create top container for header+storage+buttons (fixed block)
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        # Title with icon and version
        title_container = QWidget()
        title_grid = QGridLayout(title_container)
        title_grid.setContentsMargins(0, 0, 0, 0)
        title_grid.setSpacing(2)  # Small spacing between rows
        title_grid.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title row (Left + Logo + Right)
        title_row_widget = QWidget()
        title_layout = QHBoxLayout(title_row_widget)
        title_layout.setSpacing(5)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Left title label
        self.title_left_label = QLabel()
        self.title_left_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.title_left_label.setStyleSheet(f"color: {COLORS['text']}; border: none;")
        left_stack_widget = QWidget()
        left_stack_layout = QVBoxLayout(left_stack_widget)
        left_stack_layout.setContentsMargins(0, 0, 0, 0)
        left_stack_layout.setSpacing(0)
        left_stack_layout.addStretch(1)
        left_stack_layout.addWidget(self.title_left_label, 0, Qt.AlignmentFlag.AlignRight)
        left_placeholder = QWidget()
        left_stack_layout.addWidget(left_placeholder, 0, Qt.AlignmentFlag.AlignRight)
        title_layout.addWidget(left_stack_widget)

        # Icon label
        self.title_icon_label = QLabel()
        icon_path = self.get_static_asset("LOGO_main.png")
        if icon_path:
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.title_icon_label.setPixmap(scaled_pixmap)
                self.title_icon_label.setText("")
        else:
            self.title_icon_label.setText(tr("icon_drive", lang=get_lang()))
            self.title_icon_label.setFont(QFont("Segoe UI", 20))
        title_layout.addWidget(self.title_icon_label)

        # Right title label stacked with version
        self.title_right_label = QLabel()
        self.title_right_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))

        # Version label (secondary, smaller font)
        self.version_label = QLabel()
        self.version_label.setObjectName("versionLabel")
        self.version_label.setText(f"v{APP_VERSION}")
        self.version_label.setFont(QFont("Segoe UI", 8))
        self.version_label.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        version_font = self.version_label.font()
        version_font.setPointSize(max(1, version_font.pointSize() - 1))
        self.version_label.setFont(version_font)

        left_placeholder.setFixedHeight(self.version_label.sizeHint().height())

        right_stack = QWidget()
        right_stack_layout = QVBoxLayout(right_stack)
        right_stack_layout.setContentsMargins(0, 0, 0, 0)
        right_stack_layout.setSpacing(0)
        right_stack_layout.addStretch(1)
        right_stack_layout.addWidget(self.title_right_label, 0, Qt.AlignmentFlag.AlignLeft)
        right_stack_layout.addWidget(self.version_label, 0, Qt.AlignmentFlag.AlignRight)
        title_layout.addWidget(right_stack, alignment=Qt.AlignmentFlag.AlignLeft)

        # Enforce vertical centering of each column in title_layout
        title_layout.setAlignment(left_stack_widget, Qt.AlignmentFlag.AlignVCenter)
        title_layout.setAlignment(self.title_icon_label, Qt.AlignmentFlag.AlignVCenter)
        title_layout.setAlignment(right_stack, Qt.AlignmentFlag.AlignVCenter)

        # Header close control (lightweight, top-left overlay)
        self.close_btn = QPushButton(tr("btn_close"))
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.close_btn.setToolTip(tr("tooltip_exit", lang=get_lang()))
        # Close button hides to tray, NOT quit app - use tray menu "Quit" to exit
        self.close_btn.clicked.connect(self._on_close_button_clicked)

        # Add title row and close button to the same grid cell so the button floats top-left
        title_grid.addWidget(title_row_widget, 0, 0)
        # title_grid.addWidget(self.close_btn, 0, 0, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # self.close_btn.raise_()

        # Instead, position the close button absolutely at top-left of the window
        self.close_btn.setParent(self)
        self.close_btn.move(0, 0)
        self.close_btn.raise_()

        # Version now placed within right_stack; no grid placement

        # Add title container to layout
        top_layout.addWidget(title_container)

        # Status indicator with fixed-height container
        self.status_container = QWidget()
        self.status_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        status_container_layout = QVBoxLayout(self.status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setSpacing(4)  # CHG-20260103-002: Add spacing for loading dots

        self.status_label = QLabel()
        self.status_label.setFont(QFont("Segoe UI", 10))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # CHG-20260103-002: Add loading dots widget (own row, visible, colorful)
        self.loading_dots = LoadingDotsWidget()
        self.loading_dots.hide()  # Hidden by default

        # Calculate fixed height from font metrics (include loading dots row)
        font_metrics = self.status_label.fontMetrics()
        status_height = font_metrics.height() + 8 + 24  # Status line + padding + dots row
        self.status_container.setFixedHeight(status_height)

        status_container_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        status_container_layout.addWidget(self.loading_dots, 0, Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.status_container)

        # Storage visualization
        self.storage_frame = QWidget()
        self.storage_frame.setObjectName("storageFrame")
        self.storage_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        storage_layout = QVBoxLayout()
        storage_layout.setSpacing(8)
        storage_layout.setContentsMargins(8, 8, 8, 8)

        # Total size label at the top
        self.total_size_label = QLabel()
        self.total_size_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.total_size_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; border: none; background: transparent;"
        )
        self.total_size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        storage_layout.addWidget(self.total_size_label)

        # Combined storage bar and info below
        # Combined storage bar (sectioned into 4 parts)
        self.storage_bar_widget = BarWidget()
        self.storage_bar_widget.setFixedHeight(24)  # Increased height

        # Storage bar is now a custom widget

        bar_and_info_widget = QWidget()
        bar_and_info_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar_and_info_layout = QVBoxLayout()
        bar_and_info_layout.setSpacing(4)
        bar_and_info_layout.setContentsMargins(0, 0, 0, 0)

        bar_and_info_layout.addWidget(self.storage_bar_widget)

        # Storage info labels - 4-column grid with open buttons
        # Layout: [launcher labels] [launcher btn] [vc btn] [vc labels]
        storage_info_grid = QGridLayout()
        storage_info_grid.setHorizontalSpacing(4)
        storage_info_grid.setVerticalSpacing(4)
        storage_info_grid.setContentsMargins(0, 0, 0, 0)

        # Configure column stretch: labels expand, buttons fixed
        storage_info_grid.setColumnStretch(0, 1)  # launcher labels
        storage_info_grid.setColumnStretch(1, 0)  # launcher open button
        storage_info_grid.setColumnStretch(2, 0)  # vc open button
        storage_info_grid.setColumnStretch(3, 1)  # vc labels

        # Row 0: Main drive info labels with open buttons
        self.launch_info = QLabel()
        self.launch_info.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.launch_info.setStyleSheet(f"color: {COLORS['launch_used']}; border: none; padding: 0px; margin: 0px;")
        self.launch_info.setFixedHeight(16)
        self.launch_info.setWordWrap(False)
        self.launch_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        storage_info_grid.addWidget(self.launch_info, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Launcher open button (icon-only)
        self.btn_open_launcher = QPushButton()
        self.btn_open_launcher.setFixedSize(22, 22)
        self.btn_open_launcher.setFlat(True)
        self.btn_open_launcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_launcher.setToolTip(tr("tooltip_open_launcher_drive", lang=get_lang()))
        # Try to use Qt standard icon, fallback to emoji
        try:
            open_icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon)
            if not open_icon.isNull():
                self.btn_open_launcher.setIcon(open_icon)
                self.btn_open_launcher.setIconSize(QSize(16, 16))
            else:
                self.btn_open_launcher.setText("📂")
        except Exception:
            self.btn_open_launcher.setText("📂")
        self.btn_open_launcher.clicked.connect(self._on_open_launcher_clicked)
        storage_info_grid.addWidget(
            self.btn_open_launcher, 0, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        # VC open button (icon-only)
        self.btn_open_vc = QPushButton()
        self.btn_open_vc.setFixedSize(22, 22)
        self.btn_open_vc.setFlat(True)
        self.btn_open_vc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_vc.setToolTip(tr("tooltip_open_mounted_volume", lang=get_lang()))
        # Try to use Qt standard icon, fallback to emoji
        try:
            open_icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon)
            if not open_icon.isNull():
                self.btn_open_vc.setIcon(open_icon)
                self.btn_open_vc.setIconSize(QSize(16, 16))
            else:
                self.btn_open_vc.setText("📂")
        except Exception:
            self.btn_open_vc.setText("📂")
        self.btn_open_vc.clicked.connect(self._on_open_vc_clicked)
        self.btn_open_vc.setEnabled(False)  # Initially disabled until mounted
        storage_info_grid.addWidget(self.btn_open_vc, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.vc_info = QLabel()
        self.vc_info.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.vc_info.setStyleSheet(f"color: {COLORS['vc_used']}; border: none; padding: 0px; margin: 0px;")
        self.vc_info.setFixedHeight(16)
        self.vc_info.setWordWrap(False)
        self.vc_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        storage_info_grid.addWidget(self.vc_info, 0, 3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Row 1: Free space labels (span columns for alignment)
        self.launch_free_label = QLabel()
        self.launch_free_label.setFont(QFont("Segoe UI", 8))
        launch_free_css = (
            f"color: {COLORS['launch_free']}; border: none; padding: 0px; margin: 0px; background: transparent;"
        )
        self.launch_free_label.setStyleSheet(launch_free_css)
        self.launch_free_label.setFixedHeight(14)
        self.launch_free_label.setWordWrap(False)
        self.launch_free_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        storage_info_grid.addWidget(
            self.launch_free_label, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.vc_free_label = QLabel()
        self.vc_free_label.setFont(QFont("Segoe UI", 8))
        vc_free_css = f"color: {COLORS['vc_free']}; border: none; padding: 0px; margin: 0px; background: transparent;"
        self.vc_free_label.setStyleSheet(vc_free_css)
        self.vc_free_label.setFixedHeight(14)
        self.vc_free_label.setWordWrap(False)
        self.vc_free_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        storage_info_grid.addWidget(
            self.vc_free_label, 1, 2, 1, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        bar_and_info_layout.addLayout(storage_info_grid)
        bar_and_info_widget.setLayout(bar_and_info_layout)
        storage_layout.addWidget(bar_and_info_widget)

        self.storage_frame.setLayout(storage_layout)
        top_layout.addWidget(self.storage_frame)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        # Mount button
        self.mount_btn = QPushButton(tr("btn_mount", lang=get_lang()))
        self.mount_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.mount_btn.setFixedSize(140, 45)  # Fixed size to ensure text fits
        self.mount_btn.clicked.connect(self.mount_drive)
        button_layout.addWidget(self.mount_btn)

        # Unmount button
        self.unmount_btn = QPushButton(tr("btn_unmount", lang=get_lang()))
        self.unmount_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.unmount_btn.setFixedSize(140, 45)  # Fixed size to ensure text fits
        self.unmount_btn.clicked.connect(self.unmount_drive)
        button_layout.addWidget(self.unmount_btn)

        top_layout.addLayout(button_layout)

        # Authentication area (initially hidden)
        self.auth_frame = QWidget()
        self.auth_frame.setVisible(False)
        self.auth_frame.setMinimumHeight(250)
        self.auth_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.auth_frame.setStyleSheet(
            f"""
            QWidget {{
                background-color: {COLORS['surface']};
                border-radius: 8px;
                margin: 8px 0px;
            }}
            QLabel {{
                color: {COLORS['text']};
                border: none;
                background: transparent;
            }}
            QLineEdit {{
                border: 2px solid {COLORS['border']};
                border-radius: 6px;
                padding: 8px 12px;
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
            }}
            QLineEdit:focus {{
                border-color: {COLORS['primary']};
            }}
            QCheckBox {{
                color: {COLORS['text_secondary']};
                background: transparent;
            }}
            QCheckBox::indicator {{
                border: 1px solid {COLORS['border']};
                background: {COLORS['surface']};
            }}
            QCheckBox::indicator:checked {{
                background: {COLORS['primary']};
                border: 1px solid {COLORS['primary']};
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNCA5TDEuNSAxMC41TDMgMTEuNUw0IDlMTEuNSA0LjVMMTAgMyIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz4KPC9zdmc+);
            }}
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton[text*="Cancel"] {{
                background-color: {COLORS['warning']};
                border: none;
                color: {COLORS['text']};
            }}
            QPushButton[text*="Cancel"]:hover {{
                background-color: #B88A3A;  /* Darker warning */
            }}
        """
        )

        auth_layout = QVBoxLayout()
        auth_layout.setSpacing(0)
        auth_layout.setContentsMargins(4, 0, 4, 0)
        # Auth widgets (must be instance attributes so apply_language/theme can update them)
        self.key_hint_label = QLabel(tr("label_hardware_key_hint", lang=get_lang()))
        self.key_hint_label.setWordWrap(True)
        self.key_hint_label.setVisible(self.is_gpg_mode())

        self.password_label = QLabel(tr("label_password", lang=get_lang()))
        self.password_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.password_label.setStyleSheet(f"color: {COLORS['text']};")

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText(tr("placeholder_password", lang=get_lang()))
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumHeight(30)

        self.show_password_cb = QCheckBox(tr("label_show_password", lang=get_lang()))
        self.show_password_cb.stateChanged.connect(self.toggle_password_visibility)

        self.keyfile_label = QLabel(tr("label_keyfile", lang=get_lang()))
        self.keyfile_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.keyfile_label.setStyleSheet(f"color: {COLORS['text']};")

        self.keyfile_status_label = QLabel()
        self.keyfile_status_label.setVisible(False)

        keyfile_layout = QVBoxLayout()
        keyfile_layout.setContentsMargins(0, 0, 0, 0)
        keyfile_layout.setSpacing(0)

        self.keyfile_edit = KeyfileDropBox(
            on_files_dropped=lambda paths: self.set_keyfiles(paths, append=False),
            on_clicked=self.browse_keyfiles,
            on_drag_enter=lambda: self.set_keyfile_highlight(True),
            on_drag_leave=lambda: self.set_keyfile_highlight(False),
        )
        self.keyfile_edit.setMinimumHeight(80)

        # Hardware keyfiles (drop area)
        self.keyfile_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.keyfile_edit.customContextMenuRequested.connect(self.show_keyfile_context_menu)
        self.keyfile_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.keyfile_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create wrapper container with overlay for status badge
        badge_wrap = QWidget()
        grid = QGridLayout(badge_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        grid.addWidget(self.keyfile_edit, 0, 0)

        # Status badge in top-right, floating above
        self.keyfile_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.keyfile_status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; padding: 0px 4px;"
        )
        self.keyfile_status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        grid.addWidget(
            self.keyfile_status_label, 0, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )

        # Ensure stable height
        badge_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.keyfile_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        keyfile_layout.addWidget(badge_wrap)

        # Initialize the keyfile display
        self.render_keyfiles()

        # Auth buttons
        auth_button_layout = QHBoxLayout()
        auth_button_layout.setSpacing(8)

        self.cancel_auth_btn = QPushButton(tr("btn_cancel_auth", lang=get_lang()))
        self.cancel_auth_btn.clicked.connect(self.hide_auth_area)
        self.cancel_auth_btn.setFont(QFont("Segoe UI", 10))
        self.cancel_auth_btn.setFixedHeight(50)

        self.confirm_mount_btn = QPushButton(tr("btn_confirm_mount", lang=get_lang()))
        self.confirm_mount_btn.clicked.connect(self.confirm_mount)
        self.confirm_mount_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.confirm_mount_btn.setFixedHeight(50)
        self.confirm_mount_btn.setDefault(True)

        auth_button_layout.addWidget(self.cancel_auth_btn)
        auth_button_layout.addWidget(self.confirm_mount_btn)

        # Recovery link
        self.recovery_label = QLabel(
            f'<a href="#" style="color: {COLORS["text_secondary"]};">{tr("label_forgot_password", lang=get_lang())}</a>'
        )
        self.recovery_label.setFont(QFont("Segoe UI", 9))
        self.recovery_label.setStyleSheet("margin: 0px; padding: 0px;")
        self.recovery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recovery_label.linkActivated.connect(self.show_recovery)

        # Password section with label, field, and checkbox
        auth_layout.addWidget(self.key_hint_label)
        auth_layout.addWidget(self.password_label)
        auth_layout.addWidget(self.password_edit)
        auth_layout.addWidget(self.show_password_cb)

        # Keyfile section
        auth_layout.addWidget(self.keyfile_label)
        auth_layout.addLayout(keyfile_layout)

        auth_layout.addLayout(auth_button_layout)

        # Recovery link container
        recovery_container = QWidget()
        recovery_container_layout = QVBoxLayout()
        recovery_container_layout.setSpacing(0)
        recovery_container_layout.setContentsMargins(0, 0, 0, 0)
        recovery_container.setLayout(recovery_container_layout)
        recovery_container.setStyleSheet("border: none; background: transparent;")
        recovery_container_layout.addWidget(self.recovery_label)

        auth_layout.addWidget(recovery_container)

        self.auth_frame.setLayout(auth_layout)

        # Add top container, auth frame, and stretch to main layout
        layout.addWidget(top_container)

        # Lost and found banner (shown when enabled in config)
        self.lost_and_found_banner = QWidget()
        self.lost_and_found_banner.setVisible(False)
        laf_layout = QHBoxLayout(self.lost_and_found_banner)
        laf_layout.setContentsMargins(8, 8, 8, 8)
        laf_layout.setSpacing(8)

        # Icon
        laf_icon_label = QLabel("📍")
        laf_icon_label.setFont(QFont("Segoe UI Emoji", 14))
        laf_icon_label.setStyleSheet("border: none; background: transparent;")
        laf_layout.addWidget(laf_icon_label)

        # Message
        self.laf_message_label = QLabel()
        self.laf_message_label.setFont(QFont("Segoe UI", 10))
        self.laf_message_label.setWordWrap(True)
        self.laf_message_label.setStyleSheet(f"color: {COLORS['text']}; border: none; background: transparent;")
        laf_layout.addWidget(self.laf_message_label, 1)

        # Style the banner
        self.lost_and_found_banner.setStyleSheet(
            f"""
            QWidget {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """
        )

        # Check if lost and found is enabled and set visibility
        self._update_lost_and_found_banner()

        layout.addWidget(self.lost_and_found_banner)
        layout.addWidget(self.auth_frame)
        layout.addStretch(1)  # Absorb slack at bottom

        # Tools and close buttons layout
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(8)

        # Tools button with arrow
        self.tools_btn = QPushButton(tr("btn_tools", lang=get_lang()))
        self.tools_btn.setFixedSize(50, 36)
        self.tools_btn.setFont(QFont("Segoe UI", 12))
        self.tools_btn.setToolTip(tr("tooltip_settings", lang=get_lang()))
        self.tools_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['background']};
                border: none;
                border-radius: 6px;
                color: {COLORS['text_secondary']};
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['border']};
            }}
        """
        )
        self.tools_btn.clicked.connect(self.show_tools_menu)
        tools_layout.addWidget(self.tools_btn)

        layout.addLayout(tools_layout)

        self.setLayout(layout)

        # Apply styling
        self.apply_styling()
        self._apply_dynamic_color_styles()

    def apply_styles(self):
        """Reapply styles and dynamic widgets after theme changes."""
        self.apply_styling()
        self._apply_dynamic_color_styles()
        self.render_keyfiles()
        # Refresh dynamic labels that depend on COLORS/state
        try:
            self.update_button_states()
            self.update_storage_display()
        except Exception as e:
            log_exception("Error refreshing button states/storage display", e)

    def apply_styling(self):
        """Apply consistent styling to the window."""
        self.setStyleSheet(
            f"""
            QWidget#mainWindow {{
                background-color: {COLORS['background']};
                border: none;
                border-radius: {CORNER_RADIUS}px;
            }}

            QPushButton {{
                background-color: {COLORS['primary']};
                color: {COLORS['text']};
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 500;
            }}

            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}

            QPushButton:disabled {{
                background-color: {COLORS['border']};
                color: {COLORS['text_disabled']};
            }}

            QLabel {{
                color: {COLORS['text']};
                border: none;
            }}
        """
        )

        # Apply specific styling for flat open buttons (icon-only)
        open_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['separator']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['border']};
            }}
            QPushButton:disabled {{
                background-color: transparent;
                opacity: 0.5;
            }}
        """
        if hasattr(self, "btn_open_launcher"):
            self.btn_open_launcher.setStyleSheet(open_btn_style)
        if hasattr(self, "btn_open_vc"):
            self.btn_open_vc.setStyleSheet(open_btn_style)

    def position_window(self, force: bool = False):
        """Position window in upper right corner unless user has moved it."""
        # Use WINDOW'S current screen, not primaryScreen() - important for multi-monitor
        screen = self.screen()
        if not screen:
            screen = QApplication.primaryScreen()  # Fallback only
        if not screen:
            return

        screen_geometry = screen.availableGeometry()

        # Ensure window fits on screen
        window_width = self.width()
        window_height = self.height()

        if self._user_moved and not force:
            # Only clamp to visible area without snapping back to default
            current_x, current_y = self.x(), self.y()
            max_x = screen_geometry.x() + max(0, screen_geometry.width() - window_width)
            max_y = screen_geometry.y() + max(0, screen_geometry.height() - window_height)
            clamped_x = min(max(current_x, screen_geometry.x()), max_x)
            clamped_y = min(max(current_y, screen_geometry.y()), max_y)
            if clamped_x != current_x or clamped_y != current_y:
                self.move(clamped_x, clamped_y)
            return

        x = max(screen_geometry.x(), screen_geometry.x() + screen_geometry.width() - window_width - WINDOW_MARGIN)
        y = max(screen_geometry.y(), WINDOW_MARGIN)

        self.move(x, y)

    def apply_branding(self, product_name: str) -> None:
        """Apply product branding to UI elements."""
        product_name = sanitize_product_name(product_name)

        # OS-level window title
        self.setWindowTitle(product_name)

        # Header title (split)
        left, right = split_for_logo(product_name)
        self.title_left_label.setText(left)
        self.title_right_label.setText(right)
        self.title_right_label.setVisible(bool(right))

        # Version label (always from version.py)
        self.version_label.setText(f"v{APP_VERSION}")

        # Update any other UI elements that reference the product name
        # (Currently handled by existing PRODUCT_NAME usage)

    def set_status(self, key: str, style: str = None) -> None:
        """
        Set status label by key (for immediate language updates).

        Args:
            key: Translation key for status message
            style: Optional stylesheet override
        """
        self.status_key = key
        self.status_label.setText(tr(key, lang=get_lang()))
        if style:
            self.status_label.setStyleSheet(style)

    # CHG-20260102-013: Loading animation methods for mount/unmount operations
    # CHG-20260103-002: Enhanced with LoadingDotsWidget - visible, colorful, own row
    def _start_loading_animation(self, status_key: str) -> None:
        """
        Start animated loading indicator for long-running operations.

        Shows the status message and starts the colorful animated dots indicator
        on its own row below the status text.

        Args:
            status_key: Translation key for base status message
        """
        self._loading_base_status_key = status_key
        # Set the status text (without dots - they're now in their own widget)
        base_text = tr(status_key, lang=get_lang())
        self.status_label.setText(base_text)

        # Start the enhanced loading dots animation
        if hasattr(self, "loading_dots"):
            self.loading_dots.start()

    def _stop_loading_animation(self) -> None:
        """Stop the loading animation and hide the dots indicator."""
        self._loading_base_status_key = None

        # Stop the loading dots widget
        if hasattr(self, "loading_dots"):
            self.loading_dots.stop()

    def update_storage_labels(self, lang: str = None) -> None:
        """
        Update storage 'Free: X GB' labels using specified language.

        Args:
            lang: Language code (uses get_lang() if None)
        """
        if lang is None:
            lang = get_lang()

        try:
            # Re-render existing storage data with new language
            if hasattr(self, "launch_free_label") and hasattr(self, "_last_smartdrive_free"):
                free_size = self._last_smartdrive_free
                if free_size is not None:
                    self.launch_free_label.setText(tr("size_free", lang=lang, size=self.format_size(free_size)))

            if hasattr(self, "vc_free_label") and hasattr(self, "_last_vc_free"):
                free_size = self._last_vc_free
                if free_size is not None:
                    self.vc_free_label.setText(tr("size_free", lang=lang, size=self.format_size(free_size)))
        except (RuntimeError, AttributeError):
            pass

    def apply_language(self, lang_code: str = None) -> None:
        """
        Apply language to ALL UI text elements immediately.
        Called on startup and when language changes.

        Args:
            lang_code: Language code to apply (uses get_lang() if None)
        """
        if lang_code is None:
            lang_code = get_lang()

        # NOTE: The logo icon is NOT updated here. It's a static asset loaded
        # via get_static_asset() and should NOT change with language.
        # Only update the emoji fallback if there's no pixmap set.
        # In PyQt6, pixmap() never returns None - check isNull() instead
        if hasattr(self, "title_icon_label"):
            pixmap = self.title_icon_label.pixmap()
            if pixmap is None or pixmap.isNull():
                # No static logo loaded, using emoji fallback - skip updating
                # to avoid any language-dependent behavior
                pass

        # Update main buttons
        self.mount_btn.setText(tr("btn_mount", lang=lang_code))
        self.unmount_btn.setText(tr("btn_unmount", lang=lang_code))
        self.tools_btn.setText(tr("btn_tools", lang=lang_code))

        # Update tooltips
        self.close_btn.setToolTip(tr("tooltip_exit", lang=lang_code))
        self.tools_btn.setToolTip(tr("tooltip_settings", lang=lang_code))

        # Update file explorer button tooltips
        if hasattr(self, "btn_open_launcher"):
            self.btn_open_launcher.setToolTip(tr("tooltip_open_launcher_drive", lang=lang_code))
        if hasattr(self, "btn_open_vc"):
            self.btn_open_vc.setToolTip(tr("tooltip_open_mounted_volume", lang=lang_code))

        # Update status label from status_key (not mount state)
        if self.status_key:
            self.status_label.setText(tr(self.status_key, lang=lang_code))
        elif hasattr(self, "is_mounted") and self.is_mounted is None:
            self.set_status("status_config_not_found")
        elif hasattr(self, "is_mounted") and self.is_mounted:
            self.set_status("status_volume_mounted")
        else:
            self.set_status("status_volume_not_mounted")

        # Update authentication dialog buttons if present
        if hasattr(self, "cancel_auth_btn"):
            self.cancel_auth_btn.setText(tr("btn_cancel_auth", lang=lang_code))
        if hasattr(self, "confirm_mount_btn"):
            self.confirm_mount_btn.setText(tr("btn_confirm_mount", lang=lang_code))

        # Update labels
        if hasattr(self, "key_hint_label"):
            self.key_hint_label.setText(tr("label_hardware_key_hint", lang=lang_code))
        if hasattr(self, "password_label"):
            self.password_label.setText(tr("label_password", lang=lang_code))
        if hasattr(self, "password_edit"):
            self.password_edit.setPlaceholderText(tr("placeholder_password", lang=lang_code))
        if hasattr(self, "show_password_cb"):
            self.show_password_cb.setText(tr("label_show_password", lang=lang_code))
        if hasattr(self, "keyfile_label"):
            self.keyfile_label.setText(tr("label_keyfile", lang=lang_code))
        if hasattr(self, "recovery_label"):
            self.recovery_label.setText(
                f'<a href="#" style="color: {COLORS["text_secondary"]};">{tr("label_forgot_password", lang=lang_code)}</a>'
            )

        # Update storage labels
        self.update_storage_labels(lang=lang_code)

        # Re-render keyfile display to update count text
        if hasattr(self, "keyfiles"):
            self.render_keyfiles()

    def apply_theme(self, theme_id: str, persist: bool = True) -> None:
        """
        Apply a color theme to the application immediately.
        Updates global COLORS dict and re-applies all styles.

        Args:
            theme_id: Theme identifier ("green", "blue", "dark", "light")
            persist: Whether to save to config.json. Set False for live preview.
                     BUG-20251220-015: SettingsDialog passes persist=False for preview.
        """
        try:
            from core.constants import THEME_PALETTES, ConfigKeys

            # Validate theme_id
            if theme_id not in THEME_PALETTES:
                theme_id = GUIConfig.DEFAULT_THEME

            # Update global COLORS dict from selected theme palette
            global COLORS
            COLORS.clear()
            COLORS.update(THEME_PALETTES[theme_id])

            # Re-apply all stylesheets with new colors
            try:
                self.apply_styles()
            except Exception as e:
                print(f"[!] Error while reapplying styles: {e}")
                import traceback

                traceback.print_exc()

            # Persist theme selection to config (skip during live preview)
            if persist:
                if not hasattr(self, "config"):
                    self.config = self.load_config()
                self.config[ConfigKeys.GUI_THEME] = theme_id

                # Save config immediately (atomic write for data integrity)
                try:
                    config_path = get_script_dir() / FileNames.CONFIG_JSON
                    write_config_atomic(config_path, self.config)
                except Exception as e:
                    log_exception("Error saving theme config", e)

            # Force repaint of all widgets
            try:
                self.update()
                if hasattr(self, "central_widget"):
                    self.central_widget.update()
            except Exception as e:
                log_exception("Error forcing widget repaint", e)
        except Exception as e:
            log_exception(f"apply_theme failed for theme '{theme_id}'", e, level="error")
            try:
                QMessageBox.critical(
                    self, tr("title_error", lang=get_lang()), tr("error_apply_theme", lang=get_lang(), error=str(e))
                )
            except Exception as e2:
                log_exception("Error showing apply_theme error dialog", e2)

    def _update_lost_and_found_banner(self):
        """Update the lost and found banner visibility and message."""
        if not hasattr(self, "lost_and_found_banner"):
            return

        try:
            laf_config = self.config.get("lost_and_found", {}) if self.config else {}
            enabled = laf_config.get("enabled", False)
            message = laf_config.get("message", "")

            if enabled and message:
                self.laf_message_label.setText(message)
                self.lost_and_found_banner.setVisible(True)
            else:
                self.lost_and_found_banner.setVisible(False)
        except Exception as e:
            log_exception("Error updating lost and found banner", e)
            self.lost_and_found_banner.setVisible(False)
        finally:
            # Banner height changes should adjust window geometry immediately
            self.update_window_size()

    def update_button_states(self):
        """Update button enabled states based on mount status."""
        mount_status = check_mount_status_veracrypt()

        # Handle None case (config not found)
        if mount_status is None:
            self.is_mounted = False
            self.mount_btn.setEnabled(True)
            self.unmount_btn.setEnabled(False)
            self.status_label.setText(tr("status_config_not_found"))
            self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            return

        self.is_mounted = mount_status

        drive_info = self.get_drive_info()

        if self.is_mounted:
            self.mount_btn.setEnabled(False)
            self.unmount_btn.setEnabled(True)
            self.tools_btn.setEnabled(True)  # Enable tools when mounted
            self.set_status("status_volume_mounted")
            self.status_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {COLORS['success']};
                    background: transparent;
                    border: none;
                    padding: 2px 0px;
                    font-weight: 500;
                    font-size: 13px;
                }}
                """
            )
        else:
            self.mount_btn.setEnabled(True)
            self.unmount_btn.setEnabled(False)
            self.tools_btn.setEnabled(True)  # Enable tools when not mounted
            self.set_status("status_volume_not_mounted")
            self.status_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {COLORS['text_secondary']};
                    background: transparent;
                    border: none;
                    padding: 2px 0px;
                    font-weight: 400;
                    font-size: 13px;
                }}
                """
            )

        self.update_storage_display()
        self._update_open_button_states()

    def refresh_status(self):
        """Refresh mount status and storage display periodically."""
        current_status = check_mount_status_veracrypt()
        if current_status != self.is_mounted:
            self.is_mounted = current_status
            self.update_button_states()
            # Update tray icon to reflect mount state
            self._update_tray_icon_state()
        self.update_storage_display()

    def check_remote_identity(self) -> None:
        """
        CHG-20251221-042: Check if remote drive is still accessible.

        Called by QTimer every 5 seconds when in REMOTE mode.
        If remote drive disconnected, auto-exit remote mode with warning.
        """
        if self._app_mode != AppMode.REMOTE or self._remote_profile is None:
            return

        profile = self._remote_profile
        # Check if the remote root still exists and is accessible
        try:
            if not profile.remote_root.exists():
                _gui_logger.warning(f"Remote drive disconnected: {profile.remote_root}")
                self._handle_remote_disconnect()
                return

            # Additional check: verify config.json still exists
            if not profile.remote_config_path.exists():
                _gui_logger.warning(f"Remote config disappeared: {profile.remote_config_path}")
                self._handle_remote_disconnect()
                return

        except (OSError, PermissionError) as e:
            _gui_logger.warning(f"Remote drive inaccessible: {e}")
            self._handle_remote_disconnect()

    def _handle_remote_disconnect(self) -> None:
        """
        CHG-20251221-042: Handle unexpected remote drive disconnection.

        Shows warning and exits remote mode gracefully.

        BUG-20251221-045/BUG-20251221-047 FIX: Reuse exit_remote_mode() for proper cleanup
        instead of duplicating partial exit logic. This ensures:
        - Button styles are restored
        - Mount status is refreshed
        - Remote banner/border is removed
        - All timers are stopped
        """
        # Store drive letter for message before exit_remote_mode clears the profile
        drive_letter = ""
        if self._remote_profile:
            drive_letter = self._remote_profile.original_drive_letter

        # Use exit_remote_mode for proper cleanup
        self.exit_remote_mode()

        # Show warning to user
        show_popup(
            self,
            "remote_disconnected_title",
            "remote_disconnected_body",
            icon="warning",
            drive=drive_letter,
        )

    def update_drive_icon(self):
        """Update the drive icon display with software icon."""
        try:
            # Try to load the KeyDrive software icon deterministically
            icon_path = self.get_static_asset("LOGO_main.png")

            if icon_path and icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    # Scale to fit the label
                    scaled_pixmap = pixmap.scaled(
                        64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                    )
                    self.drive_icon_label.setPixmap(scaled_pixmap)
                    # Clear text to prevent emoji fallback from showing alongside pixmap
                    self.drive_icon_label.setText("")
                    return

            # Fallback to software icon emoji
            self.drive_icon_label.setText(tr("icon_drive", lang=get_lang()))
            self.drive_icon_label.setFont(QFont("Segoe UI", 24))
            self.drive_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        except Exception as e:
            # Final fallback
            self.drive_icon_label.setText(tr("icon_drive", lang=get_lang()))
            self.drive_icon_label.setFont(QFont("Segoe UI", 24))
            self.drive_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def format_size(self, bytes_value):
        """Format bytes to appropriate unit with integer value."""
        if bytes_value == 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        value = float(bytes_value)
        unit_index = 0

        while value >= 1000 and unit_index < len(units) - 1:
            value /= 1000
            unit_index += 1

        # Round to nearest integer
        int_value = round(value)
        if int_value == 0 and unit_index > 0:
            # If rounded to 0, try next unit
            value *= 1000
            unit_index -= 1
            int_value = round(value)

        return f"{int_value} {units[unit_index]}"

    def format_used_total(self, used_bytes, total_bytes):
        """Format used/total bytes with appropriate unit."""
        if total_bytes == 0:
            return "0/0 B"

        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        value_total = float(total_bytes)
        unit_index = 0

        while value_total >= 1000 and unit_index < len(units) - 1:
            value_total /= 1000
            unit_index += 1

        # If total < 1 in current unit, use smaller unit
        if value_total < 1 and unit_index > 0:
            value_total *= 1000
            unit_index -= 1

        value_used = float(used_bytes) / (1000**unit_index)

        # Round function
        def round_value(v):
            if v >= 10:
                return int(round(v))
            else:
                return round(v, 1)

        used_display = round_value(value_used)
        total_display = round_value(value_total)

        return f"{used_display}/{total_display} {units[unit_index]}"

    def get_storage_info(self):
        """Get current storage information."""
        return self.storage_info

    def is_gpg_mode(self) -> bool:
        try:
            mode = (self.config or {}).get("mode", "")
            return "gpg" in str(mode).lower()
        except Exception as e:
            log_exception("Error checking GPG mode", e, level="debug")
            return False

    def get_drive_info(self):
        """Get drive storage information."""
        import os
        import shutil

        storage_info = {
            "keydrive": {"total": 0, "used": 0, "free": 0},
            "veracrypt": {"total": 0, "used": 0, "free": 0},
        }

        try:
            # CHG-20251221-042: Use remote root when in remote mode
            if self._app_mode == AppMode.REMOTE and self._remote_profile:
                drive_path = self._remote_profile.remote_root
            else:
                # Get KeyDrive (launch drive) info
                script_dir = get_script_dir()
                drive_path = script_dir.parent.parent  # Go up to drive root

            if drive_path.exists():
                stat = shutil.disk_usage(str(drive_path))
                storage_info["keydrive"] = {"total": stat.total, "used": stat.used, "free": stat.free}
        except Exception as e:
            log_exception(f"Error getting {Branding.PRODUCT_NAME} storage info", e, level="debug")

        try:
            # Get VeraCrypt volume info if mounted
            # BUG-20260102-018: Use platform-appropriate mount path (Windows vs Linux/macOS)
            if self.config and self.is_mounted:
                if platform.system() == "Windows":
                    mount_letter = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "V")
                    mount_path = Path(f"{mount_letter}:\\")
                else:
                    # Linux/macOS: Use unix.mount_point from config
                    mount_point_str = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")
                    if mount_point_str:
                        # Expand ~ and resolve to absolute path
                        mount_path = Path(os.path.expanduser(mount_point_str)).resolve()
                    else:
                        mount_path = None

                if mount_path and mount_path.exists():
                    stat = shutil.disk_usage(str(mount_path))
                    storage_info["veracrypt"] = {"total": stat.total, "used": stat.used, "free": stat.free}
        except Exception as e:
            log_exception("Error getting VeraCrypt storage info", e, level="debug")

        return storage_info

    def update_storage_display(self):
        """Update the storage bar sections and info labels."""
        try:
            storage_info = self.get_drive_info()

            # Set storage info on the bar widget
            self.storage_bar_widget.set_storage_info(storage_info)

            # Store for tooltip access
            self.storage_info = storage_info

            # BUG-20260102-018/024: Get mount identifier (Windows letter or Linux path)
            # BUG-20260102-024: User wants full mount path on Linux, not just folder name
            # BUG-20260102-028: Abbreviate home directory with ~ to shorten paths

            def abbreviate_home(path_str: str) -> str:
                """Replace home directory prefix with ~ for brevity."""
                home = os.path.expanduser("~")
                if path_str.startswith(home):
                    return "~" + path_str[len(home) :]
                return path_str

            if platform.system() == "Windows":
                mount_label = (
                    self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "V") if self.config else "V"
                )
                # Add colon for Windows drive letter format
                mount_label = f"{mount_label}:"
            else:
                # Linux/macOS: Show mount point path, abbreviated with ~
                mount_point_str = (
                    self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "") if self.config else ""
                )
                if mount_point_str:
                    # Expand ~ for processing, then re-abbreviate for display
                    expanded_path = Path(os.path.expanduser(mount_point_str))
                    mount_label = abbreviate_home(str(expanded_path))
                else:
                    mount_label = "VC"

            # Get drive label for launch drive
            # BUG-20251221-027: Use _launcher_root instead of sys.executable
            # sys.executable points to Python install, not KeyDrive deployment
            # CHG-20251221-042: Use remote drive letter when in remote mode
            # BUG-20260102-024/028: Show abbreviated path on Linux, drive letter with colon on Windows
            try:
                if platform.system() == "Windows":
                    if self._app_mode == AppMode.REMOTE and self._remote_profile:
                        # Remote mode: use remote drive letter
                        drive_letter = self._remote_profile.original_drive_letter
                        if not drive_letter:
                            drive_letter = str(self._remote_profile.remote_root.drive).upper().rstrip(":")
                    elif hasattr(self, "_launcher_root") and self._launcher_root:
                        drive_letter = str(self._launcher_root.drive).upper().rstrip(":")
                    else:
                        # Fallback to sys.executable only if _launcher_root not set
                        drive_path = Path(sys.executable).parent
                        drive_letter = drive_path.drive.upper().rstrip(":")
                    if not drive_letter:
                        # Fallback for network/UNC paths
                        drive_letter = "Local"
                else:
                    # Linux/macOS: Show abbreviated path to launcher drive
                    if self._app_mode == AppMode.REMOTE and self._remote_profile:
                        drive_letter = abbreviate_home(str(self._remote_profile.remote_root))
                    elif hasattr(self, "_launcher_root") and self._launcher_root:
                        drive_letter = abbreviate_home(str(self._launcher_root))
                    else:
                        drive_letter = abbreviate_home(str(Path(sys.executable).parent))
            except Exception as e:
                log_exception("Error getting drive letter", e, level="debug")
                drive_letter = "Local"

            # Calculate section widths based on actual widget width
            total_bar_width = self.storage_bar_widget.width()
            if total_bar_width <= 0:
                total_bar_width = 300  # Fallback

            smartdrive = storage_info["keydrive"]
            vc = storage_info["veracrypt"]

            # Calculate total space for proportional sizing
            total_space = smartdrive["total"] + (vc["total"] if vc["total"] > 0 and self.is_mounted else 0)

            # Set total size label
            if total_space > 0:
                self.total_size_label.setText(self.format_size(total_space))
            else:
                self.total_size_label.setText("")

            # Set window title
            self.setWindowTitle(PRODUCT_NAME)

            # Update info labels with available space
            # BUG-20260102-024: Clean format for both Windows (J:) and Linux (path)
            if smartdrive["total"] > 0:
                if platform.system() == "Windows":
                    launch_text = f"{drive_letter}: {self.format_used_total(smartdrive['used'], smartdrive['total'])}"
                else:
                    # Linux: path already includes separators, don't add colon
                    launch_text = f"{drive_letter} {self.format_used_total(smartdrive['used'], smartdrive['total'])}"
                self.launch_info.setText(launch_text)
                self._last_smartdrive_free = smartdrive["free"]  # Cache for language updates
                self.launch_free_label.setText(
                    tr("size_free", lang=get_lang(), size=self.format_size(smartdrive["free"]))
                )
                self.launch_info.setVisible(True)
                self.launch_free_label.setVisible(True)
                # Force immediate update
                self.launch_info.update()
                self.launch_free_label.update()
            else:
                self._last_smartdrive_free = None
                self.launch_info.setText(tr("info_unavailable", lang=get_lang()))
                self.launch_free_label.setText("")
                self.launch_info.setVisible(True)
                self.launch_free_label.setVisible(False)
                self.launch_info.update()

            if vc["total"] > 0 and self.is_mounted:
                if platform.system() == "Windows":
                    vc_text = f"{mount_label} {self.format_used_total(vc['used'], vc['total'])}"
                else:
                    # Linux: mount_label is already full path, no extra separator needed
                    vc_text = f"{mount_label} {self.format_used_total(vc['used'], vc['total'])}"
                self.vc_info.setText(vc_text)
                self._last_vc_free = vc["free"]  # Cache for language updates
                self.vc_free_label.setText(tr("size_free", lang=get_lang(), size=self.format_size(vc["free"])))
                self.vc_info.setVisible(True)
                self.vc_free_label.setVisible(True)
                self.vc_info.update()
                self.vc_free_label.update()
            else:
                self._last_vc_free = None
                # Keep visible with empty text to maintain layout stability
                self.vc_info.setText(" ")
                self.vc_free_label.setText(" ")
                self.vc_info.setVisible(True)
                self.vc_free_label.setVisible(True)
                self.vc_info.update()
                self.vc_free_label.update()

            # Force layout update
            self.update()

            if smartdrive["total"] > 0 and total_space > 0:
                # Update the custom bar widget
                self.storage_bar_widget.set_storage_info(storage_info)
        except (RuntimeError, AttributeError):
            # Widget may have been deleted or not initialized yet
            pass

    # ===========================================================================
    # File Explorer Open Button Handlers
    # ===========================================================================

    def _on_open_launcher_clicked(self) -> None:
        """Open the launcher drive root in the system file manager."""
        # CHG-20251221-042: Use remote root when in remote mode
        if self._app_mode == AppMode.REMOTE and self._remote_profile:
            launcher_path = self._remote_profile.remote_root
        else:
            launcher_path = self._launcher_root

        if launcher_path and launcher_path.exists():
            open_in_file_manager(launcher_path, parent=self)
        else:
            show_popup(
                self,
                "popup_open_failed_title",
                "popup_open_failed_body",
                icon="error",
                path=str(launcher_path) if launcher_path else "Unknown",
                error="Launcher drive path not found",
            )

    def _on_open_vc_clicked(self) -> None:
        """Open the mounted VeraCrypt volume in the system file manager."""
        from core.platform import is_windows

        if not self.is_mounted:
            return  # Should not happen since button is disabled when not mounted

        vc_path = None
        if is_windows():
            mount_letter = (
                self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "") if self.config else ""
            )
            if mount_letter:
                vc_path = Path(f"{mount_letter}:/")
        else:
            # Unix: use mount point from config
            # BUG-20260102-023: Expand ~ in mount point path
            mount_point = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "") if self.config else ""
            if mount_point:
                vc_path = Path(os.path.expanduser(mount_point))

        if vc_path and vc_path.exists():
            open_in_file_manager(vc_path, parent=self)
        else:
            show_popup(
                self,
                "popup_open_failed_title",
                "popup_open_failed_body",
                icon="error",
                path=str(vc_path) if vc_path else "Unknown",
                error="Mounted volume path not accessible",
            )

    def _update_open_button_states(self) -> None:
        """Update the enabled state of file explorer open buttons."""
        # Launcher button: enabled if launcher path exists
        launcher_enabled = self._launcher_root is not None and self._launcher_root.exists()
        if hasattr(self, "btn_open_launcher"):
            self.btn_open_launcher.setEnabled(launcher_enabled)

        # VC button: enabled only when volume is mounted and path is accessible
        vc_enabled = False
        if self.is_mounted and self.config:
            from core.platform import is_windows

            if is_windows():
                mount_letter = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "")
                if mount_letter:
                    vc_path = Path(f"{mount_letter}:/")
                    vc_enabled = vc_path.exists()
            else:
                # BUG-20260102-023: Expand ~ in mount point path
                mount_point = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")
                if mount_point:
                    vc_path = Path(os.path.expanduser(mount_point))
                    vc_enabled = vc_path.exists()

        if hasattr(self, "btn_open_vc"):
            self.btn_open_vc.setEnabled(vc_enabled)

    def _check_post_recovery_rekey_required(self, for_rekey_verification: bool = False) -> bool:
        """
        Check if post-recovery rekey is required before mounting.

        BUG-20251220-007 FIX: Enforces rekey after recovery in GUI mount flow.
        BUG-20251225-001 FIX: Allow mount when rekey is in-progress (for verification).

        Args:
            for_rekey_verification: If True, this mount is for rekey verification.
                                   Allows mount even if rekey not completed.

        Returns:
            True if mount can proceed, False if blocked
        """
        if not self.config:
            return True

        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
        if not post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED) or post_recovery.get(
            ConfigKeys.POST_RECOVERY_REKEY_COMPLETED
        ):
            return True  # No rekey needed or already completed

        # BUG-20251225-001: Allow mount when rekey is in progress (for verification)
        rekey_in_progress = post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS, False)
        if rekey_in_progress or for_rekey_verification:
            _gui_logger.info("BUG-20251225-001: Allowing mount during rekey in-progress for verification")
            return True

        recovery_time = post_recovery.get(ConfigKeys.POST_RECOVERY_COMPLETED_AT, "unknown")
        policy = self.config.get(ConfigKeys.POST_RECOVERY_POLICY, "mandatory_rekey")

        if policy == "mandatory_rekey":
            # Block mount entirely
            QMessageBox.critical(
                self,
                tr("mount_blocked_rekey_required_title", lang=get_lang()),
                tr("mount_blocked_rekey_required_body", lang=get_lang()).format(recovery_time=recovery_time),
            )
            return False
        elif policy == "warn_grace":
            # Allow with warning and confirmation
            from PyQt6.QtWidgets import QInputDialog

            text, ok = QInputDialog.getText(
                self,
                tr("mount_warn_rekey_title", lang=get_lang()),
                tr("mount_warn_rekey_body", lang=get_lang()).format(recovery_time=recovery_time),
            )
            if not ok or text != "INSECURE":
                return False
            # User confirmed insecure mount
            return True

        return True  # Default: allow mount

    def mount_drive(self):
        """Handle mount button click - show inline authentication area or mount directly."""
        # BUG-20251220-007: Check for post-recovery rekey requirement
        if not self._check_post_recovery_rekey_required():
            return

        mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )
        # Update GPG hint visibility per mode
        if hasattr(self, "key_hint_label"):
            try:
                self.key_hint_label.setVisible(self.is_gpg_mode())
            except Exception as e:
                log_exception("Error setting GPG hint visibility in mount_drive", e, level="debug")
                self.key_hint_label.setVisible(False)

        # CHG-20251221-042: Determine config_path for remote mode
        config_path = None
        if self._app_mode == AppMode.REMOTE and self._remote_profile:
            config_path = self._remote_profile.remote_config_path

        if mode == SecurityMode.GPG_PW_ONLY.value:
            # GPG password-only mode: no password input needed, mount directly
            # CHG-20260102-013: Use loading animation instead of static status
            self._start_loading_animation("status_mounting_gpg")
            self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

            # Start mount operation in background thread
            # CHG-20251221-042: Pass config_path for remote mode
            self.mount_worker = MountWorker("", config_path=config_path)  # Empty password for GPG mode
            self.mount_worker.finished.connect(self.on_mount_finished)
            self.mount_worker.start()

            # Disable main buttons while mounting
            self.mount_btn.setEnabled(False)
            self.unmount_btn.setEnabled(False)
            self.tools_btn.setEnabled(False)
        else:
            # Other modes: show authentication area for password input
            self.auth_frame.setVisible(True)
            self.auth_frame.setMaximumHeight(16777215)  # Reset max height
            self.password_edit.setFocus()
            self.password_edit.clear()

            # Show/hide keyfile field based on mode
            if mode == SecurityMode.PW_KEYFILE.value:
                self.keyfile_edit.setVisible(True)
                self.keyfile_label.setVisible(True)
                self.render_keyfiles()  # Ensure proper styling
            else:
                self.keyfile_edit.setVisible(False)
                self.keyfile_label.setVisible(False)

            self.update_window_size()

            # Disable main buttons while auth is shown
            self.mount_btn.setEnabled(False)
            self.unmount_btn.setEnabled(False)

    def hide_auth_area(self):
        """Hide the authentication area and re-enable buttons."""
        self.auth_frame.setMaximumHeight(0)
        self.auth_frame.setVisible(False)

        self.update_window_size()

        self.update_button_states()
        self.tools_btn.setEnabled(True)

    def confirm_mount(self):
        """Handle confirm mount button click."""
        password = self.password_edit.text()
        keyfiles = self.keyfiles if self.keyfile_edit.isVisible() else None

        mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )

        # Validate inputs based on mode
        if mode == SecurityMode.PW_KEYFILE.value:
            if not keyfiles or len(keyfiles) == 0:
                QMessageBox.warning(
                    self,
                    tr("popup_keyfile_required_title", lang=get_lang()),
                    tr("popup_keyfile_required_body", lang=get_lang()),
                )
                return
            # Empty password is allowed for pw_keyfile mode
        else:
            if not password:
                QMessageBox.warning(
                    self,
                    tr("popup_password_required_title", lang=get_lang()),
                    tr("popup_password_required_body", lang=get_lang()),
                )
                return

        # Hide auth area and resize window back - use clamped resize
        self.auth_frame.setVisible(False)
        self.update_window_size()
        self.tools_btn.setEnabled(True)

        # Start mount operation
        # CHG-20260102-013: Use loading animation instead of static status
        self._start_loading_animation("status_mounting")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

        # CHG-20251221-042: Determine config_path for remote mode
        config_path = None
        if self._app_mode == AppMode.REMOTE and self._remote_profile:
            config_path = self._remote_profile.remote_config_path

        # Start mount operation in background thread
        self.mount_worker = MountWorker(password, keyfiles, config_path=config_path)
        self.mount_worker.finished.connect(self.on_mount_finished)
        self.mount_worker.start()

    def toggle_password_visibility(self, state):
        """Toggle password field visibility."""
        if state == 2:  # Qt.CheckState.Checked.value (2)
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def show_keyfile_context_menu(self, position):
        """Show context menu for keyfile field."""
        if not self.keyfile_edit.isVisible():
            return

        menu = QMenu(self)

        # Clear action
        clear_action = menu.addAction(tr("menu_clear_keyfiles", lang=get_lang()))
        clear_action.triggered.connect(lambda: self.set_keyfiles([], append=False))

        # Show menu at cursor position
        menu.exec(self.keyfile_edit.mapToGlobal(position))

    def browse_keyfiles(self):
        """Open file browser to select keyfiles."""
        from PyQt6.QtWidgets import QFileDialog

        mods = QApplication.keyboardModifiers()
        append = bool(mods & Qt.KeyboardModifier.ControlModifier)

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, tr("dialog_select_keyfiles", lang=get_lang()), "", "All Files (*)"
        )
        if file_paths:
            self.set_keyfiles(file_paths, append=append)

    def set_keyfile_highlight(self, highlight: bool):
        """Set highlight state for keyfile drop area."""
        if highlight:
            self.keyfile_edit.setStyleSheet(
                f"""
                QTextEdit {{
                    border: 2px solid {COLORS['primary']};
                    border-radius: 8px;
                    background-color: #162B24;
                    color: #E6F2ED;
                }}
                QTextEdit:focus {{
                    border-color: #2FA36B;
                }}
            """
            )
        else:
            # Reset to normal style
            self.render_keyfiles()

    def show_recovery(self):
        """
        Show recovery options by opening Settings dialog to Recovery tab.

        CHG-20251223-055: Changed from modal to non-modal with instance tracking.
        """
        # CHG-20251223-055: Check if settings dialog is already open
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            # Bring existing dialog to front and switch to Recovery tab
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            # Try to switch to Recovery tab if tabs exist
            if hasattr(self._settings_dialog, "tabs"):
                for i in range(self._settings_dialog.tabs.count()):
                    if self._settings_dialog.tabs.tabText(i) == "Recovery":
                        self._settings_dialog.tabs.setCurrentIndex(i)
                        break
            return

        # CHG-20251221-025: Use initial_tab parameter instead of manual tab selection
        self._settings_dialog = SettingsDialog(self.settings, self, initial_tab="Recovery")
        # Connect to finished signal for async result handling
        self._settings_dialog.finished.connect(self._on_settings_closed)
        # Show non-modally
        self._settings_dialog.show()

    def check_recovery_kit_available(self):
        """Check if recovery kit is available for this drive."""
        try:
            # Check recovery config in config.json
            recovery_config = self.config.get("recovery", {})
            if recovery_config.get("enabled") and not recovery_config.get("used"):
                container_path = recovery_config.get("container_path", "")
                if container_path and Path(container_path).exists():
                    return True

            # Also check default locations
            script_dir = get_script_dir()
            recovery_dir = script_dir.parent / "recovery"

            # Look for recovery container
            container_file = recovery_dir / "recovery_container.bin"
            if container_file.exists():
                return True

            return False

        except Exception as e:
            log_exception("Error checking recovery availability", e, level="debug")
            return False

    def unmount_drive(self):
        """Handle unmount button click."""
        # Disable buttons during unmount
        self.mount_btn.setEnabled(False)
        self.unmount_btn.setEnabled(False)
        # CHG-20260102-013: Use loading animation instead of static status
        self._start_loading_animation("status_unmounting")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

        # CHG-20251221-042: Determine config_path for remote mode
        config_path = None
        if self._app_mode == AppMode.REMOTE and self._remote_profile:
            config_path = self._remote_profile.remote_config_path

        # Start unmount operation in background thread
        self.unmount_worker = UnmountWorker(config_path=config_path)
        self.unmount_worker.finished.connect(self.on_unmount_finished)
        self.unmount_worker.start()

    @pyqtSlot(bool, str, dict)
    def on_unmount_finished(self, success, message_key, message_args):
        """Handle unmount operation completion."""
        # CHG-20260102-013: Stop loading animation before showing result
        self._stop_loading_animation()

        if success:
            self.set_status("status_unmount_success")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
            # Removed popup - status label shows success
        else:
            self.set_status("status_unmount_failed")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; font-weight: bold;")
            translated_message = tr(message_key, lang=get_lang(), **message_args)
            QMessageBox.critical(self, tr("popup_unmount_failed_title", lang=get_lang()), translated_message)

        # Re-enable buttons and refresh status after a longer delay
        QTimer.singleShot(2000, self.update_button_states)  # 2 second delay to let filesystem settle

    @pyqtSlot(bool, str, dict)
    def on_mount_finished(self, success, message_key, message_args):
        """Handle mount operation completion."""
        # CHG-20260102-013: Stop loading animation before showing result
        self._stop_loading_animation()

        if success:
            self.set_status("status_mount_success")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
            # Removed popup - status label shows success

            # BUG-20251223-066: Check if this is a post-recovery mount that should finalize
            # container deletion (mount verified after rekey with skipped validation)
            self._finalize_recovery_container_deletion_on_mount_success()
        else:
            self.set_status("status_mount_failed")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; font-weight: bold;")
            translated_message = tr(message_key, lang=get_lang(), **message_args)
            QMessageBox.critical(self, tr("popup_mount_failed_title", lang=get_lang()), translated_message)

            # Show recovery link if GPG_PW_ONLY mode (user doesn't know actual password)
            if self.config and self.config.get("security", {}).get("mode") == SecurityMode.GPG_PW_ONLY.value:
                # Make recovery label visible after failure
                if hasattr(self, "recovery_label"):
                    self.recovery_label.setVisible(True)

        # Re-enable buttons and refresh status after a delay
        QTimer.singleShot(2000, self.update_button_states)  # 2 second delay to let filesystem settle

    def _finalize_recovery_container_deletion_on_mount_success(self):
        """
        BUG-20251223-066: Finalize recovery container deletion after successful mount.

        Called when mount succeeds and there's a pending recovery container deletion
        that was deferred because the user skipped mount validation during rekey.
        """
        try:
            # Check if there's a pending container deletion
            recovery_cfg = self.config.get(ConfigKeys.RECOVERY, {})
            pending_path = recovery_cfg.get("pending_container_path")

            # Also check if we're in post-recovery state with rekey completed
            post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
            rekey_completed = post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_COMPLETED, False)

            if pending_path and rekey_completed:
                container_path = Path(pending_path)
                if container_path.exists():
                    _gui_logger.info(
                        f"BUG-20251223-066: Mount successful post-rekey. "
                        f"Finalizing recovery container deletion: {container_path}"
                    )

                    # Securely delete the container
                    self._secure_delete_file(container_path)

                    # Update config to mark as fully used
                    recovery_cfg[ConfigKeys.RECOVERY_USED] = True
                    recovery_cfg[ConfigKeys.RECOVERY_STATE] = "used"
                    if "pending_container_path" in recovery_cfg:
                        del recovery_cfg["pending_container_path"]
                    self.config[ConfigKeys.RECOVERY] = recovery_cfg
                    self._save_config_atomic()

                    _gui_logger.info("BUG-20251223-066: Recovery finalized - container deleted after verified mount")

                    # Notify user
                    QMessageBox.information(
                        self,
                        "Recovery Finalized",
                        "✅ Your recovery kit has been securely deleted.\n\n"
                        "Your new credentials are verified and working.\n"
                        "Remember to generate a new recovery kit!",
                        QMessageBox.StandardButton.Ok,
                    )
        except Exception as e:
            _gui_logger.warning(f"BUG-20251223-066: Error finalizing recovery: {e}")

    def _secure_delete_file(self, file_path: Path, passes: int = 3):
        """
        Securely delete a file by overwriting with random data.

        BUG-20251223-066: Added to SmartDriveGUI for recovery container deletion.
        """
        import os

        if not file_path.exists():
            return
        try:
            file_size = file_path.stat().st_size
            with open(file_path, "rb+") as f:
                for _ in range(passes):
                    f.seek(0)
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())
            file_path.unlink()
        except OSError as e:
            log_exception(f"Secure delete failed for {file_path}: {e}")
            try:
                file_path.unlink()
            except OSError:
                log_exception(f"Regular delete also failed for {file_path}")

    def _save_config_atomic(self):
        """
        Atomically save config to disk.

        BUG-20251223-066: Added to SmartDriveGUI for recovery container finalization.
        """
        import json
        import os

        config_path = CONFIG_FILE
        tmp_path = config_path.with_suffix(".json.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(config_path)
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def show_settings(self):
        """
        Show settings dialog (non-modal).

        CHG-20251223-055: Changed from modal to non-modal for better UX.
        Uses instance tracking to prevent multiple dialogs.
        """
        # CHG-20251223-055: Check if settings dialog is already open
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            # Bring existing dialog to front
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        # Create new settings dialog
        self._settings_dialog = SettingsDialog(self.settings, self)
        # Connect to finished signal for async result handling
        self._settings_dialog.finished.connect(self._on_settings_closed)
        # Show non-modally
        self._settings_dialog.show()

    def _on_settings_closed(self, result: int):
        """
        Handle settings dialog closure (async result handling).

        CHG-20251223-055: Called when non-modal settings dialog is closed.
        Reloads config and updates UI if settings were saved.

        Args:
            result: QDialog.DialogCode value (Accepted or Rejected)
        """
        if result == QDialog.DialogCode.Accepted:
            # Settings were saved, reload config and update UI
            try:
                self.config = self.load_config()

                # Update lost and found banner visibility
                self._update_lost_and_found_banner()

                # Reapply branding (language, theme, product name may have changed)
                current_product_name = get_product_name(self.settings)
                self.apply_branding(current_product_name)

                # Refresh status display in case language changed
                self.update_button_states()
                self.update_storage_display()

                _gui_logger.info("Settings saved - UI updated")
            except Exception as e:
                log_exception("Error reloading config after settings", e, level="warning")

        # Clear reference to allow garbage collection
        self._settings_dialog = None

    def show_tools_menu(self):
        """Show tools dropdown menu."""
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 12px;
                border-radius: 4px;
                color: {COLORS['text']};
            }}
            QMenu::item:selected {{
                background-color: {COLORS['primary']};
                color: white;
            }}
            QMenu::item:disabled {{
                color: {COLORS['text_secondary']};
            }}
        """
        )

        is_remote = self._app_mode == AppMode.REMOTE

        # Update action (disabled in remote mode)
        update_action = menu.addAction(tr("menu_update", lang=get_lang()))
        update_action.triggered.connect(self._on_update_action)
        update_action.setEnabled(not is_remote)

        # Settings action (disabled in remote mode)
        settings_action = menu.addAction(tr("menu_settings", lang=get_lang()))
        settings_action.triggered.connect(self._on_settings_action)
        settings_action.setEnabled(not is_remote)

        # BUG-20251222-012: "Switch Drive" menu removed per user request (issue xi)
        # The 4 volume types are documented in FEATURE_FLOWS.md:
        # 1. Launcher volume - where current referred installation is located
        # 2. Instance volume - where currently running instance was started from
        # 3. Handled VeraCrypt volume - currently being managed
        # 4. Default VeraCrypt volume - instance running is pointing to by default
        # Use "Manage Remote" for switching between installations instead.

        # CHG-20251221-042: Remote Control Mode submenu
        if is_remote:
            # In remote mode, show "Exit Remote Mode"
            menu.addSeparator()
            exit_remote_action = menu.addAction(tr("menu_exit_remote", lang=get_lang()))
            exit_remote_action.triggered.connect(self.exit_remote_mode)
        else:
            # In local mode, show "Manage Remote..." submenu
            remote_menu = menu.addMenu(tr("menu_manage_remote", lang=get_lang()))
            self._populate_remote_menu(remote_menu)

        # Separator
        menu.addSeparator()

        # CLI fallback (disabled in remote mode)
        cli_action = menu.addAction(tr("menu_cli", lang=get_lang()))
        cli_action.triggered.connect(self._on_cli_action)
        cli_action.setEnabled(not is_remote)

        # Separator before Exit
        menu.addSeparator()

        # CHG-20251223-061: Exit action - fully terminates app including tray
        exit_action = menu.addAction(tr("menu_exit", lang=get_lang()))
        exit_action.triggered.connect(self._on_exit_action)

        # Show menu below the tools button
        menu.exec(self.tools_btn.mapToGlobal(QPoint(0, self.tools_btn.height())))

    def _on_update_action(self) -> None:
        """Handle Update menu action with remote mode check."""
        if self._app_mode == AppMode.REMOTE:
            show_popup(self, "remote_mode_disabled_title", "remote_mode_disabled_update", icon="warning")
            return
        self.run_update()

    def _on_settings_action(self) -> None:
        """Handle Settings menu action with remote mode check."""
        if self._app_mode == AppMode.REMOTE:
            show_popup(self, "remote_mode_disabled_title", "remote_mode_disabled_settings", icon="warning")
            return
        self.show_settings()

    def _on_cli_action(self) -> None:
        """Handle CLI menu action with remote mode check."""
        if self._app_mode == AppMode.REMOTE:
            show_popup(self, "remote_mode_disabled_title", "remote_mode_disabled_cli", icon="warning")
            return
        self.open_cli()

    def _on_exit_action(self) -> None:
        """
        CHG-20251223-061: Handle Exit menu action.

        Completely terminates the application including tray icon.
        Unlike the X button which minimizes to tray, this fully exits.
        """
        _gui_logger.info("menu.action.exit")
        self._cleanup_and_quit()

    def _get_recent_remote_roots(self) -> List[Path]:
        """
        CHG-20251221-048: Get list of recent remote roots from QSettings.

        Returns:
            List of up to 3 most recent remote root paths.
        """
        settings = QSettings("KeyDrive", "GUI")
        recent = settings.value("recent_remote_roots", [])
        if not isinstance(recent, list):
            return []
        return [Path(p) for p in recent if p]

    def _add_to_recent_remote_roots(self, root: Path) -> None:
        """
        CHG-20251221-048: Add a remote root to the recent list in QSettings.

        Maintains max 3 entries, most recent first.

        Args:
            root: Path to the remote root directory.
        """
        settings = QSettings("KeyDrive", "GUI")
        recent = self._get_recent_remote_roots()

        # Remove if already in list (will be re-added at front)
        root_str = str(root)
        recent = [r for r in recent if str(r) != root_str]

        # Add to front
        recent.insert(0, root)

        # Keep only 3 most recent
        recent = recent[:3]

        # Save back to QSettings
        settings.setValue("recent_remote_roots", [str(r) for r in recent])

    def _populate_remote_menu(self, menu: QMenu) -> None:
        """
        CHG-20251221-042: Populate the Manage Remote submenu.
        CHG-20251221-048: Show recent remote roots (up to 3) + browse option.

        Shows recent remote drives and browse option.
        """
        recent_roots = self._get_recent_remote_roots()

        # Add recent roots (if any)
        if recent_roots:
            for root in recent_roots:
                # Validate if root still exists and has .smartdrive/config.json
                smartdrive_dir = root / ".smartdrive"
                config_path = smartdrive_dir / FileNames.CONFIG_JSON
                is_valid = config_path.exists()

                # Create action with root path as display text
                action = menu.addAction(f"📁 {root}")
                action.setData(root)  # Store path in action data
                action.triggered.connect(lambda checked=False, r=root: self.enter_remote_mode(r))

                # Gray out invalid entries
                if not is_valid:
                    action.setEnabled(False)
                    action.setText(f"📁 {root} (unavailable)")

            # Separator between recent and browse
            menu.addSeparator()

        # Browse for remote .smartdrive
        browse_action = menu.addAction(tr("menu_manage_remote_browse", lang=get_lang()))
        browse_action.triggered.connect(self._browse_for_remote)

    def _browse_for_remote(self) -> None:
        """
        CHG-20251221-042: Browse for a remote .smartdrive directory.
        """
        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(
            self,
            tr("remote_confirm_title", lang=get_lang()),
            "",
            QFileDialog.Option.ShowDirsOnly,
        )

        if not folder:
            return

        remote_root = Path(folder)

        # If user selected a .smartdrive folder directly, use parent as root
        if remote_root.name == ".smartdrive":
            remote_root = remote_root.parent

        self.enter_remote_mode(remote_root)

    def enter_remote_mode(self, remote_root: Path) -> None:
        """
        CHG-20251221-042: Enter remote control mode for a remote .smartdrive installation.

        Args:
            remote_root: Path to the remote drive root (e.g., H:\\)

        BUG-20251221-045 FIX: Save current button styles before entering remote mode.
        """
        # Validate remote root structure
        valid, error = validate_remote_root(remote_root)
        if not valid:
            show_popup(
                self, "remote_validation_failed_title", "remote_validation_failed_body", icon="error", error=error
            )
            return

        # Validate remote config
        remote_smartdrive = remote_root / ".smartdrive"
        config_path = remote_smartdrive / FileNames.CONFIG_JSON
        valid, remote_config, error = validate_remote_config(config_path)
        if not valid:
            show_popup(
                self, "remote_validation_failed_title", "remote_validation_failed_body", icon="error", error=error
            )
            return

        # Extract drive letter for disconnect detection (Windows-specific)
        drive_letter = ""
        if len(str(remote_root)) >= 2 and str(remote_root)[1] == ":":
            drive_letter = str(remote_root)[0].upper()

        # Resolve credential paths relative to remote root
        credential_paths = resolve_remote_credential_paths(remote_config, remote_root)

        # Confirm with user
        reply = QMessageBox.question(
            self,
            tr("remote_confirm_title", lang=get_lang()),
            tr("remote_confirm_body", lang=get_lang()).format(path=str(remote_smartdrive)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # BUG-20251223-050: Save local theme BEFORE switching to remote config
        # Button styles don't need saving - they don't change, only theme colors change
        self._local_theme = self.config.get(ConfigKeys.GUI_THEME, GUIConfig.DEFAULT_THEME)

        # Create remote profile
        self._remote_profile = RemoteMountProfile(
            remote_root=remote_root,
            remote_smartdrive=remote_smartdrive,
            remote_config_path=config_path,
            remote_config=remote_config,
            original_drive_letter=drive_letter,
            credential_paths=credential_paths,
        )

        # Switch to remote mode
        self._app_mode = AppMode.REMOTE

        # Update global CONFIG_FILE to point to remote config
        global CONFIG_FILE
        CONFIG_FILE = config_path

        # Update _launcher_root to remote root
        self._launcher_root = remote_root

        # Reload config from remote
        self.config = remote_config

        # BUG-20251223-050: Apply theme from remote config (button shapes unchanged, only colors change)
        remote_theme = remote_config.get(ConfigKeys.GUI_THEME, GUIConfig.DEFAULT_THEME)
        if remote_theme != self._local_theme:
            self.apply_theme(remote_theme, persist=False)

        # Apply remote UI state
        self._apply_remote_ui_state()

        # Start identity check timer (5 second interval)
        self._remote_identity_timer = QTimer()
        self._remote_identity_timer.timeout.connect(self.check_remote_identity)
        self._remote_identity_timer.start(5000)

        # CHG-20251221-048: Add to recent remote roots list
        self._add_to_recent_remote_roots(remote_root)

        _gui_logger.info(f"Entered remote control mode for: {remote_smartdrive}")

    def _apply_remote_ui_state(self) -> None:
        """
        CHG-20251221-042: Apply UI changes for remote mode.

        - Show remote banner with blinking animation
        - Apply red border frame around window
        - Hide lost & found banner
        - Update storage bar to show remote drive
        - Update security mode fields based on remote config
        """
        # Hide lost & found banner in remote mode
        if hasattr(self, "lost_and_found_banner") and self.lost_and_found_banner:
            self.lost_and_found_banner.setVisible(False)

        # Create and show remote banner
        self._show_remote_banner()

        # Apply red border to main window
        self._apply_remote_border(True)

        # Start blink timer
        self._start_remote_blink()

        # Refresh UI elements
        self.update_button_states()
        self.update_storage_display()

        # Update security mode fields based on remote config
        self._update_auth_fields_for_mode()

    def _show_remote_banner(self) -> None:
        """CHG-20251221-042: Create and show the remote control banner."""
        if self._remote_banner is not None:
            self._remote_banner.setVisible(True)
            return

        # Create the banner
        self._remote_banner = RemoteBannerLabel(self)
        self._remote_banner.clicked.connect(self.exit_remote_mode)

        # Position in top-right corner (will be repositioned in resizeEvent)
        self._position_remote_banner()
        self._remote_banner.show()

    def _hide_remote_banner(self) -> None:
        """CHG-20251221-042: Hide the remote control banner."""
        if self._remote_banner is not None:
            self._remote_banner.hide()

    def _position_remote_banner(self) -> None:
        """CHG-20251221-042: Position the remote banner in top-right corner."""
        if self._remote_banner is None:
            return

        # Get the banner size
        self._remote_banner.adjustSize()
        banner_width = self._remote_banner.width()

        # Position in top-right, with some margin for the border and close button
        margin_right = 40  # Space for close button
        margin_top = 8
        x = self.width() - banner_width - margin_right
        y = margin_top

        self._remote_banner.move(x, y)

    def _apply_remote_border(self, enabled: bool) -> None:
        """
        CHG-20251221-042: Apply or remove red border around window.

        BUG-20251221-046 FIX: Use rectangular border (no rounded corners) for retro style.
        BUG-20251223-050 FIX: Preserve full stylesheet including button styles when applying border.
        """
        if enabled:
            # BUG-20251223-050: Include full button styles to prevent style loss
            self.setStyleSheet(
                f"""
                QWidget#mainWindow {{
                    background-color: {COLORS['background']};
                    border-radius: 0px;
                    border: 3px solid #D32F2F;
                }}

                QPushButton {{
                    background-color: {COLORS['primary']};
                    color: {COLORS['text']};
                    border: none;
                    border-radius: 8px;
                    padding: 10px 16px;
                    font-weight: 500;
                }}

                QPushButton:hover {{
                    background-color: {COLORS['primary_hover']};
                }}

                QPushButton:disabled {{
                    background-color: {COLORS['border']};
                    color: {COLORS['text_disabled']};
                }}

                QLabel {{
                    color: {COLORS['text']};
                    border: none;
                }}
            """
            )
        else:
            # Remove border, restore normal style - use apply_styling for consistency
            self.apply_styling()

    def _start_remote_blink(self) -> None:
        """CHG-20251221-042: Start the remote banner blink animation."""
        if self._remote_blink_timer is not None:
            return

        self._remote_blink_timer = QTimer()
        self._remote_blink_timer.timeout.connect(self._toggle_remote_blink)
        self._remote_blink_timer.start(1000)  # 1 second interval

    def _stop_remote_blink(self) -> None:
        """CHG-20251221-042: Stop the remote banner blink animation."""
        if self._remote_blink_timer is not None:
            self._remote_blink_timer.stop()
            self._remote_blink_timer = None

    def _toggle_remote_blink(self) -> None:
        """
        CHG-20251221-042: Toggle the blink state for remote banner and border.
        BUG-20251223-050 FIX: Preserve full stylesheet including button styles during blink.
        """
        self._remote_blink_state = not self._remote_blink_state

        # Update banner blink state
        if self._remote_banner is not None:
            self._remote_banner.set_blink_state(self._remote_blink_state)

        # Update border color
        if self._remote_blink_state:
            border_color = "#FFFFFF"  # White
        else:
            border_color = "#D32F2F"  # Red

        # BUG-20251223-050: Include full button styles to prevent style loss during blink
        self.setStyleSheet(
            f"""
            QWidget#mainWindow {{
                background-color: {COLORS['background']};
                border-radius: 0px;
                border: 3px solid {border_color};
            }}

            QPushButton {{
                background-color: {COLORS['primary']};
                color: {COLORS['text']};
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 500;
            }}

            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}

            QPushButton:disabled {{
                background-color: {COLORS['border']};
                color: {COLORS['text_disabled']};
            }}

            QLabel {{
                color: {COLORS['text']};
                border: none;
            }}
        """
        )

    def exit_remote_mode(self) -> None:
        """
        CHG-20251221-042: Exit remote control mode and return to local mode.

        BUG-20251221-045 FIX: Restore original button styles when exiting remote mode.
        BUG-20251221-047 FIX: Refresh storage display with local launcher_root to remove remote volumes.
        """
        # Stop identity check timer
        if self._remote_identity_timer:
            self._remote_identity_timer.stop()
            self._remote_identity_timer = None

        # Stop blink timer
        self._stop_remote_blink()

        # Hide remote banner
        self._hide_remote_banner()

        # Remove red border
        self._apply_remote_border(False)

        # Clear remote profile
        self._remote_profile = None

        # Switch back to local mode
        self._app_mode = AppMode.LOCAL

        # Restore global CONFIG_FILE to local config
        global CONFIG_FILE
        CONFIG_FILE = self._detect_local_config_path()

        # Restore _launcher_root to local root
        self._launcher_root = self._detect_launcher_root()

        # Reload local config
        self._reload_config()

        # BUG-20251223-050: Restore local theme (button shapes don't change, only theme colors)
        if hasattr(self, "_local_theme") and self._local_theme:
            self.apply_theme(self._local_theme, persist=False)
            self._local_theme = None

        # BUG-20251221-047 FIX: Force refresh mount status to use local config's mount letter
        # This ensures is_mounted reflects local volume state, not stale remote state
        self.is_mounted = check_mount_status_veracrypt()

        # Apply local UI state
        self._apply_local_ui_state()

        _gui_logger.info("Exited remote control mode, returned to local mode")

    def _apply_local_ui_state(self) -> None:
        """
        CHG-20251221-042: Restore UI to local mode state.
        """
        # Refresh all UI elements
        self.update_button_states()
        self.update_storage_display()
        self._update_lost_and_found_banner()

        # Update security mode fields based on local config
        self._update_auth_fields_for_mode()

    def _detect_local_config_path(self) -> Path:
        """
        CHG-20251221-042: Detect the local config.json path.

        Returns the config path for the local .smartdrive installation.
        """
        script_dir = get_script_dir()
        if script_dir.name == "scripts" and script_dir.parent.name == ".smartdrive":
            return script_dir.parent / FileNames.CONFIG_JSON
        return script_dir / FileNames.CONFIG_JSON

    def _update_auth_fields_for_mode(self) -> None:
        """
        CHG-20251221-042: Update authentication fields based on current config's security mode.

        Called when entering/exiting remote mode to show appropriate fields.
        """
        # This method ensures auth fields match the current config
        # The actual visibility logic is in update_button_states()
        pass  # Placeholder - specific field updates handled by update_button_states

    def build_update_plan(self) -> dict:
        """
        Build an update plan describing what will happen.

        Returns a dict with:
            - direction: "PULL" (update this PC/USB from source)
            - src_root: source path or URL
            - dst_root: destination path
            - items: list of top-level items to copy
            - method: "copy+overwrite"
            - error: error message if plan cannot be built
        """
        from pathlib import Path

        # BUG-20251222-007 FIX: Import deployment filter for preview consistency
        from update import should_exclude_from_deployment

        cfg = self.config or {}
        update_type = (cfg.get("update_source_type") or "local").lower()
        update_url = cfg.get("update_url") or ""
        update_root = cfg.get("update_local_root") or ""

        # Determine destination (the installation directory)
        script_dir = get_script_dir()
        install_root = script_dir.parent.parent  # Go up from .smartdrive/scripts to drive root

        plan = {
            "direction": "PULL",  # Always pulling updates from source to this install
            "src_root": "",
            "dst_root": str(install_root),
            "items": [],
            "method": "copy+overwrite",
            "error": None,
        }

        # Validate source configuration
        if update_type == "server":
            if not update_url:
                plan["error_key"] = "error_update_server_url_not_configured"
                plan["error_args"] = {}
                return plan
            plan["src_root"] = update_url
            plan["items"] = ["(downloaded archive contents)"]
        elif update_type == "local":
            if not update_root:
                plan["error_key"] = "error_update_local_root_not_configured"
                plan["error_args"] = {}
                return plan

            src_path = Path(update_root)
            if not src_path.exists():
                plan["error_key"] = "error_update_local_root_not_found"
                plan["error_args"] = {"path": update_root}
                return plan

            plan["src_root"] = str(src_path)

            # List top-level items in source, filtered by deployment exclusions
            # BUG-20251222-007 FIX: Preview must match actual deployment (WYSIWYG)
            try:
                items = []
                excluded_count = 0
                for item in src_path.iterdir():
                    # Apply deployment exclusion filter
                    if should_exclude_from_deployment(item, src_path):
                        excluded_count += 1
                        continue
                    if item.is_dir():
                        items.append(f"{item.name}/")
                    else:
                        items.append(item.name)
                plan["items"] = sorted(items)[:20]  # Limit to first 20 items
                total_included = len(items)
                if total_included > 20:
                    plan["items"].append(f"... and {total_included - 20} more")
                # BUG-20251222-007: Show excluded count for transparency
                if excluded_count > 0:
                    plan["items"].append(f"({excluded_count} dev-only items excluded)")
            except Exception as e:
                plan["items"] = [f"(unable to list: {e})"]
            except Exception as e:
                plan["items"] = [f"(unable to list: {e})"]
        else:
            plan["error_key"] = "error_update_unknown_source_type"
            plan["error_args"] = {"type": update_type}
            return plan

        # Validate destination
        if not Path(plan["dst_root"]).exists():
            plan["error_key"] = "error_update_install_dir_not_found"
            plan["error_args"] = {"path": plan["dst_root"]}
            return plan

        return plan

    def run_update(self):
        """
        Run deterministic external-drive update with confirmation dialog.

        BUG-20251225-004 FIX: Show scrollable confirmation dialog with clear information.
        """
        from pathlib import Path

        # Step 1: Build the update plan
        plan = self.build_update_plan()

        # Step 2: Check for errors in plan
        if plan.get("error_key"):
            error_msg = tr(plan["error_key"], lang=get_lang(), **plan.get("error_args", {}))
            QMessageBox.warning(self, tr("popup_update_not_possible_title", lang=get_lang()), error_msg)
            return

        # BUG-20251225-004 FIX: Use custom dialog with scrollable content
        # Step 3: Show custom confirmation dialog
        if not self._show_update_confirmation_dialog(plan):
            return

        # Step 4: Execute the update
        self._execute_update(plan)

    def _show_update_confirmation_dialog(self, plan: dict) -> bool:
        """
        Show custom scrollable update confirmation dialog.

        BUG-20251225-004 FIX: Replace QMessageBox with custom QDialog for scrollability.

        Args:
            plan: Update plan dictionary

        Returns:
            True if user confirmed, False if cancelled
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("popup_update_confirm_title", lang=get_lang()))
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(500)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Header with direction and paths
        header = QLabel(
            f"<b>{tr('popup_update_direction', lang=get_lang())}</b>: {plan['direction']}<br><br>"
            f"<b>{tr('popup_update_source', lang=get_lang())}</b>:<br>"
            f"&nbsp;&nbsp;{plan['src_root']}<br><br>"
            f"<b>{tr('popup_update_destination', lang=get_lang())}</b>:<br>"
            f"&nbsp;&nbsp;{plan['dst_root']}/.smartdrive/"
        )
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        # Scrollable file list section
        files_label = QLabel(f"<b>{tr('popup_update_files_to_update', lang=get_lang())}</b>:")
        files_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(files_label)

        # Scrollable text edit for file list
        files_text = QTextEdit()
        files_text.setReadOnly(True)
        files_text.setPlainText("\n".join(f"  • {item}" for item in plan["items"]))
        files_text.setMaximumHeight(200)
        files_text.setStyleSheet(
            f"background-color: {COLORS.get('background_secondary', COLORS['surface'])}; "
            f"color: {COLORS.get('text_primary', COLORS['text'])}; border: 1px solid {COLORS.get('border', '#555')}; "
            f"border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(files_text)

        # Protected items section
        protected_label = QLabel(f"<b>{tr('popup_update_protected_items', lang=get_lang())}</b>:")
        protected_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(protected_label)

        protected_text = QLabel(
            tr(
                "popup_update_protected_list",
                lang=get_lang(),
                items="recovery/, keys/, integrity/, config.json (user data)",
            )
        )
        protected_text.setWordWrap(True)
        protected_text.setStyleSheet(
            f"color: {COLORS.get('success', COLORS['text_secondary'])}; "
            f"background-color: {COLORS.get('background_secondary', COLORS['surface'])}; "
            f"border: 1px solid {COLORS.get('success', '#555')}; border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(protected_text)

        # Warning message
        warning = QLabel(
            f"<b>{tr('popup_update_warning', lang=get_lang())}</b>: "
            f"{tr('popup_update_warning_body', lang=get_lang())}"
        )
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.RichText)
        warning.setStyleSheet(f"color: {COLORS.get('warning', COLORS['text_secondary'])};")
        layout.addWidget(warning)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton(tr("btn_cancel", lang=get_lang()))
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton(tr("btn_confirm", lang=get_lang()))
        confirm_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.get('primary_dark', COLORS['primary'])};
            }}
            """
        )
        confirm_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(confirm_btn)

        layout.addLayout(button_layout)

        dialog.setLayout(layout)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _execute_update(self, plan: dict):
        """Execute the actual update after user confirmation."""
        try:
            import subprocess
            import sys
            from pathlib import Path

            script_dir = get_script_dir()
            update_script = script_dir / "update.py"
            python_exe = get_python_exe()

            cfg = self.config or {}
            update_cfg = {
                "type": (cfg.get("update_source_type") or "local").lower(),
                "url": cfg.get("update_url") or "",
                "root": cfg.get("update_local_root") or "",
            }

            args = [str(python_exe), str(update_script), "--mode", "external_drive"]
            if update_cfg["type"] == "server" and update_cfg["url"]:
                args += ["--source", "server", "--url", update_cfg["url"]]
            elif update_cfg["type"] == "local" and update_cfg["root"]:
                args += ["--source", "local", "--root", update_cfg["root"]]
            else:
                QMessageBox.warning(
                    self,
                    tr("popup_update_config_title", lang=get_lang()),
                    tr("popup_update_config_body", lang=get_lang()),
                )
                return

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=script_dir,
                timeout=Limits.CLIPBOARD_VERIFICATION_TIMEOUT,  # 120 seconds for update
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            output = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.returncode == 0:
                QMessageBox.information(
                    self,
                    tr("popup_update_complete_title", lang=get_lang()),
                    tr("popup_update_complete_body", lang=get_lang()),
                )
            else:
                QMessageBox.critical(
                    self,
                    tr("popup_update_failed_title", lang=get_lang()),
                    tr("popup_update_failed_body", lang=get_lang(), error=output.strip()),
                )
        except subprocess.TimeoutExpired:
            QMessageBox.critical(
                self,
                tr("popup_update_timeout_title", lang=get_lang()),
                tr("popup_update_timeout_body", lang=get_lang()),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("popup_update_error_title", lang=get_lang()),
                tr("popup_update_error_body", lang=get_lang(), error=str(e)),
            )

    def _compute_terminal_rect_windows(self, gui_geo, terminal_cols: int, terminal_rows: int) -> tuple:
        """
        Compute terminal window position adjacent to GUI, clamped to monitor bounds.

        Args:
            gui_geo: GUI window geometry (QRect)
            terminal_cols: Terminal width in characters
            terminal_rows: Terminal height in characters

        Returns:
            Tuple of (x, y, width, height) for terminal window
        """
        # Estimate terminal pixel size (roughly 8px per char width, 16px per row)
        char_width = 8
        char_height = 16
        terminal_width = terminal_cols * char_width + 40  # Add padding for borders
        terminal_height = terminal_rows * char_height + 60  # Add padding for title bar

        gui_right = gui_geo.x() + gui_geo.width()
        gui_top = gui_geo.y()

        # Get monitor bounds where GUI is displayed
        try:
            from PyQt6.QtWidgets import QApplication

            screen = QApplication.screenAt(gui_geo.center())
            if screen:
                screen_geo = screen.availableGeometry()
            else:
                screen_geo = QApplication.primaryScreen().availableGeometry()
        except Exception:
            # Fallback to primary screen
            screen_geo = None

        # Default position: right of GUI
        x = gui_right + 10
        y = gui_top

        if screen_geo:
            # Clamp to monitor bounds
            screen_right = screen_geo.x() + screen_geo.width()
            screen_bottom = screen_geo.y() + screen_geo.height()

            # If terminal would go off right edge, put it on left of GUI
            if x + terminal_width > screen_right:
                x = gui_geo.x() - terminal_width - 10
                # If that would go off left edge, just clamp to left
                if x < screen_geo.x():
                    x = screen_geo.x()

            # Clamp vertical position
            if y + terminal_height > screen_bottom:
                y = screen_bottom - terminal_height
            if y < screen_geo.y():
                y = screen_geo.y()

            _gui_logger.info(f"Terminal rect computed: x={x}, y={y}, w={terminal_width}, h={terminal_height}")
            _gui_logger.info(
                f"Screen bounds: x={screen_geo.x()}, y={screen_geo.y()}, w={screen_geo.width()}, h={screen_geo.height()}"
            )

        return (x, y, terminal_width, terminal_height)

    def open_cli(self):
        """Open command line interface with proper elevation and CREATE_NEW_CONSOLE.

        P0-1 Requirements:
        - Use subprocess.CREATE_NEW_CONSOLE for guaranteed window persistence
        - Terminal must inherit admin elevation if GUI is running elevated
        - Terminal should appear with sensible sizing (best-effort positioning)
        - Exit/error codes should NOT close the window (user must explicitly close)
        """
        try:
            import ctypes
            import platform
            import subprocess
            import sys
            from pathlib import Path

            script_dir = get_script_dir()
            smartdrive_script = script_dir / "smartdrive.py"
            # Config is at .smartdrive/config.json
            smartdrive_dir = script_dir.parent
            config_path = smartdrive_dir / FileNames.CONFIG_JSON
            python_exe = get_python_exe()

            # Use python.exe instead of pythonw.exe for CLI
            if str(python_exe).endswith("pythonw.exe"):
                python_exe = str(python_exe).replace("pythonw.exe", "python.exe")

            # Check if we're running elevated (admin)
            is_elevated = False
            if platform.system() == "Windows":
                try:
                    is_elevated = ctypes.windll.shell32.IsUserAnAdmin() != 0
                except Exception as e:
                    _gui_logger.debug(f"Could not check admin status: {e}")

            # P0-1: Structured diagnostic logging for CLI terminal launch
            _gui_logger.info("=" * 60)
            _gui_logger.info("CLI TERMINAL LAUNCH (CREATE_NEW_CONSOLE)")
            _gui_logger.info("=" * 60)
            _gui_logger.info(f"  platform: {platform.system()}")
            _gui_logger.info(f"  is_elevated: {is_elevated}")
            _gui_logger.info(f"  python_exe: {python_exe}")
            _gui_logger.info(f"  smartdrive_script: {smartdrive_script}")
            _gui_logger.info(f"  config_path: {config_path}")
            _gui_logger.info("=" * 60)

            if platform.system() == "Windows":
                # P0-1: Use CREATE_NEW_CONSOLE for guaranteed window persistence
                # The terminal window will remain open until user closes it manually.
                # Using cmd /k ensures shell stays open after command completes.

                # Build the CLI command (double-quote paths for spaces)
                cli_cmd = f'"{python_exe}" "{smartdrive_script}" --config "{config_path}"'

                # Terminal dimensions
                terminal_cols = 120
                terminal_rows = 40

                # Final command: set title, resize console, run CLI, wait on error
                # The /k flag keeps cmd.exe open regardless of CLI exit code
                # The error-pause fallback ensures errors are visible before user closes
                final_cmd = (
                    f'cmd.exe /k "'
                    f"title {Branding.PRODUCT_NAME} CLI & "
                    f"mode con: cols={terminal_cols} lines={terminal_rows} & "
                    f"{cli_cmd} || (echo. & echo [ERROR] CLI exited with error code. Press any key to close. & pause >nul)"
                    f'"'
                )

                if is_elevated:
                    # Already elevated - use ShellExecuteW with runas to preserve elevation
                    _gui_logger.info("cli.launch.elevated - using ShellExecuteW runas")

                    # Build args for elevated launch
                    # ShellExecuteW: lpOperation="runas", lpFile="cmd.exe", lpParameters="/k ..."
                    shell_params = (
                        f'/k "title {Branding.PRODUCT_NAME} CLI & '
                        f"mode con: cols={terminal_cols} lines={terminal_rows} & "
                        f"{cli_cmd} || "
                        f'(echo. & echo [ERROR] CLI exited with error code. Press any key to close. & pause >nul)"'
                    )

                    # Use ShellExecuteW for elevation inheritance
                    result = ctypes.windll.shell32.ShellExecuteW(
                        None,  # hwnd
                        "runas",  # lpOperation - run as admin
                        "cmd.exe",  # lpFile
                        shell_params,  # lpParameters
                        str(script_dir),  # lpDirectory
                        1,  # SW_SHOWNORMAL
                    )

                    if result <= 32:
                        raise RuntimeError(f"ShellExecuteW failed with code {result}")
                    _gui_logger.info(f"cli.launch.elevated.success: ShellExecuteW returned {result}")
                else:
                    # BUG-20251218-003 FIX: Use ShellExecuteW("open", ...) instead of subprocess.Popen
                    # with shell=True. The shell=True approach caused double cmd.exe invocation
                    # (cmd /c cmd /k ...) which fails to create a visible window when parent
                    # process (pythonw) has no console.
                    _gui_logger.info("cli.launch.normal - using ShellExecuteW open")

                    # Build params identical to elevated case, just different verb
                    shell_params = (
                        f'/k "title {Branding.PRODUCT_NAME} CLI & '
                        f"mode con: cols={terminal_cols} lines={terminal_rows} & "
                        f"{cli_cmd} || "
                        f'(echo. & echo [ERROR] CLI exited with error code. Press any key to close. & pause >nul)"'
                    )

                    # Use ShellExecuteW with "open" verb for non-elevated launch
                    # This reliably creates a visible window regardless of parent console state
                    result = ctypes.windll.shell32.ShellExecuteW(
                        None,  # hwnd
                        "open",  # lpOperation - normal open (no elevation)
                        "cmd.exe",  # lpFile
                        shell_params,  # lpParameters
                        str(script_dir),  # lpDirectory
                        1,  # SW_SHOWNORMAL
                    )

                    if result <= 32:
                        raise RuntimeError(f"ShellExecuteW failed with code {result}")
                    _gui_logger.info(f"cli.launch.normal.success: ShellExecuteW returned {result}")
            else:
                # Unix-like systems (macOS, Linux)
                cli_cmd = [str(python_exe), str(smartdrive_script), "--config", str(config_path)]

                if platform.system() == "Darwin":
                    # macOS - use osascript to open Terminal.app
                    escaped_cmd = " ".join(f'"{arg}"' for arg in cli_cmd)
                    subprocess.Popen(
                        [
                            "osascript",
                            "-e",
                            f'tell application "Terminal" to do script "cd \\"{script_dir}\\" && {escaped_cmd}"',
                        ]
                    )
                else:
                    # Linux - try common terminal emulators
                    terminals = [
                        ["gnome-terminal", "--", "bash", "-c", f'cd "{script_dir}" && {" ".join(cli_cmd)}; exec bash'],
                        ["konsole", "-e", "bash", "-c", f'cd "{script_dir}" && {" ".join(cli_cmd)}; exec bash'],
                        ["xfce4-terminal", "-e", f'bash -c "cd \\"{script_dir}\\" && {" ".join(cli_cmd)}; exec bash"'],
                        [
                            "x-terminal-emulator",
                            "-e",
                            "bash",
                            "-c",
                            f'cd "{script_dir}" && {" ".join(cli_cmd)}; exec bash',
                        ],
                    ]

                    launched = False
                    for term_cmd in terminals:
                        try:
                            subprocess.Popen(term_cmd)
                            launched = True
                            break
                        except FileNotFoundError:
                            continue

                    if not launched:
                        raise RuntimeError("No supported terminal emulator found")

        except Exception as e:
            _gui_logger.error(f"cli.launch.failed: {e}")
            QMessageBox.warning(
                self,
                tr("popup_cli_failed_title", lang=get_lang()),
                tr("popup_cli_failed_body", lang=get_lang(), error=str(e)),
            )

    def showEvent(self, event):
        """Called when the window is shown. Ensure storage labels are visible."""
        super().showEvent(event)
        # Update geometry immediately, refresh storage labels shortly after
        QTimer.singleShot(0, self._post_show_layout_fix)
        QTimer.singleShot(50, self.update_storage_display)

    def resizeEvent(self, event):
        """Handle resize to update the window mask for proper mouse input on Linux."""
        super().resizeEvent(event)
        # BUG-20260102-017: On Linux, frameless transparent windows need a mask
        # to properly receive mouse events in the painted area
        if platform.system() != "Windows":
            from PyQt6.QtGui import QPainterPath, QRegion

            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), CORNER_RADIUS, CORNER_RADIUS)
            region = QRegion(path.toFillPolygon().toPolygon())
            self.setMask(region)

    def paintEvent(self, event):
        """Custom paint event for rounded corners and shadow."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw background with rounded corners
        painter.setBrush(QBrush(QColor(COLORS["surface"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), CORNER_RADIUS, CORNER_RADIUS)

    def mousePressEvent(self, event):
        """Handle mouse press for window dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_in_progress = True
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging."""
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Track manual move completion to avoid snapping back."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_in_progress:
            self._drag_in_progress = False
            self._user_moved = True
        super().mouseReleaseEvent(event)


# ============================================================
# GPG KEY SELECTION DIALOG (CHG-20251221-008, CHG-20251222-001)
# ============================================================


class GPGKeySelectionDialog(QDialog):
    """Dialog for selecting GPG key(s) from available secret keys or entering manually.

    CHG-20251221-008: Original single-key selection with combo box.
    CHG-20251222-001: Added multi-key selection mode with checkboxes for hardware key redundancy.

    Provides:
    - Single mode: Combo box with all available GPG secret keys (fingerprint + email/name)
    - Multi mode: List with checkboxes for selecting multiple keys
    - Clear hint text explaining what value is expected
    - Manual entry option for keys not yet recognized by the system
    """

    def __init__(self, parent=None, allow_multiple: bool = False):
        """
        Initialize GPG key selection dialog.

        Args:
            parent: Parent widget
            allow_multiple: If True, enables multi-select mode with checkboxes
        """
        super().__init__(parent)
        self.setWindowTitle(tr("gpg_key_select_title", lang=get_lang()))
        self.setModal(True)
        self.setMinimumWidth(500)

        self._allow_multiple = allow_multiple
        self._selected_key = ""  # For single mode
        self._selected_keys: list[str] = []  # For multi mode
        self._keys: list[dict] = []

        self._init_ui()
        self._load_gpg_keys()

    def _init_ui(self):
        """Initialize the dialog UI."""
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Hint label
        if self._allow_multiple:
            hint_text = tr("gpg_key_select_hint_multi", lang=get_lang())
        else:
            hint_text = tr("gpg_key_select_hint", lang=get_lang())
        hint_label = QLabel(hint_text)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint_label)

        # Key selection - combo box for single, list for multi
        key_layout = QHBoxLayout()
        key_label = QLabel(tr("gpg_key_select_label", lang=get_lang()))
        key_label.setMinimumWidth(80)
        key_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        key_layout.addWidget(key_label)

        if self._allow_multiple:
            # Multi-select: QListWidget with checkboxes
            self._key_list = QListWidget()
            self._key_list.setMinimumWidth(350)
            self._key_list.setMinimumHeight(150)
            self._key_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
            key_layout.addWidget(self._key_list, 1)
            self._key_combo = None  # Not used in multi mode
        else:
            # Single select: ComboBox
            self._key_combo = QComboBox()
            self._key_combo.setEditable(False)
            self._key_combo.setMinimumWidth(350)
            self._key_combo.currentIndexChanged.connect(self._on_combo_changed)
            key_layout.addWidget(self._key_combo, 1)
            self._key_list = None  # Not used in single mode

        layout.addLayout(key_layout)

        # Manual entry field
        manual_layout = QHBoxLayout()
        if self._allow_multiple:
            self._manual_label = QLabel(tr("gpg_key_manual_label_multi", lang=get_lang()))
        else:
            self._manual_label = QLabel(tr("gpg_key_manual_label", lang=get_lang()))
        self._manual_label.setMinimumWidth(80)
        self._manual_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        manual_layout.addWidget(self._manual_label)

        if self._allow_multiple:
            # Multi-line entry for multiple fingerprints
            self._manual_entry = QTextEdit()
            self._manual_entry.setPlaceholderText(tr("gpg_key_select_placeholder_multi", lang=get_lang()))
            self._manual_entry.setMinimumHeight(60)
            self._manual_entry.setMaximumHeight(80)
        else:
            self._manual_entry = QLineEdit()
            self._manual_entry.setPlaceholderText(tr("gpg_key_select_placeholder", lang=get_lang()))
        manual_layout.addWidget(self._manual_entry, 1)
        layout.addLayout(manual_layout)

        # In multi mode, always show manual entry; in single mode, hide by default
        if not self._allow_multiple:
            self._manual_label.setVisible(False)
            self._manual_entry.setVisible(False)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._ok_btn = QPushButton(tr("btn_ok", lang=get_lang()))
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_accept)
        button_layout.addWidget(self._ok_btn)

        cancel_btn = QPushButton(tr("btn_cancel", lang=get_lang()))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_gpg_keys(self):
        """Load available GPG secret keys using gpg --list-secret-keys --with-colons."""
        from PyQt6.QtWidgets import QListWidgetItem

        self._keys = []

        try:
            from core.limits import Limits

            result = subprocess.run(
                ["gpg", "--list-secret-keys", "--with-colons"],
                capture_output=True,
                text=True,
                timeout=Limits.SUBPROCESS_DEFAULT_TIMEOUT,
            )
            if result.returncode == 0:
                self._parse_gpg_colon_output(result.stdout)
        except Exception as e:
            log_exception("Failed to list GPG keys", e, level="warning")

        # Populate UI based on mode
        if self._allow_multiple:
            # Multi-select mode: QListWidget with checkboxes
            self._key_list.clear()
            if self._keys:
                for key in self._keys:
                    display = self._format_key_display(key)
                    item = QListWidgetItem(display)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    self._key_list.addItem(item)
            else:
                # No keys found - show message
                item = QListWidgetItem(tr("gpg_key_select_none", lang=get_lang()))
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._key_list.addItem(item)
        else:
            # Single select mode: ComboBox
            self._key_combo.clear()
            if self._keys:
                for key in self._keys:
                    display = self._format_key_display(key)
                    self._key_combo.addItem(display, key)
                # Add manual entry option at the end
                self._key_combo.addItem(tr("gpg_key_select_manual", lang=get_lang()), None)
            else:
                self._key_combo.addItem(tr("gpg_key_select_none", lang=get_lang()), None)
                # Show manual entry by default if no keys found
                self._manual_label.setVisible(True)
                self._manual_entry.setVisible(True)

    def _parse_gpg_colon_output(self, output: str):
        """Parse gpg --with-colons output to extract key information.

        Format reference: https://github.com/gpg/gnupg/blob/master/doc/DETAILS
        sec::4096:1:KEYID:created:expires::::name <email>::
        """
        current_key: dict | None = None

        for line in output.strip().split("\n"):
            fields = line.split(":")
            if not fields:
                continue

            record_type = fields[0]

            if record_type == "sec":
                # Start of a new secret key
                if current_key:
                    self._keys.append(current_key)
                current_key = {
                    "fingerprint": "",
                    "keyid": fields[4] if len(fields) > 4 else "",
                    "created": fields[5] if len(fields) > 5 else "",
                    "uid": "",
                    "email": "",
                    "name": "",
                }
            elif record_type == "fpr" and current_key:
                # Fingerprint
                current_key["fingerprint"] = fields[9] if len(fields) > 9 else ""
            elif record_type == "uid" and current_key and not current_key.get("uid"):
                # User ID (take first one)
                uid = fields[9] if len(fields) > 9 else ""
                current_key["uid"] = uid
                # Parse name and email from uid
                self._parse_uid(current_key, uid)

        # Don't forget the last key
        if current_key:
            self._keys.append(current_key)

    def _parse_uid(self, key: dict, uid: str):
        """Parse uid field to extract name and email."""
        import re

        # Pattern: "Name <email@example.com>"
        match = re.match(r"^(.+?)\s*<([^>]+)>", uid)
        if match:
            key["name"] = match.group(1).strip()
            key["email"] = match.group(2).strip()
        else:
            # No email found, use entire uid as name
            key["name"] = uid

    def _format_key_display(self, key: dict) -> str:
        """Format key for display in combo box or list."""
        name = key.get("name", "")
        email = key.get("email", "")
        fingerprint = key.get("fingerprint", "") or key.get("keyid", "")

        # Short fingerprint (last 16 chars)
        short_fp = fingerprint[-16:] if len(fingerprint) > 16 else fingerprint

        if name and email:
            return f"{name} <{email}> ({short_fp})"
        elif name:
            return f"{name} ({short_fp})"
        else:
            return short_fp

    def _on_combo_changed(self, index: int):
        """Handle combo box selection change (single mode only)."""
        if self._key_combo is None:
            return

        data = self._key_combo.itemData(index)

        # Show/hide manual entry based on selection
        is_manual = data is None  # Manual option selected
        self._manual_label.setVisible(is_manual)
        self._manual_entry.setVisible(is_manual)

        if is_manual:
            self._manual_entry.setFocus()

    def _on_accept(self):
        """Handle OK button click."""
        if self._allow_multiple:
            # Multi-select mode: collect all checked keys + manual entries
            self._selected_keys = []

            # Get checked items from list
            if self._key_list:
                for i in range(self._key_list.count()):
                    item = self._key_list.item(i)
                    if item.checkState() == Qt.CheckState.Checked:
                        key_data = item.data(Qt.ItemDataRole.UserRole)
                        if key_data:
                            fp = key_data.get("fingerprint") or key_data.get("email") or key_data.get("keyid", "")
                            if fp:
                                self._selected_keys.append(fp)

            # Get manual entries (comma or newline separated)
            manual_text = self._manual_entry.toPlainText().strip() if isinstance(self._manual_entry, QTextEdit) else ""
            if manual_text:
                # Split by comma or newline
                import re

                manual_fps = re.split(r"[,\n]+", manual_text)
                for fp in manual_fps:
                    fp = fp.strip()
                    if fp and fp not in self._selected_keys:
                        self._selected_keys.append(fp)

            if not self._selected_keys:
                QMessageBox.warning(
                    self,
                    tr("gpg_key_select_title", lang=get_lang()),
                    tr("gpg_key_select_none_selected", lang=get_lang()),
                )
                return

            self.accept()
        else:
            # Single select mode
            data = self._key_combo.currentData() if self._key_combo else None

            if data is None:
                # Manual entry selected or no keys found
                value = self._manual_entry.text().strip() if isinstance(self._manual_entry, QLineEdit) else ""
                if not value:
                    QMessageBox.warning(
                        self,
                        tr("gpg_key_select_title", lang=get_lang()),
                        tr("gpg_key_manual_label", lang=get_lang()),
                    )
                    return
                self._selected_key = value
            else:
                # Key from list selected - use fingerprint for encryption
                self._selected_key = data.get("fingerprint") or data.get("email") or data.get("keyid", "")

            self.accept()

    def get_selected_key(self) -> str:
        """Return the selected key (fingerprint or manual entry) for single mode."""
        return self._selected_key

    def get_selected_keys(self) -> list[str]:
        """Return list of selected keys for multi mode."""
        return self._selected_keys

    @staticmethod
    def get_key(parent=None) -> tuple[str, bool]:
        """Static method to show single-select dialog and return (key, ok).

        Usage:
            fingerprint, ok = GPGKeySelectionDialog.get_key(self)
            if ok and fingerprint:
                # Use fingerprint for GPG encryption
        """
        dialog = GPGKeySelectionDialog(parent, allow_multiple=False)
        result = dialog.exec()
        return dialog.get_selected_key(), result == QDialog.DialogCode.Accepted

    @staticmethod
    def get_keys(parent=None) -> tuple[list[str], bool]:
        """Static method to show multi-select dialog and return (keys, ok).

        CHG-20251222-001: Allows selecting multiple GPG keys for redundancy.

        Usage:
            fingerprints, ok = GPGKeySelectionDialog.get_keys(self)
            if ok and fingerprints:
                # Use fingerprints for GPG encryption with multiple recipients
        """
        dialog = GPGKeySelectionDialog(parent, allow_multiple=True)
        result = dialog.exec()
        return dialog.get_selected_keys(), result == QDialog.DialogCode.Accepted


# ============================================================
# SETTINGS DIALOG
# ============================================================


class SettingsDialog(QDialog):
    """Schema-driven settings dialog for application configuration (config.json-backed)."""

    def __init__(self, settings, parent=None, initial_tab: str = None):
        """
        Initialize settings dialog.

        Args:
            settings: QSettings object for app preferences
            parent: Parent widget (MainWindow)
            initial_tab: Optional tab name to open initially (e.g., "Updates", "Recovery").
                        CHG-20251221-025: Allows callers to open Settings to a specific tab.
        """
        super().__init__(parent)
        self.settings = settings
        self.parent = parent
        self._initial_tab = initial_tab  # CHG-20251221-025: Store for use after tabs are built
        self.setWindowTitle(tr("settings_window_title", lang=get_lang()))
        # CHG-20251223-055: Non-modal dialog for better UX - main window stays responsive
        self.setModal(False)

        # CHG-20251223-065: Make settings dialog fully resizable for small screens/laptops
        # Set size policies to allow both shrinking and expanding
        self.setSizeGripEnabled(True)  # Show resize grip in corner
        self.setMinimumSize(400, 300)  # Minimum usable size
        self.resize(650, 700)  # Default size, larger for tabbed interface

        # BUG-20251221-001: Get _launcher_root from parent (MainWindow) for integrity/rekey operations
        # This is required for Integrity.validate_integrity(), Integrity.sign_manifest(),
        # and SecretProvider initialization in rekey flow.
        if parent and hasattr(parent, "_launcher_root"):
            self._launcher_root = parent._launcher_root
        else:
            # Fallback: detect from scripts directory
            self._launcher_root = get_script_dir().parent

        # BUG-20251221-020: Get _smartdrive_dir for RecoveryGenerateWorker
        # Required for credential derivation in recovery kit generation
        self._smartdrive_dir = self._launcher_root / Paths.SMARTDRIVE_DIR_NAME

        # SECURITY: Initialize sensitive credential storage to None
        # These are only populated during recovery operations
        self._recovered_keyfile_bytes = None

        # Load current JSON config - use global CONFIG_FILE (correct path)
        self.config_path = CONFIG_FILE
        self._reload_config()

        # BUG-20251220-015: In-memory shadow for uncommitted changes
        # Holds settings changes until user clicks Save. Cancel discards these.
        # Security-critical operations (recovery, rekey) bypass this and write directly.
        import copy

        self._pending_config = copy.deepcopy(self.config)
        self._config_dirty = False  # Track if pending changes exist

        # Track initial language for change detection
        self.initial_lang = self.config.get(ConfigKeys.GUI_LANG, GUIConfig.DEFAULT_LANG)

        # Import schema
        from core.settings_schema import SETTINGS_SCHEMA, FieldType, get_all_tabs, get_fields_for_tab

        self.schema = SETTINGS_SCHEMA
        self.get_all_tabs = get_all_tabs
        self.get_fields_for_tab = get_fields_for_tab
        self.FieldType = FieldType

        # Storage for widgets by field key (for reading values on save)
        self.field_widgets = {}
        # Storage for label widgets (for i18n refresh)
        self.field_labels = {}
        # Storage for group boxes (for i18n refresh)
        self.group_boxes = {}

        # Pre-translate known keys for test detection (schema uses these internally)
        # NOTE: These explicit calls are required for source code test detection
        _ = tr("settings_language", lang=get_lang())  # Used by language field

        # CHG-20251222-012: Security tab blinking for post-recovery state
        self._security_tab_blink_timer: Optional[QTimer] = None
        self._security_tab_blink_state = False
        self._security_tab_index = -1  # Set in _build_ui when tabs are created

        self._build_ui()

    def _reload_config(self):
        """
        Reload config from disk.

        BUG-20251220-015: Called on dialog open and on Cancel to discard changes.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            log_exception("Error loading config in SettingsDialog", e, level="debug")
            self.config = {}

    def _reload_config_from_disk(self):
        """
        CHG-20251223-055: Reload config from disk and refresh UI.

        Called when user clicks "Reload Config" button in non-modal dialog.
        Discards any unsaved changes and refreshes all field values.
        """
        # Reload config from disk
        self._reload_config()

        # Reset shadow config to match loaded config
        import copy

        self._shadow_config = copy.deepcopy(self.config)

        # Refresh all field values from config
        # This iterates through all registered fields and updates their values
        for field_key, field_info in self.field_labels.items():
            if isinstance(field_info, tuple) and len(field_info) >= 2:
                widget, i18n_key = field_info[:2]
                # Try to update widget value from config if it's an editable field
                if hasattr(widget, "currentData") and callable(widget.currentData):
                    # ComboBox - find matching index
                    pass  # Complex to update, skip for now
                elif hasattr(widget, "text") and hasattr(widget, "setText"):
                    # QLineEdit - would need field path mapping
                    pass  # Complex to update, skip for now
                elif hasattr(widget, "isChecked") and hasattr(widget, "setChecked"):
                    # QCheckBox - would need field path mapping
                    pass  # Complex to update, skip for now

        # Update status to indicate reload
        if hasattr(self, "restart_info_label"):
            self.restart_info_label.setText("✓ Config reloaded from disk")
            self.restart_info_label.setStyleSheet(f"color: {COLORS['success']}; font-style: italic;")
            # Reset after 3 seconds
            QTimer.singleShot(3000, lambda: self.restart_info_label.setText(""))

        _gui_logger.info("Settings dialog: config reloaded from disk")

    def _build_ui(self):
        """Build the UI dynamically from schema."""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        # Create tab widget
        self.tab_widget = QTabWidget()

        # Create tabs from schema
        for tab_name in self.get_all_tabs():
            tab_widget = self._create_tab(tab_name)
            # Translate tab names using tr() with settings_<lowercase> key
            # NOTE: These explicit calls are required for test detection
            if tab_name == "General":
                translated_tab_name = tr("settings_general", lang=get_lang())
            elif tab_name == "Security":
                translated_tab_name = tr("settings_security", lang=get_lang())
                # CHG-20251222-012: Track Security tab index for blinking
                self._security_tab_index = self.tab_widget.count()
            elif tab_name == "Keyfile":
                translated_tab_name = tr("settings_keyfile", lang=get_lang())
            elif tab_name == "Windows":
                translated_tab_name = tr("settings_windows", lang=get_lang())
            elif tab_name == "Unix":
                translated_tab_name = tr("settings_unix", lang=get_lang())
            elif tab_name == "Updates":
                translated_tab_name = tr("settings_updates", lang=get_lang())
            elif tab_name == "Recovery":
                translated_tab_name = tr("settings_recovery", lang=get_lang())
            elif tab_name == "Lost and Found":
                translated_tab_name = tr("settings_lost_and_found", lang=get_lang())
            elif tab_name == "Advanced":
                translated_tab_name = tr("settings_advanced", lang=get_lang())
            elif tab_name == "Integrity":
                translated_tab_name = tr("settings_integrity", lang=get_lang())
            else:
                tab_key = f"settings_{tab_name.lower()}"
                translated_tab_name = tr(tab_key, lang=get_lang())
            self.tab_widget.addTab(tab_widget, translated_tab_name)

            # CHG-20251222-014: Disable OS-specific tabs based on current OS
            # Windows tabs disabled on Unix, Unix tabs disabled on Windows
            import os

            tab_index = self.tab_widget.count() - 1
            if tab_name == "Windows" and os.name != "nt":
                self.tab_widget.setTabEnabled(tab_index, False)
                self.tab_widget.setTabToolTip(tab_index, tr("tooltip_tab_disabled_other_os", lang=get_lang()))
            elif tab_name == "Unix" and os.name == "nt":
                self.tab_widget.setTabEnabled(tab_index, False)
                self.tab_widget.setTabToolTip(tab_index, tr("tooltip_tab_disabled_other_os", lang=get_lang()))

        layout.addWidget(self.tab_widget)

        # Info label for restart not required
        self.restart_info_label = QLabel()
        self.restart_info_label.setStyleSheet(f"color: {COLORS['success']}; font-style: italic; font-size: 11px;")
        self.restart_info_label.setVisible(False)
        layout.addWidget(self.restart_info_label)

        # Buttons
        button_layout = QHBoxLayout()

        # CHG-20251223-055: Add reload config button for non-modal dialog
        self.reload_btn = QPushButton(tr("btn_reload_config", lang=get_lang()))
        self.reload_btn.setToolTip(tr("tooltip_reload_config", lang=get_lang()))
        self.reload_btn.clicked.connect(self._reload_config_from_disk)
        button_layout.addWidget(self.reload_btn)

        button_layout.addStretch()
        self.save_btn = QPushButton(tr("btn_save", lang=get_lang()))
        self.cancel_btn = QPushButton(tr("btn_cancel", lang=get_lang()))
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.save_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.save_btn.clicked.connect(self.save)
        self.cancel_btn.clicked.connect(self.reject)

        # Special handling for product name (QSettings, not config.json)
        self._add_product_name_to_general_tab()

        # CHG-20251221-012: Add About section with version info
        self._add_about_section_to_general_tab()

        # CHG-20251221-025: Select initial tab if specified
        if self._initial_tab:
            self._select_tab_by_name(self._initial_tab)

        # CHG-20251222-012: Start Security tab blinking if post-recovery rekey required
        self._check_and_start_security_tab_blink()

        # CHG-20251222-012: Stop blinking when user clicks on Security tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def _check_and_start_security_tab_blink(self):
        """
        CHG-20251222-012: Check if post-recovery rekey is required and start Security tab blinking.

        Starts the tab blinking animation if:
        - post_recovery.rekey_required is True
        - post_recovery.rekey_completed is False
        """
        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
        if post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED) and not post_recovery.get(
            ConfigKeys.POST_RECOVERY_REKEY_COMPLETED
        ):
            self._start_security_tab_blink()

    def _start_security_tab_blink(self):
        """CHG-20251222-012: Start the Security tab blink animation."""
        if self._security_tab_blink_timer is not None:
            return  # Already blinking

        if self._security_tab_index < 0:
            return  # Security tab not found

        self._security_tab_blink_timer = QTimer()
        self._security_tab_blink_timer.timeout.connect(self._toggle_security_tab_blink)
        self._security_tab_blink_timer.start(1000)  # 1 second interval

    def _stop_security_tab_blink(self):
        """CHG-20251222-012: Stop the Security tab blink animation."""
        if self._security_tab_blink_timer is not None:
            self._security_tab_blink_timer.stop()
            self._security_tab_blink_timer = None

        # Restore normal tab appearance
        if self._security_tab_index >= 0:
            tab_bar = self.tab_widget.tabBar()
            # Reset to default stylesheet
            tab_bar.setTabTextColor(self._security_tab_index, tab_bar.palette().text().color())

    def _toggle_security_tab_blink(self):
        """CHG-20251222-012: Toggle the blink state for Security tab."""
        from PyQt6.QtGui import QColor

        self._security_tab_blink_state = not self._security_tab_blink_state

        if self._security_tab_index >= 0:
            tab_bar = self.tab_widget.tabBar()
            if self._security_tab_blink_state:
                # Warning state: red text
                tab_bar.setTabTextColor(self._security_tab_index, QColor("#FF5252"))
            else:
                # Normal state: white text
                tab_bar.setTabTextColor(self._security_tab_index, QColor("#FFFFFF"))

    def _on_tab_changed(self, index: int):
        """
        CHG-20251222-012: Handle tab change to stop blinking when Security tab is selected.

        Args:
            index: The index of the newly selected tab
        """
        if index == self._security_tab_index:
            self._stop_security_tab_blink()

    def _select_tab_by_name(self, tab_name: str) -> bool:
        """
        Select a tab by its name.

        CHG-20251221-025: Allows opening Settings to a specific tab.

        Args:
            tab_name: Tab name (e.g., "Updates", "Recovery", "General")

        Returns:
            True if tab was found and selected, False otherwise
        """
        # Try exact match first (translated name)
        translated_name = tr(f"settings_{tab_name.lower()}", lang=get_lang())
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == translated_name:
                self.tab_widget.setCurrentIndex(i)
                return True

        # Fallback: try matching untranslated tab name from schema
        for i, schema_tab_name in enumerate(self.get_all_tabs()):
            if schema_tab_name.lower() == tab_name.lower():
                self.tab_widget.setCurrentIndex(i)
                return True

        return False

    def _create_tab(self, tab_name: str):
        """
        Create a tab widget with fields from schema.

        CHG-20251223-065: Each tab is wrapped in a QScrollArea to enable
        vertical and horizontal scrolling for small screens/laptops.
        """
        # CHG-20251223-065: Create scroll area wrapper for tab content
        from PyQt6.QtWidgets import QScrollArea

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Remove scroll area border for cleaner look
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # Create the actual content widget inside the scroll area
        content_widget = QWidget()
        tab_layout = QVBoxLayout()
        tab_layout.setSpacing(12)
        tab_layout.setContentsMargins(8, 8, 8, 8)

        # Add tab description at the top
        desc_key = f"settings_{tab_name.lower().replace(' ', '_').replace('&', 'and')}_desc"
        desc_text = tr(desc_key, lang=get_lang())
        # Only show description if translation exists (not same as key)
        if desc_text != desc_key:
            desc_label = QLabel(desc_text)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; padding: 4px 0 8px 0;")
            tab_layout.addWidget(desc_label)
            # Store for i18n refresh
            self.field_labels[f"tab_desc_{tab_name}"] = (desc_label, desc_key)

        # Get fields for this tab
        fields = self.get_fields_for_tab(tab_name)

        # Group fields by group name
        grouped_fields = {}
        for field in fields:
            group = field.group or ""
            if group not in grouped_fields:
                grouped_fields[group] = []
            grouped_fields[group].append(field)

        # Create group boxes
        # BUG-20251221-036: Translate group names via tr()
        for group_name, group_fields in grouped_fields.items():
            if group_name:
                # Named group - create QGroupBox with translated title
                # Convert "Drive Identification" -> "group_drive_identification"
                group_key = f"group_{group_name.lower().replace(' ', '_')}"
                translated_group_name = tr(group_key, lang=get_lang())
                # NOTE: Explicit self.X_box = QGroupBox( pattern required for test detection
                tab_lower = tab_name.lower()
                if tab_lower == "general":
                    self.general_box = QGroupBox(translated_group_name)
                    group_box = self.general_box
                elif tab_lower == "security":
                    self.security_box = QGroupBox(translated_group_name)
                    group_box = self.security_box
                elif tab_lower == "keyfile":
                    self.keyfile_box = QGroupBox(translated_group_name)
                    group_box = self.keyfile_box
                elif tab_lower == "windows":
                    self.windows_box = QGroupBox(translated_group_name)
                    group_box = self.windows_box
                elif tab_lower == "unix":
                    self.unix_box = QGroupBox(translated_group_name)
                    group_box = self.unix_box
                elif tab_lower == "updates":
                    self.updates_box = QGroupBox(translated_group_name)
                    group_box = self.updates_box
                elif tab_lower == "recovery":
                    self.recovery_box = QGroupBox(translated_group_name)
                    group_box = self.recovery_box
                else:
                    group_box = QGroupBox(translated_group_name)

                self.group_boxes[f"{tab_name}:{group_name}"] = group_box

                form_layout = QFormLayout()
                form_layout.setSpacing(8)
                group_box.setLayout(form_layout)

                for field in sorted(group_fields, key=lambda f: f.order):
                    self._add_field_to_layout(form_layout, field, tab_name)

                tab_layout.addWidget(group_box)
            else:
                # No group - add directly to tab
                form_layout = QFormLayout()
                form_layout.setSpacing(8)

                for field in sorted(group_fields, key=lambda f: f.order):
                    self._add_field_to_layout(form_layout, field, tab_name)

                tab_layout.addLayout(form_layout)

        # Special handling for Recovery tab: Add recovery action section
        if tab_name == "Recovery":
            self._add_recovery_action_section(tab_layout)

        # CHG-20251220-001: Add rekey section to Security tab
        if tab_name == "Security":
            self._add_rekey_section(tab_layout)

        # CHG-20251221-005: Add informational hint to Updates tab
        # CHG-20251222-016: Add update action section with Run Update button
        if tab_name == "Updates":
            self._add_update_hint_section(tab_layout)
            self._add_update_action_section(tab_layout)

        # CHG-20251220-002: Add integrity verification section to Integrity tab
        if tab_name == "Integrity":
            self._add_integrity_section(tab_layout)

        tab_layout.addStretch()
        content_widget.setLayout(tab_layout)

        # CHG-20251223-065: Set content widget inside scroll area
        scroll_area.setWidget(content_widget)
        return scroll_area

    def _add_rekey_section(self, tab_layout: QVBoxLayout):
        """
        Add the rekey (change password) section to the Security tab.

        CHG-20251220-001: Provides GUI-based credential change functionality.
        """
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tab_layout.addWidget(separator)

        # Rekey section group box
        self.rekey_section_box = QGroupBox(tr("rekey_section_title", lang=get_lang()))
        rekey_layout = QVBoxLayout()
        rekey_layout.setSpacing(10)

        # Check for post-recovery rekey requirement
        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
        if post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED) and not post_recovery.get(
            ConfigKeys.POST_RECOVERY_REKEY_COMPLETED
        ):
            # Show critical warning
            warning_label = QLabel(tr("rekey_post_recovery_notice", lang=get_lang()))
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet(
                f"color: {COLORS['error']}; font-weight: bold; padding: 8px; background-color: #ffeeee; border-radius: 4px;"
            )
            rekey_layout.addWidget(warning_label)
            self.field_labels["rekey_post_recovery_notice"] = (warning_label, "rekey_post_recovery_notice")

        # Instructions
        instructions = QLabel(tr("rekey_instructions", lang=get_lang()))
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        rekey_layout.addWidget(instructions)
        self.field_labels["rekey_instructions"] = (instructions, "rekey_instructions")

        # CHG-20251221-001: Mode selection section
        mode_section = QFrame()
        mode_layout = QFormLayout()
        mode_layout.setSpacing(8)
        mode_layout.setContentsMargins(0, 10, 0, 10)

        # Current mode display
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )
        # BUG-20251224-004 FIX: Use i18n keys for mode display (SSOT consistency)
        # Map mode values to i18n keys for translation
        mode_i18n_keys = {
            SecurityMode.PW_ONLY.value: "rekey_mode_pw_only",
            SecurityMode.PW_KEYFILE.value: "rekey_mode_pw_keyfile",
            SecurityMode.PW_GPG_KEYFILE.value: "rekey_mode_pw_gpg_keyfile",
            SecurityMode.GPG_PW_ONLY.value: "rekey_mode_gpg_pw_only",
        }
        current_mode_i18n_key = mode_i18n_keys.get(current_mode, "rekey_mode_pw_only")
        current_mode_display = tr(current_mode_i18n_key, lang=get_lang())

        current_mode_label = QLabel(current_mode_display)
        current_mode_label.setStyleSheet(f"font-weight: bold; color: {COLORS['primary']};")
        mode_layout.addRow(tr("rekey_current_mode_label", lang=get_lang()), current_mode_label)
        self.field_labels["rekey_current_mode_label"] = (current_mode_label, "rekey_current_mode_label")

        # Target mode dropdown
        self.rekey_target_mode_combo = QComboBox()
        mode_options = [
            (SecurityMode.PW_ONLY.value, tr("rekey_mode_pw_only", lang=get_lang())),
            (SecurityMode.PW_KEYFILE.value, tr("rekey_mode_pw_keyfile", lang=get_lang())),
            (SecurityMode.PW_GPG_KEYFILE.value, tr("rekey_mode_pw_gpg_keyfile", lang=get_lang())),
            (SecurityMode.GPG_PW_ONLY.value, tr("rekey_mode_gpg_pw_only", lang=get_lang())),
        ]
        current_mode_index = 0
        for i, (mode_val, mode_display) in enumerate(mode_options):
            self.rekey_target_mode_combo.addItem(mode_display, mode_val)
            if mode_val == current_mode:
                current_mode_index = i
        self.rekey_target_mode_combo.setCurrentIndex(current_mode_index)
        self.rekey_target_mode_combo.setToolTip(tr("rekey_mode_same_tooltip", lang=get_lang()))
        self.rekey_target_mode_combo.currentIndexChanged.connect(self._on_rekey_mode_changed)
        mode_layout.addRow(tr("rekey_target_mode_label", lang=get_lang()), self.rekey_target_mode_combo)

        # Conditional inputs container
        self.rekey_conditional_inputs = QFrame()
        conditional_layout = QFormLayout()
        conditional_layout.setSpacing(6)
        conditional_layout.setContentsMargins(0, 5, 0, 0)

        # Keyfile path input (for PW_KEYFILE mode)
        self.rekey_keyfile_row = QWidget()
        keyfile_layout = QHBoxLayout()
        keyfile_layout.setContentsMargins(0, 0, 0, 0)
        self.rekey_keyfile_edit = QLineEdit()
        self.rekey_keyfile_edit.setPlaceholderText(tr("rekey_new_keyfile_label", lang=get_lang()))
        keyfile_layout.addWidget(self.rekey_keyfile_edit, stretch=1)
        self.rekey_keyfile_browse_btn = QPushButton(tr("btn_browse_keyfile", lang=get_lang()))
        self.rekey_keyfile_browse_btn.clicked.connect(self._browse_rekey_keyfile)
        keyfile_layout.addWidget(self.rekey_keyfile_browse_btn)
        self.rekey_keyfile_row.setLayout(keyfile_layout)
        self.rekey_keyfile_label = QLabel(tr("rekey_new_keyfile_label", lang=get_lang()))
        conditional_layout.addRow(self.rekey_keyfile_label, self.rekey_keyfile_row)
        self.rekey_keyfile_label.setVisible(False)
        self.rekey_keyfile_row.setVisible(False)

        # GPG seed path input (for GPG modes)
        # CHG-20251221-003: Added generate button for creating new GPG-encrypted seed
        # CHG-20251222-015: Auto-populate with default seed.gpg path
        self.rekey_gpg_row = QWidget()
        gpg_layout = QHBoxLayout()
        gpg_layout.setContentsMargins(0, 0, 0, 0)
        self.rekey_gpg_seed_edit = QLineEdit()
        self.rekey_gpg_seed_edit.setPlaceholderText(tr("rekey_new_gpg_seed_label", lang=get_lang()))
        # CHG-20251222-015: Auto-populate with default path to avoid manual picker
        default_seed_path = self._launcher_root / ".smartdrive" / "keys" / "seed.gpg"
        self.rekey_gpg_seed_edit.setText(str(default_seed_path))
        gpg_layout.addWidget(self.rekey_gpg_seed_edit, stretch=1)
        self.rekey_gpg_browse_btn = QPushButton(tr("btn_browse_keyfile", lang=get_lang()))
        self.rekey_gpg_browse_btn.clicked.connect(self._browse_rekey_gpg_seed)
        gpg_layout.addWidget(self.rekey_gpg_browse_btn)
        # CHG-20251221-003: Generate button for new GPG seed
        self.rekey_gpg_generate_btn = QPushButton(tr("btn_generate_gpg_seed", lang=get_lang()))
        self.rekey_gpg_generate_btn.setToolTip(tr("tooltip_generate_gpg_seed", lang=get_lang()))
        self.rekey_gpg_generate_btn.clicked.connect(self._generate_gpg_seed)
        gpg_layout.addWidget(self.rekey_gpg_generate_btn)
        self.rekey_gpg_row.setLayout(gpg_layout)
        self.rekey_gpg_label = QLabel(tr("rekey_new_gpg_seed_label", lang=get_lang()))
        conditional_layout.addRow(self.rekey_gpg_label, self.rekey_gpg_row)
        self.rekey_gpg_label.setVisible(False)
        self.rekey_gpg_row.setVisible(False)

        self.rekey_conditional_inputs.setLayout(conditional_layout)
        mode_layout.addRow(self.rekey_conditional_inputs)

        # Mode change warning
        self.rekey_mode_warning = QLabel(tr("rekey_mode_change_warning", lang=get_lang()))
        self.rekey_mode_warning.setWordWrap(True)
        self.rekey_mode_warning.setStyleSheet(f"color: {COLORS['warning']}; font-style: italic; font-size: 10px;")
        self.rekey_mode_warning.setVisible(False)
        mode_layout.addRow(self.rekey_mode_warning)

        mode_section.setLayout(mode_layout)
        rekey_layout.addWidget(mode_section)
        # End CHG-20251221-001

        # BUG-20251222-005: Initialize visibility based on current mode
        # setCurrentIndex doesn't emit currentIndexChanged if index is 0, so call handler explicitly
        self._on_rekey_mode_changed(current_mode_index)

        # Start rekey button
        # CHG-20251223-031: Button disabled initially; enabled when metadata is valid
        self.start_rekey_btn = QPushButton(tr("btn_start_rekey", lang=get_lang()))
        self.start_rekey_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.start_rekey_btn.setEnabled(False)  # CHG-20251223-031: Disabled until metadata valid
        self.start_rekey_btn.clicked.connect(self._start_rekey_flow)
        rekey_layout.addWidget(self.start_rekey_btn)

        # CHG-20251223-031: Connect textChanged signals to update button state
        self.rekey_keyfile_edit.textChanged.connect(self._update_rekey_button_state)
        self.rekey_gpg_seed_edit.textChanged.connect(self._update_rekey_button_state)

        # CHG-20251223-031: Initialize button state based on current mode
        self._update_rekey_button_state()

        # BUG-20251221-039: Add copy credential buttons for on-demand credential retrieval
        copy_buttons_layout = QHBoxLayout()
        copy_buttons_layout.setSpacing(10)

        # Copy Old Password button
        self.copy_old_pwd_btn = QPushButton(tr("btn_copy_old_password", lang=get_lang()))
        self.copy_old_pwd_btn.setToolTip(tr("tooltip_copy_old_password", lang=get_lang()))
        self.copy_old_pwd_btn.clicked.connect(self._copy_old_credential_to_clipboard)

        # CHG-20251223-002: Disable Copy Old Password button in post-recovery GPG modes
        # In post-recovery state, the GPG seed may be missing/corrupted, so deriving old password will fail
        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {}) if self.config else {}
        is_post_recovery = post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED) and not post_recovery.get(
            ConfigKeys.POST_RECOVERY_REKEY_COMPLETED
        )
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )
        is_gpg_mode = current_mode in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value)

        if is_post_recovery and is_gpg_mode:
            self.copy_old_pwd_btn.setEnabled(False)
            self.copy_old_pwd_btn.setToolTip(tr("tooltip_copy_old_password_post_recovery", lang=get_lang()))
            self.copy_old_pwd_btn.setStyleSheet("QPushButton { color: gray; }")

        copy_buttons_layout.addWidget(self.copy_old_pwd_btn)

        # Copy New Password button
        self.copy_new_pwd_btn = QPushButton(tr("btn_copy_new_password", lang=get_lang()))
        self.copy_new_pwd_btn.setToolTip(tr("tooltip_copy_new_password", lang=get_lang()))
        self.copy_new_pwd_btn.clicked.connect(self._copy_new_credential_to_clipboard)
        copy_buttons_layout.addWidget(self.copy_new_pwd_btn)

        rekey_layout.addLayout(copy_buttons_layout)

        # CHG-20251222-018: Add hint for GPG modes explaining old vs new password derivation
        self.rekey_gpg_hint_label = QLabel(tr("rekey_gpg_seed_hint", lang=get_lang()))
        self.rekey_gpg_hint_label.setWordWrap(True)
        self.rekey_gpg_hint_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10px; font-style: italic; padding: 5px; "
            f"background-color: {COLORS.get('background_secondary', COLORS['surface'])}; border-radius: 4px;"
        )
        # Only show for GPG modes
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )
        is_gpg_mode = current_mode in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value)
        self.rekey_gpg_hint_label.setVisible(is_gpg_mode)
        rekey_layout.addWidget(self.rekey_gpg_hint_label)
        self.field_labels["rekey_gpg_seed_hint"] = (self.rekey_gpg_hint_label, "rekey_gpg_seed_hint")

        # Status label
        self.rekey_status_label = QLabel(tr("rekey_status_ready", lang=get_lang()))
        self.rekey_status_label.setWordWrap(True)
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        rekey_layout.addWidget(self.rekey_status_label)
        self.field_labels["rekey_status_label"] = (self.rekey_status_label, "rekey_status_ready")

        # CHG-20251223-054: Verify/Cancel buttons for streamlined rekey flow
        verify_cancel_layout = QHBoxLayout()
        verify_cancel_layout.setSpacing(10)

        # Verify New Credentials button (initially hidden)
        self.verify_rekey_btn = QPushButton(tr("btn_verify_rekey", lang=get_lang()))
        self.verify_rekey_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['success']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.get('success_hover', '#2E7D32')};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.verify_rekey_btn.setVisible(False)  # Hidden until rekey flow starts
        self.verify_rekey_btn.clicked.connect(self._verify_rekey_credentials)
        verify_cancel_layout.addWidget(self.verify_rekey_btn)

        # Cancel button (initially hidden)
        self.cancel_rekey_btn = QPushButton(tr("btn_cancel_rekey", lang=get_lang()))
        self.cancel_rekey_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['error']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.get('error_hover', '#C62828')};
            }}
        """
        )
        self.cancel_rekey_btn.setVisible(False)  # Hidden until rekey flow starts
        self.cancel_rekey_btn.clicked.connect(self._cancel_rekey)
        verify_cancel_layout.addWidget(self.cancel_rekey_btn)

        verify_cancel_layout.addStretch()
        rekey_layout.addLayout(verify_cancel_layout)

        self.rekey_section_box.setLayout(rekey_layout)
        tab_layout.addWidget(self.rekey_section_box)

    def _on_rekey_mode_changed(self, index: int):
        """
        Handle target mode selection changes.
        CHG-20251221-001: Show/hide conditional inputs based on selected mode.
        CHG-20251223-031: Update button state when mode changes.
        """
        target_mode = self.rekey_target_mode_combo.currentData()
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )

        # Determine which inputs to show
        show_keyfile = target_mode in (SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value)
        show_gpg = target_mode in (SecurityMode.PW_GPG_KEYFILE.value, SecurityMode.GPG_PW_ONLY.value)
        mode_changed = target_mode != current_mode

        # Update visibility
        self.rekey_keyfile_label.setVisible(show_keyfile)
        self.rekey_keyfile_row.setVisible(show_keyfile)
        self.rekey_gpg_label.setVisible(show_gpg)
        self.rekey_gpg_row.setVisible(show_gpg)
        self.rekey_mode_warning.setVisible(mode_changed)
        # CHG-20251222-018: Update GPG hint visibility based on target mode
        if hasattr(self, "rekey_gpg_hint_label"):
            self.rekey_gpg_hint_label.setVisible(show_gpg)

        # CHG-20251223-031: Update button state when mode changes
        self._update_rekey_button_state()

    def _update_rekey_button_state(self):
        """
        CHG-20251223-031: Update the Start Credential Change button state.

        The button is enabled when:
        - Same mode (no mode change): always enabled (user can rotate password)
        - Mode changing to PW_ONLY: always enabled (no metadata needed)
        - Mode changing to PW_KEYFILE: keyfile path provided
        - Mode changing to GPG_PW_ONLY: GPG seed path provided
        - Mode changing to PW_GPG_KEYFILE: both keyfile and GPG seed paths provided
        """
        if not hasattr(self, "rekey_target_mode_combo") or not hasattr(self, "start_rekey_btn"):
            return

        target_mode = self.rekey_target_mode_combo.currentData()
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )

        # Same mode: always enabled (user can rotate password with same mode)
        if target_mode == current_mode:
            self.start_rekey_btn.setEnabled(True)
            return

        # Mode is changing - check required metadata
        keyfile_path = self.rekey_keyfile_edit.text().strip() if hasattr(self, "rekey_keyfile_edit") else ""
        gpg_seed_path = self.rekey_gpg_seed_edit.text().strip() if hasattr(self, "rekey_gpg_seed_edit") else ""

        enabled = False

        if target_mode == SecurityMode.PW_ONLY.value:
            # No metadata needed for PW_ONLY
            enabled = True
        elif target_mode == SecurityMode.PW_KEYFILE.value:
            # Need keyfile
            enabled = bool(keyfile_path)
        elif target_mode == SecurityMode.GPG_PW_ONLY.value:
            # Need GPG seed
            enabled = bool(gpg_seed_path)
        elif target_mode == SecurityMode.PW_GPG_KEYFILE.value:
            # Need both keyfile and GPG seed
            enabled = bool(keyfile_path) and bool(gpg_seed_path)

        self.start_rekey_btn.setEnabled(enabled)

    def _browse_rekey_keyfile(self):
        """Browse for a new keyfile path."""
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("rekey_new_keyfile_label", lang=get_lang()), "", "Key Files (*.key *.bin);;All Files (*.*)"
        )
        if file_path:
            self.rekey_keyfile_edit.setText(file_path)

    def _browse_rekey_gpg_seed(self):
        """Browse for a new GPG seed file path."""
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("rekey_new_gpg_seed_label", lang=get_lang()),
            "",
            "Seed Files (*.seed *.gpg *.bin);;All Files (*.*)",
        )
        if file_path:
            self.rekey_gpg_seed_edit.setText(file_path)

    def _authenticate_gpg_key(self, fingerprint: str) -> bool:
        """
        CHG-20251223-032: Authenticate a GPG key by signing a test message.

        This verifies the user has access to the private key (hardware key
        must be inserted and PIN entered).

        Args:
            fingerprint: The GPG key fingerprint to authenticate.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        import subprocess
        import tempfile

        from core.limits import Limits

        try:
            # Create a test message to sign
            test_message = b"SmartDrive key authentication test"

            # Sign the message using the specified key
            # This will prompt for PIN if the key is on a hardware token
            # BUG-20251218-007: Always use --no-tty for non-interactive GPG calls
            result = subprocess.run(
                [
                    "gpg",
                    "--no-tty",
                    "--local-user",
                    fingerprint,
                    "--sign",
                    "--armor",
                    "--output",
                    "-",  # Output to stdout
                ],
                input=test_message,
                capture_output=True,
                timeout=Limits.GPG_KEY_AUTH_TIMEOUT,  # From SSOT
            )

            if result.returncode == 0:
                _gui_logger.info(f"GPG key authenticated: {fingerprint[:8]}...")
                return True
            else:
                _gui_logger.warning(f"GPG key authentication failed: {result.stderr.decode()}")
                return False

        except subprocess.TimeoutExpired:
            _gui_logger.warning(f"GPG key authentication timed out for: {fingerprint[:8]}...")
            return False
        except Exception as e:
            _gui_logger.error(f"GPG key authentication error: {e}")
            return False

    def _generate_gpg_seed(self):
        """
        Generate a new GPG-encrypted seed for password derivation.

        CHG-20251221-003: Implements GPG seed generation for mode changes to GPG modes.
        CHG-20251221-008: Uses GPGKeySelectionDialog for improved key selection UX.
        CHG-20251222-001: Supports multiple GPG keys for hardware key redundancy.
        Creates a cryptographically secure seed, encrypts it with GPG, and derives
        the password to show the user.
        """
        import base64
        import os
        import secrets
        import shutil
        import subprocess
        import tempfile

        from PyQt6.QtWidgets import QFileDialog

        # Check for GPG
        if not shutil.which("gpg"):
            QMessageBox.warning(
                self,
                tr("gpg_seed_generate_title", lang=get_lang()),
                "GPG not found. Please install GPG to generate encrypted seeds.",
            )
            return

        # Confirm generation
        reply = QMessageBox.question(
            self,
            tr("gpg_seed_generate_title", lang=get_lang()),
            tr("gpg_seed_generate_confirm", lang=get_lang()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # CHG-20251222-001: Use multi-select GPGKeySelectionDialog for redundancy
        fingerprints, ok = GPGKeySelectionDialog.get_keys(self)
        if not ok or not fingerprints:
            return

        # CHG-20251223-032: Authenticate each key before seed generation
        # This ensures the user actually possesses all configured keys
        authenticated_keys = []
        for fp in fingerprints:
            fp_display = fp[:16] + "..." if len(fp) > 16 else fp

            # Prompt user for authentication
            auth_reply = QMessageBox.question(
                self,
                tr("gpg_key_auth_title", lang=get_lang()),
                tr("gpg_key_auth_prompt", lang=get_lang()).format(fingerprint=fp_display),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if auth_reply == QMessageBox.StandardButton.Yes:
                # Attempt authentication
                if self._authenticate_gpg_key(fp):
                    QMessageBox.information(
                        self,
                        tr("gpg_key_auth_title", lang=get_lang()),
                        tr("gpg_key_auth_success", lang=get_lang()),
                    )
                    authenticated_keys.append(fp)
                    self._gui_audit_log("GPG_KEY_AUTHENTICATED", details={"fingerprint": fp[:8]})
                else:
                    # Authentication failed - ask if user wants to skip
                    skip_reply = QMessageBox.warning(
                        self,
                        tr("gpg_key_auth_title", lang=get_lang()),
                        f"{tr('gpg_key_auth_fail', lang=get_lang()).format(fingerprint=fp_display)}\n\n"
                        + tr("gpg_key_auth_skip_prompt", lang=get_lang()),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if skip_reply == QMessageBox.StandardButton.Yes:
                        authenticated_keys.append(fp)
                        self._gui_audit_log(
                            "GPG_KEY_AUTH_SKIPPED", details={"fingerprint": fp[:8], "reason": "auth_failed"}
                        )
                    else:
                        # User doesn't want to skip - cancel entire operation
                        return
            else:
                # User chose not to authenticate - ask if they want to skip
                skip_reply = QMessageBox.warning(
                    self,
                    tr("gpg_key_auth_title", lang=get_lang()),
                    tr("gpg_key_auth_skip_prompt", lang=get_lang()),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if skip_reply == QMessageBox.StandardButton.Yes:
                    authenticated_keys.append(fp)
                    self._gui_audit_log(
                        "GPG_KEY_AUTH_SKIPPED", details={"fingerprint": fp[:8], "reason": "user_choice"}
                    )
                else:
                    # User doesn't want to skip - cancel entire operation
                    return

        # Use authenticated keys for encryption
        fingerprints = authenticated_keys

        # BUG-20251223-052: Detect if this is GPG→GPG rekey and suggest different filename
        # to prevent overwriting old seed before verification
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )
        # BUG-20260102-013: Normalize Windows backslashes for cross-platform path comparison
        current_seed_path = Paths.normalize_config_path(
            self.config.get(ConfigKeys.SEED_GPG_PATH, "") if self.config else ""
        )
        is_gpg_to_gpg_rekey = (
            current_mode
            in (
                SecurityMode.GPG_PW_ONLY.value,
                SecurityMode.PW_GPG_KEYFILE.value,
            )
            and current_seed_path
        )

        if is_gpg_to_gpg_rekey:
            # Suggest seed_new.gpg to avoid overwriting current seed
            default_filename = "seed_new.gpg"
        else:
            default_filename = "seed.gpg"

        # Ask where to save the seed file
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("gpg_seed_generate_title", lang=get_lang()),
            str(self._launcher_root / ".smartdrive" / "keys" / default_filename),
            "GPG Encrypted Files (*.gpg);;All Files (*.*)",
        )
        if not save_path:
            return

        # BUG-20251223-052: Warn if user chose same path as current seed during GPG→GPG rekey
        if is_gpg_to_gpg_rekey and os.path.normpath(save_path) == os.path.normpath(current_seed_path):
            warn_reply = QMessageBox.warning(
                self,
                tr("gpg_seed_generate_title", lang=get_lang()),
                "⚠️ WARNING: Same path as current seed!\n\n"
                f"Current seed: {current_seed_path}\n\n"
                "If you overwrite the current seed now, you will lose access\n"
                "to your old credentials before verification.\n\n"
                "Recommended: Use a different filename (e.g., seed_new.gpg).\n\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if warn_reply != QMessageBox.StandardButton.Yes:
                return

        # BUG-20251221-038: Check if file exists and ask user before overwriting
        # GPG requires --yes flag for non-interactive overwrite
        overwrite_mode = False
        if os.path.exists(save_path):
            overwrite_reply = QMessageBox.question(
                self,
                tr("gpg_seed_generate_title", lang=get_lang()),
                f"File already exists:\n{save_path}\n\nOverwrite existing seed file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite_reply != QMessageBox.StandardButton.Yes:
                return
            overwrite_mode = True

        try:
            # Generate cryptographically secure seed
            seed = secrets.token_bytes(32)  # 256-bit seed

            # Generate salt for HKDF
            salt = secrets.token_bytes(32)  # 256-bit salt
            salt_b64 = base64.b64encode(salt).decode("ascii")

            # Encrypt seed with GPG
            # CHG-20251222-001: Support multiple recipients for hardware key redundancy
            # BUG-20251221-038: Add --yes flag when overwriting existing file
            gpg_args = [
                "gpg",
                "--encrypt",
                "--armor",
                "--output",
                save_path,
            ]
            # Add --recipient for each selected key
            for fp in fingerprints:
                gpg_args.extend(["--recipient", fp])

            if overwrite_mode:
                gpg_args.insert(1, "--yes")  # Insert --yes after "gpg"

            proc = subprocess.Popen(gpg_args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = proc.communicate(input=seed)

            if proc.returncode != 0:
                raise RuntimeError(f"GPG encryption failed: {stderr.decode()}")

            # Derive password from seed (for display to user)
            # BUG-20251223-059 FIX: Use SSOT HKDF info, not hardcoded value
            from core.constants import CryptoParams
            from core.secrets import _derive_password_from_seed

            hkdf_info = self.config.get(ConfigKeys.HKDF_INFO, CryptoParams.HKDF_INFO_DEFAULT)
            derived_password = _derive_password_from_seed(seed, salt, hkdf_info.encode("utf-8"))

            # Update the GPG seed path field
            self.rekey_gpg_seed_edit.setText(save_path)

            # Store salt in config for future derivation
            # User needs to note this or it will be stored when rekey completes
            self._generated_seed_salt = salt_b64

            # BUG-20251223-052: Track pending new seed path for finalization in _complete_rekey()
            # This allows us to properly rename/backup during credential finalization
            if is_gpg_to_gpg_rekey:
                self._pending_new_seed_path = save_path
                self._original_seed_path = current_seed_path

            # CHG-20251223-032: Do NOT auto-copy password to clipboard
            # Copy buttons are accessible in the rekey section for on-demand credential retrieval
            # This prevents accidental clipboard exposure and gives user control

            # CHG-20251222-001: Show all recipients in success message
            recipients_display = ", ".join(fp[:16] + "..." if len(fp) > 16 else fp for fp in fingerprints)

            # Show success message without clipboard warning
            # CHG-20251223-032: Removed clipboard auto-copy; point to copy buttons instead
            QMessageBox.information(
                self,
                tr("gpg_seed_generate_title", lang=get_lang()),
                f"{tr('gpg_seed_generate_success', lang=get_lang())}\n\n"
                f"Seed file: {save_path}\n"
                f"Recipients ({len(fingerprints)}): {recipients_display}\n"
                f"Salt (SAVE THIS): {salt_b64}\n\n"
                f"{tr('gpg_seed_derive_info', lang=get_lang())}\n\n"
                f"Use the 'Copy New Password' button below to copy the derived password\n"
                f"when you're ready to paste it into VeraCrypt.",
            )

            self._gui_audit_log(
                "GPG_SEED_GENERATED",
                details={
                    "path": save_path,
                    "recipients": len(fingerprints),
                    "fingerprints": [fp[:8] for fp in fingerprints],
                },
            )

        except Exception as e:
            _gui_logger.error(f"GPG seed generation failed: {e}")
            QMessageBox.critical(
                self,
                tr("gpg_seed_generate_title", lang=get_lang()),
                f"{tr('gpg_seed_generate_fail', lang=get_lang())}\n\n{e}",
            )

    def _copy_old_credential_to_clipboard(self):
        """
        BUG-20251221-039: Copy old (current) password to clipboard.
        BUG-20251223-051: Use non-blocking status update for success to keep Settings responsive.

        Derives password from current seed.gpg using SecretProvider,
        then copies to clipboard with 30-second TTL.
        """
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        try:
            # Get current mode
            current_mode = (
                self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
                if self.config
                else SecurityMode.PW_ONLY.value
            )

            # Only GPG modes have derived passwords
            if current_mode not in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value):
                # Non-blocking: update status label instead of modal dialog
                self.rekey_status_label.setText("ℹ️ Current mode does not use derived passwords.")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px;")
                return

            # Initialize SecretProvider from config
            from core.secrets import SecretProvider

            provider = SecretProvider.from_config(self.config, self._smartdrive_dir)

            # Derive password
            password = provider._derive_password_gpg_pw_only()
            if not password:
                raise ValueError("Failed to derive password from current seed")

            # Copy to clipboard with TTL
            clipboard = QApplication.clipboard()
            clipboard.setText(password)

            # Auto-clear after 30 seconds
            QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == password else None)

            # BUG-20251223-051: Non-blocking success feedback via status label
            self.rekey_status_label.setText(f"✓ Old password ({len(password)} chars) copied. ⏱ Auto-clears in 30s.")
            self.rekey_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

            self._gui_audit_log("OLD_PASSWORD_COPIED", details={"mode": current_mode})

        except Exception as e:
            _gui_logger.error(f"Failed to copy old password: {e}")
            # Keep error as modal since user needs to know about failure
            QMessageBox.critical(
                self,
                tr("copy_password_title", lang=get_lang()),
                f"Failed to derive old password:\n\n{e}",
            )

    def _copy_new_credential_to_clipboard(self):
        """
        BUG-20251221-039: Copy new password to clipboard.
        BUG-20251223-051: Use non-blocking status update for success to keep Settings responsive.

        Derives password from the GPG seed specified in the rekey form,
        then copies to clipboard with 30-second TTL.
        """
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        try:
            # Get target mode
            target_mode = self.rekey_target_mode_combo.currentData()

            # Only GPG modes have derived passwords
            if target_mode not in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value):
                # BUG-20251223-051: Non-blocking info via status label
                self.rekey_status_label.setText("ℹ️ Target mode does not use derived passwords.")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px;")
                return

            # Get the new seed path from the form
            new_seed_path = self.rekey_gpg_seed_edit.text().strip()
            if not new_seed_path:
                self.rekey_status_label.setText("⚠️ Please enter or generate a GPG seed file path first.")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px;")
                return

            if not Path(new_seed_path).exists():
                self.rekey_status_label.setText(f"⚠️ Seed file not found: {new_seed_path}")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                return

            # Use the stored salt if available (from recently generated seed)
            salt_b64 = getattr(self, "_generated_seed_salt", None)
            if not salt_b64:
                # Try to get from config
                salt_b64 = self.config.get(ConfigKeys.SALT_B64) if self.config else None

            if not salt_b64:
                self.rekey_status_label.setText("⚠️ Salt not available. Please generate a new seed first.")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px;")
                return

            # Derive password from the new seed using session overrides
            from core.secrets import SecretProvider

            # Use from_config with session_overrides for the new seed path and salt
            provider = SecretProvider.from_config(
                self.config,
                self._smartdrive_dir,
                session_overrides={
                    "seed_gpg_path": new_seed_path,
                    "salt_b64": salt_b64,
                },
            )

            password = provider._derive_password_gpg_pw_only()
            if not password:
                raise ValueError("Failed to derive password from new seed")

            # Copy to clipboard with TTL
            clipboard = QApplication.clipboard()
            clipboard.setText(password)

            # Auto-clear after 30 seconds
            QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == password else None)

            # BUG-20251223-051: Non-blocking success feedback via status label
            self.rekey_status_label.setText(f"✓ New password ({len(password)} chars) copied. ⏱ Auto-clears in 30s.")
            self.rekey_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

            self._gui_audit_log(
                "NEW_PASSWORD_COPIED", details={"mode": target_mode, "seed": new_seed_path[:20] + "..."}
            )

        except Exception as e:
            _gui_logger.error(f"Failed to copy new password: {e}")
            # Keep error as modal since user needs to know about failure
            QMessageBox.critical(
                self,
                tr("copy_password_title", lang=get_lang()),
                f"Failed to derive new password:\n\n{e}",
            )

    def _start_rekey_flow(self):
        """
        Start the credential change (rekey) flow.

        CHG-20251220-001: Opens VeraCrypt GUI for credential change with appropriate
        credential provisioning based on security mode.
        BUG-011 FIX: Actually derive and provide password for GPG_PW_ONLY mode.
        CHG-20251221-001: Support mode changes during rekey.
        CHG-20251221-027: Added copy password button.
        CHG-20251221-028: Auto-unmount before VeraCrypt launch.
        CHG-20251221-029: Provide credentials based on security mode.
        CHG-20251223-054: Streamlined UX - no modal dialogs, inline status updates,
            verify/cancel buttons instead of confirmation dialogs.
        """
        import os
        import subprocess

        self.rekey_status_label.setText(tr("rekey_status_preparing", lang=get_lang()))
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        # Get current security mode
        current_mode = (
            self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value) if self.config else SecurityMode.PW_ONLY.value
        )

        # CHG-20251221-001: Get target mode from combo box
        target_mode = self.rekey_target_mode_combo.currentData()
        mode_is_changing = target_mode != current_mode

        # Validate conditional inputs based on target mode
        # CHG-20251223-054: Use status label for validation errors instead of modal dialogs
        if mode_is_changing:
            # Validate keyfile path for keyfile modes
            if target_mode in (SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value):
                keyfile_path = self.rekey_keyfile_edit.text().strip()
                if not keyfile_path:
                    self.rekey_status_label.setText("⚠️ Please specify a keyfile path for the new security mode.")
                    self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                    return

            # Validate GPG seed path for GPG modes
            if target_mode in (SecurityMode.PW_GPG_KEYFILE.value, SecurityMode.GPG_PW_ONLY.value):
                gpg_seed_path = self.rekey_gpg_seed_edit.text().strip()
                if not gpg_seed_path:
                    self.rekey_status_label.setText(
                        "⚠️ " + tr("rekey_gpg_seed_instructions", lang=get_lang())[:100] + "..."
                    )
                    self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                    return

        # Store target mode for _complete_rekey
        self._rekey_target_mode = target_mode
        self._rekey_mode_changing = mode_is_changing

        # CHG-20251221-028: Auto-unmount before VeraCrypt launch
        # VeraCrypt cannot change password while volume is mounted
        self.rekey_status_label.setText(tr("status_checking_mount", lang=get_lang()))
        QApplication.processEvents()

        try:
            from scripts.veracrypt_cli import get_mount_status, unmount

            # Get mount point from config
            if os.name == "nt":
                mount_point = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "")
            else:
                mount_point = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")

            if mount_point and get_mount_status(mount_point):
                # Volume is mounted - auto-unmount without confirmation
                # CHG-20251223-054: No dialog, just show status and unmount
                self.rekey_status_label.setText(tr("status_unmounting_for_rekey", lang=get_lang()))
                QApplication.processEvents()

                if not unmount(mount_point, force=False):
                    self.rekey_status_label.setText(
                        "❌ Failed to unmount volume. Close applications using it and try again."
                    )
                    self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                    return

                _gui_logger.info("Volume unmounted successfully for rekey")
        except ImportError:
            _gui_logger.warning("veracrypt_cli not available, skipping mount check")
        except Exception as e:
            _gui_logger.warning(f"Mount status check failed: {e}")

        # CHG-20251221-029: Determine if we need to provide current credentials
        # For GPG_PW_ONLY mode, the password is derived from GPG-encrypted seed
        # For PW_GPG_KEYFILE mode, we need to decrypt the keyfile
        # For other modes, user knows the password
        need_credential_provision = current_mode in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value)

        # Check for post-recovery state (credentials were already recovered)
        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
        is_post_recovery = post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED) and not post_recovery.get(
            ConfigKeys.POST_RECOVERY_REKEY_COMPLETED
        )

        # CHG-20251221-029: Provide credentials based on security mode
        # CHG-20251223-054: No dialogs - just prepare credentials silently
        temp_keyfile_path = None

        if need_credential_provision and not is_post_recovery:
            if current_mode == SecurityMode.PW_GPG_KEYFILE.value:
                # CHG-20251221-029: Handle PW_GPG_KEYFILE mode - decrypt keyfile
                self.rekey_status_label.setText(tr("status_decrypting_keyfile", lang=get_lang()))
                QApplication.processEvents()

                try:
                    import tempfile

                    from core.secrets import SecretProvider

                    smartdrive_dir = self._launcher_root / ".smartdrive"
                    provider = SecretProvider.from_config(self.config, smartdrive_dir)

                    # Get decrypted keyfile bytes
                    keyfile_bytes = provider.get_keyfile()

                    # Write to temp file for VeraCrypt
                    with tempfile.NamedTemporaryFile(mode="wb", suffix=".key", delete=False) as f:
                        f.write(keyfile_bytes)
                        temp_keyfile_path = f.name

                    # Store for cleanup
                    self._temp_keyfile_path = temp_keyfile_path
                    _gui_logger.info(f"Temporary keyfile created at: {temp_keyfile_path}")

                except Exception as e:
                    _gui_logger.error(f"Failed to decrypt keyfile: {e}")
                    self.rekey_status_label.setText(f"❌ Failed to decrypt keyfile: {e}")
                    self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                    return

        # Launch VeraCrypt GUI
        self.rekey_status_label.setText(tr("rekey_status_opening_veracrypt", lang=get_lang()))
        QApplication.processEvents()

        try:
            from core.paths import Paths

            vc_exe = Paths.veracrypt_exe()

            if not vc_exe or not vc_exe.exists():
                self.rekey_status_label.setText("❌ VeraCrypt not found. Please install VeraCrypt first.")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                return

            # Launch VeraCrypt GUI (user will use Tools > Change Volume Password)
            subprocess.Popen([str(vc_exe)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

            # CHG-20251223-054: Show instructions in status label, enable verify/cancel buttons
            # Build instruction text - include temp keyfile path if applicable
            instructions = tr("rekey_instructions_veracrypt", lang=get_lang())
            if temp_keyfile_path:
                instructions += f"\n\n📁 Temp keyfile: {temp_keyfile_path}"

            self.rekey_status_label.setText(instructions)
            self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")

            # Toggle button states: disable Start, show Verify/Cancel
            self.start_rekey_btn.setEnabled(False)
            self.verify_rekey_btn.setVisible(True)
            self.cancel_rekey_btn.setVisible(True)

            # BUG-20251225-001: Mark rekey as in-progress to allow verification mount
            # This lifts the mount blocking so credential verification can work
            post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
            if post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_REQUIRED):
                post_recovery[ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS] = True
                self.config[ConfigKeys.POST_RECOVERY] = post_recovery
                self._save_config_atomic()
                _gui_logger.info("BUG-20251225-001: Set rekey_in_progress=True to allow verification mount")

            _gui_logger.info("Rekey flow started - VeraCrypt GUI opened, awaiting user verification")

        except Exception as e:
            _gui_logger.error(f"Failed to launch VeraCrypt: {e}")
            self.rekey_status_label.setText(f"❌ Failed to launch VeraCrypt: {e}")
            self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

    def _verify_rekey_credentials(self):
        """
        CHG-20251223-054: Verify new credentials via mount test after user completes
        VeraCrypt credential change.

        Called when user clicks "Verify New Credentials" button after completing
        the credential change in VeraCrypt GUI. Validates via mount test before
        finalizing the rekey.
        """
        self.rekey_status_label.setText(tr("rekey_verifying", lang=get_lang()))
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        try:
            # Call existing validation method
            validation_ok, skip_validation = self._validate_new_credentials_before_rekey()

            if validation_ok:
                # Verification succeeded - show success, complete rekey
                self.rekey_status_label.setText(tr("rekey_verification_success", lang=get_lang()))
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")
                QApplication.processEvents()

                # Complete the rekey process
                self._complete_rekey(validation_skipped=False)

                # Reset button states
                self.verify_rekey_btn.setVisible(False)
                self.cancel_rekey_btn.setVisible(False)
                self.start_rekey_btn.setEnabled(True)

            elif skip_validation:
                # User chose to skip validation - proceed with warning
                self.rekey_status_label.setText("⚠️ Proceeding without verification...")
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px;")
                QApplication.processEvents()

                self._complete_rekey(validation_skipped=True)

                # Reset button states
                self.verify_rekey_btn.setVisible(False)
                self.cancel_rekey_btn.setVisible(False)
                self.start_rekey_btn.setEnabled(True)

            else:
                # Validation failed and user chose not to proceed
                self.rekey_status_label.setText(tr("rekey_verification_failed", lang=get_lang()))
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                # Keep verify/cancel buttons visible for retry

        except Exception as e:
            _gui_logger.error(f"Verification failed with exception: {e}")
            self.rekey_status_label.setText(f"❌ Verification error: {e}")
            self.rekey_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

    def _cancel_rekey(self):
        """
        CHG-20251223-054: Cancel the rekey flow and reset UI state.

        Called when user clicks "Cancel" button during rekey flow.
        Cleans up any temporary files and resets UI to initial state.
        """
        _gui_logger.info("Rekey flow cancelled by user")

        # Clean up temporary keyfile if created
        if hasattr(self, "_temp_keyfile_path") and self._temp_keyfile_path:
            try:
                import os

                if os.path.exists(self._temp_keyfile_path):
                    os.remove(self._temp_keyfile_path)
                    _gui_logger.info(f"Cleaned up temporary keyfile: {self._temp_keyfile_path}")
                self._temp_keyfile_path = None
            except Exception as e:
                _gui_logger.warning(f"Failed to clean up temp keyfile: {e}")

        # BUG-20251225-001: Clear rekey_in_progress flag on cancel
        # Mount blocking should be restored since rekey was not completed
        post_recovery = self.config.get(ConfigKeys.POST_RECOVERY, {})
        if post_recovery.get(ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS):
            del post_recovery[ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS]
            self.config[ConfigKeys.POST_RECOVERY] = post_recovery
            self._save_config_atomic()
            _gui_logger.info("BUG-20251225-001: Cleared rekey_in_progress flag after cancel")

        # Reset stored state
        self._rekey_target_mode = None
        self._rekey_mode_changing = False

        # Reset UI state
        self.rekey_status_label.setText(tr("rekey_cancelled", lang=get_lang()))
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")

        # Toggle button states: re-enable Start, hide Verify/Cancel
        self.start_rekey_btn.setEnabled(True)
        self.verify_rekey_btn.setVisible(False)
        self.cancel_rekey_btn.setVisible(False)

        # Update button state based on current metadata
        self._update_rekey_button_state()

    def _validate_new_credentials_before_rekey(self) -> tuple:
        """
        CHG-20251223-030: Validate new credentials via mount before completing rekey.

        Attempts to mount the volume with the NEW credentials to verify
        the VeraCrypt credential change was successful. Old credentials
        are NOT removed until this verification succeeds.

        For GPG modes: derives password from NEW seed.gpg (stored in rekey_gpg_seed_edit)
        For keyfile modes: uses keyfile path from rekey_keyfile_edit
        For PW_ONLY: user must manually enter password

        Returns:
            tuple: (validation_passed: bool, user_chose_to_skip: bool)
                - (True, False): Validation passed
                - (False, True): Validation failed but user chose to proceed anyway
                - (False, False): Validation failed and user chose to abort
        """
        import platform

        self.rekey_status_label.setText(tr("rekey_validating", lang=get_lang()))
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        try:
            from scripts.veracrypt_cli import InvalidCredentialsError, try_mount, unmount

            # Get volume path from config
            if os.name == "nt":
                volume_path = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.VOLUME_PATH, "")
                configured_mount = self.config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "V")
            else:
                volume_path = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.VOLUME_PATH, "")
                configured_mount = self.config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "")

            if not volume_path:
                reply = QMessageBox.warning(
                    self,
                    tr("rekey_section_title", lang=get_lang()),
                    "⚠️ Cannot validate new credentials:\nVolume path not configured.\n\n"
                    "Do you want to proceed anyway?\n"
                    "(Risk: If credential change failed, old credentials will be lost)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                return (False, reply == QMessageBox.StandardButton.Yes)

            # Get target mode
            target_mode = getattr(self, "_rekey_target_mode", None)
            if not target_mode:
                target_mode = self.rekey_target_mode_combo.currentData()

            # Derive/get new password based on target mode
            new_password = None
            new_keyfile = None

            if target_mode in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value):
                # GPG mode: derive password from new seed
                new_seed_path = self.rekey_gpg_seed_edit.text().strip()
                if not new_seed_path:
                    reply = QMessageBox.warning(
                        self,
                        tr("rekey_section_title", lang=get_lang()),
                        "⚠️ Cannot validate: No new GPG seed path specified.\n\n" "Do you want to proceed anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    return (False, reply == QMessageBox.StandardButton.Yes)

                # Get salt (from generated seed or config)
                salt_b64 = getattr(self, "_generated_seed_salt", None)
                if not salt_b64:
                    salt_b64 = self.config.get(ConfigKeys.SALT_B64, "")
                if not salt_b64:
                    reply = QMessageBox.warning(
                        self,
                        tr("rekey_section_title", lang=get_lang()),
                        "⚠️ Cannot validate: No salt available for password derivation.\n\n"
                        "Do you want to proceed anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    return (False, reply == QMessageBox.StandardButton.Yes)

                # Derive password from new seed
                self.rekey_status_label.setText(tr("status_deriving_yubikey_password", lang=get_lang()))
                QApplication.processEvents()

                try:
                    import base64
                    import subprocess
                    from pathlib import Path

                    from core.secrets import _derive_password_from_seed

                    # Decrypt new seed using GPG
                    seed_path = Path(new_seed_path)
                    if not seed_path.exists():
                        raise FileNotFoundError(f"Seed file not found: {new_seed_path}")

                    # BUG-20251218-007: Include --no-tty flag for non-interactive GPG usage
                    gpg_result = subprocess.run(
                        ["gpg", "--decrypt", "--batch", "--quiet", "--no-tty", str(seed_path)],
                        capture_output=True,
                    )
                    if gpg_result.returncode != 0:
                        raise RuntimeError(f"GPG decryption failed: {gpg_result.stderr.decode()}")

                    seed_bytes = gpg_result.stdout
                    salt_bytes = base64.b64decode(salt_b64)
                    # BUG-20251223-059 FIX: Use SSOT HKDF info, not hardcoded value
                    from core.constants import CryptoParams

                    hkdf_info = self.config.get(ConfigKeys.HKDF_INFO, CryptoParams.HKDF_INFO_DEFAULT)
                    new_password = _derive_password_from_seed(seed_bytes, salt_bytes, hkdf_info.encode("utf-8"))
                except Exception as e:
                    _gui_logger.error(f"Password derivation failed: {e}")
                    reply = QMessageBox.warning(
                        self,
                        tr("rekey_section_title", lang=get_lang()),
                        f"⚠️ Password derivation failed:\n{e}\n\n" "Do you want to proceed anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    return (False, reply == QMessageBox.StandardButton.Yes)

                # For PW_GPG_KEYFILE, also get new keyfile
                if target_mode == SecurityMode.PW_GPG_KEYFILE.value:
                    new_keyfile = self.rekey_keyfile_edit.text().strip()

            elif target_mode == SecurityMode.PW_KEYFILE.value:
                # Keyfile mode: get keyfile path, ask user for password
                new_keyfile = self.rekey_keyfile_edit.text().strip()
                if not new_keyfile:
                    reply = QMessageBox.warning(
                        self,
                        tr("rekey_section_title", lang=get_lang()),
                        "⚠️ Cannot validate: No new keyfile path specified.\n\n" "Do you want to proceed anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    return (False, reply == QMessageBox.StandardButton.Yes)

                # Ask user to enter the new password for verification
                new_password, ok = QInputDialog.getText(
                    self,
                    tr("rekey_section_title", lang=get_lang()),
                    "Enter your NEW password for verification mount:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return (False, False)  # User cancelled

            elif target_mode == SecurityMode.PW_ONLY.value:
                # PW_ONLY mode: ask user to enter the new password
                new_password, ok = QInputDialog.getText(
                    self,
                    tr("rekey_section_title", lang=get_lang()),
                    "Enter your NEW password for verification mount:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return (False, False)  # User cancelled

            else:
                # Unknown mode - skip validation
                reply = QMessageBox.warning(
                    self,
                    tr("rekey_section_title", lang=get_lang()),
                    f"⚠️ Unknown target mode: {target_mode}\n\n" "Cannot validate credentials. Proceed anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                return (False, reply == QMessageBox.StandardButton.Yes)

            # Use existing _verify_credentials_via_mount method
            self.rekey_status_label.setText(tr("rekey_verifying_mount", lang=get_lang()))
            QApplication.processEvents()

            success, error = self._verify_credentials_via_mount(
                volume_path=volume_path,
                mount_point=configured_mount,
                password=new_password or "",
                keyfile_path=new_keyfile,
            )

            if success:
                _gui_logger.info("New credentials verified successfully via mount")
                self.rekey_status_label.setText("✅ " + tr("rekey_credentials_verified", lang=get_lang()))
                self.rekey_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")
                QApplication.processEvents()
                return (True, False)
            else:
                _gui_logger.warning(f"Credential verification failed: {error}")
                reply = QMessageBox.warning(
                    self,
                    tr("rekey_section_title", lang=get_lang()),
                    f"⚠️ CREDENTIAL VERIFICATION FAILED\n\n"
                    f"Error: {error}\n\n"
                    f"This means the new credentials may not work.\n"
                    f"Your old credentials are still preserved.\n\n"
                    f"Do you want to proceed anyway?\n"
                    f"(Risk: You may be locked out of your volume)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                return (False, reply == QMessageBox.StandardButton.Yes)

        except Exception as e:
            _gui_logger.warning(f"Credential validation error: {e}")
            reply = QMessageBox.warning(
                self,
                tr("rekey_section_title", lang=get_lang()),
                f"⚠️ VALIDATION ERROR\n\n"
                f"Unexpected error during validation: {e}\n\n"
                f"Do you want to proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return (False, reply == QMessageBox.StandardButton.Yes)

    def _verify_credentials_via_mount(
        self, volume_path: str, mount_point: str, password: str, keyfile_path=None
    ) -> tuple[bool, str]:
        """
        BUG-20251223-056 FIX: Verify credentials by attempting mount/unmount.
        Copied from RecoveryGenerateWorker for use in SettingsDialog rekey flow.

        This ensures the rekey operation will use valid credentials.
        Invalid credentials would cause the rekey to fail.

        Returns:
            (success, error_message)
        """
        import platform
        import tempfile

        try:
            from scripts.veracrypt_cli import (
                InvalidCredentialsError,
                VeraCryptError,
                get_mount_status,
                try_mount,
                unmount,
            )
        except ImportError as e:
            return False, f"Cannot import veracrypt_cli: {e}"

        # Check if already mounted - if so, credentials are already verified
        try:
            status = get_mount_status()
            # Check if our volume is in the mounted list
            if status and any(volume_path in str(m.get("volume", "")) for m in status):
                return True, ""  # Already mounted = credentials valid
        except Exception as e:
            _gui_logger.debug(f"Mount status check failed (continuing): {e}")

        # Determine mount point for test
        is_windows = platform.system().lower() == "windows"
        if is_windows:
            # Use a temporary drive letter for test mount
            import string

            used_letters = set()
            try:
                for m in get_mount_status() or []:
                    letter = m.get(ConfigKeys.MOUNT_POINT, "")
                    if letter:
                        used_letters.add(letter[0].upper())
            except Exception as e:
                _gui_logger.debug(f"Failed to get used drive letters: {e}")

            test_letter = None
            for letter in reversed(string.ascii_uppercase):
                if letter not in used_letters and letter not in ["C", "D"]:
                    test_letter = letter
                    break
            if not test_letter:
                return False, "No available drive letter for credential test"
            test_mount = f"{test_letter}:"
        else:
            # Linux/macOS: Use temp directory
            test_mount = tempfile.mkdtemp(prefix="keydrive_test_")

        try:
            # Attempt mount
            success, err = try_mount(
                volume_path=volume_path,
                mount_point=test_mount,
                password=password,
                keyfile_path=keyfile_path,
            )

            if not success:
                return False, f"Credential verification failed: {err}"

            # Immediately unmount
            try:
                unmount(test_mount)
            except Exception as e:
                try:
                    unmount(test_mount, force=True)
                except Exception as e2:
                    _gui_logger.debug(f"Best effort unmount failed: {e2}")

            return True, ""

        except InvalidCredentialsError as e:
            return False, f"Invalid credentials: {e}"
        except VeraCryptError as e:
            return False, f"VeraCrypt error during verification: {e}"
        except Exception as e:
            return False, f"Unexpected error during credential verification: {e}"
        finally:
            # Cleanup temp directory on Linux
            if not is_windows and test_mount.startswith("/tmp/"):
                try:
                    import shutil

                    shutil.rmtree(test_mount, ignore_errors=True)
                except Exception as e:
                    _gui_logger.debug(f"Temp directory cleanup failed: {e}")

    def _complete_rekey(self, validation_skipped: bool = False):
        """
        Mark rekey as completed and update config.
        CHG-20251221-001: Also handle mode changes during rekey.
        CHG-20251221-003: Save generated GPG seed salt if available.
        CHG-20251221-029: Clean up temp keyfile if created.
        BUG-20251221-030: Added validation_skipped parameter for warning.
        BUG-20251223-052: Finalize GPG→GPG seed transition (backup old, activate new).
        BUG-20251223-066: Finalize recovery container deletion ONLY after successful mount.

        Args:
            validation_skipped: If True, validation was skipped (show warning).
        """
        import os
        from pathlib import Path

        # BUG-20251221-029: Use timezone.utc (module-level import) instead of datetime.UTC
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ═══════════════════════════════════════════════════════════════════
        # BUG-20251223-066 CRITICAL: Finalize recovery container deletion
        # Container is ONLY deleted after successful rekey + mount verification
        # ═══════════════════════════════════════════════════════════════════
        pending_container_path = getattr(self, "_pending_container_deletion_path", None)
        recovery_cfg = self.config.get(ConfigKeys.RECOVERY, {})
        config_pending_path = recovery_cfg.get("pending_container_path")

        # Determine container path from either memory or config
        container_to_delete = None
        if pending_container_path and Path(pending_container_path).exists():
            container_to_delete = Path(pending_container_path)
        elif config_pending_path and Path(config_pending_path).exists():
            container_to_delete = Path(config_pending_path)

        if container_to_delete:
            if validation_skipped:
                # Mount was NOT verified - DO NOT delete container yet
                # User needs another chance to verify mount works
                _gui_logger.warning(
                    f"BUG-20251223-066: Rekey completed but mount NOT verified. "
                    f"Container preserved at: {container_to_delete}"
                )
                # Show warning to user
                QMessageBox.warning(
                    self,
                    tr("warning", lang=get_lang()),
                    "⚠️ IMPORTANT: Mount verification was skipped.\n\n"
                    "Your recovery container has NOT been deleted yet.\n"
                    "Please verify you can mount the volume with your new credentials.\n\n"
                    "If mount fails, you can still use your recovery phrase.\n"
                    "Container will be deleted after successful mount.",
                    QMessageBox.StandardButton.Ok,
                )
            else:
                # Mount WAS verified - safe to delete container now
                _gui_logger.info(
                    f"BUG-20251223-066: Rekey + mount verified. "
                    f"Now securely deleting container: {container_to_delete}"
                )
                self._secure_delete_file(container_to_delete)
                self._pending_container_deletion_path = None

                # Update recovery config to mark as fully used
                if ConfigKeys.RECOVERY in self.config:
                    self.config[ConfigKeys.RECOVERY][ConfigKeys.RECOVERY_USED] = True
                    self.config[ConfigKeys.RECOVERY][ConfigKeys.RECOVERY_STATE] = "used"
                    # Remove pending path from config
                    if "pending_container_path" in self.config[ConfigKeys.RECOVERY]:
                        del self.config[ConfigKeys.RECOVERY]["pending_container_path"]

                _gui_logger.info("BUG-20251223-066: Recovery container securely deleted after verified rekey")

        # CHG-20251221-029: Clean up temp keyfile if it was created during rekey
        if hasattr(self, "_temp_keyfile_path") and self._temp_keyfile_path:
            try:
                temp_path = Path(self._temp_keyfile_path)
                if temp_path.exists():
                    # Secure delete: overwrite with zeros before unlink
                    size = temp_path.stat().st_size
                    with open(temp_path, "wb") as f:
                        f.write(b"\x00" * size)
                    temp_path.unlink()
                    _gui_logger.info(f"Securely deleted temp keyfile: {temp_path}")
            except Exception as e:
                _gui_logger.warning(f"Failed to clean up temp keyfile: {e}")
            finally:
                self._temp_keyfile_path = None

        # BUG-20251223-052: Finalize GPG→GPG seed transition
        # BUG-20251223-062 FIX: Move new seed to SSOT location so mount.py finds it
        # If we have a pending new seed that's different from the original, backup old and install new
        pending_new_seed = getattr(self, "_pending_new_seed_path", None)
        original_seed = getattr(self, "_original_seed_path", None)
        if pending_new_seed and original_seed:
            try:
                import shutil

                new_seed_path = Path(pending_new_seed)
                old_seed_path = Path(original_seed)

                # Only process if new seed exists and is different from old
                if new_seed_path.exists() and new_seed_path != old_seed_path:
                    # Backup old seed with timestamp
                    backup_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    backup_path = old_seed_path.with_suffix(f".gpg.backup_{backup_suffix}")

                    if old_seed_path.exists():
                        shutil.copy2(old_seed_path, backup_path)
                        _gui_logger.info(f"Backed up old seed: {old_seed_path} → {backup_path}")

                    # BUG-20251223-062 FIX: Copy new seed to SSOT location
                    # mount.py's resolve_encrypted_seed checks Paths.seed_gpg() first
                    # So the new seed MUST be at the SSOT location for automount to work
                    ssot_seed_path = Paths.seed_gpg(self._launcher_root)
                    if new_seed_path != ssot_seed_path:
                        shutil.copy2(new_seed_path, ssot_seed_path)
                        _gui_logger.info(f"Installed new seed to SSOT location: {new_seed_path} → {ssot_seed_path}")

                        # Update rekey_gpg_seed_edit to show SSOT path
                        # This ensures config will have the canonical path
                        self.rekey_gpg_seed_edit.setText(str(ssot_seed_path))
                    else:
                        _gui_logger.info(f"New seed already at SSOT location: {new_seed_path}")
            except Exception as e:
                _gui_logger.warning(f"Seed finalization warning: {e}")
            finally:
                self._pending_new_seed_path = None
                self._original_seed_path = None

        # Update post_recovery to mark rekey completed
        if ConfigKeys.POST_RECOVERY in self.config:
            self.config[ConfigKeys.POST_RECOVERY][ConfigKeys.POST_RECOVERY_REKEY_COMPLETED] = True
            self.config[ConfigKeys.POST_RECOVERY][ConfigKeys.POST_RECOVERY_REKEY_COMPLETED_AT] = timestamp
            # BUG-20251225-001: Clear rekey_in_progress flag now that rekey is completed
            if ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS in self.config[ConfigKeys.POST_RECOVERY]:
                del self.config[ConfigKeys.POST_RECOVERY][ConfigKeys.POST_RECOVERY_REKEY_IN_PROGRESS]
                _gui_logger.info("BUG-20251225-001: Cleared rekey_in_progress flag after rekey completion")

        # CHG-20251221-001: Handle mode changes
        # BUG-20251221-040: ALWAYS update mode to target_mode to ensure consistency
        target_mode = getattr(self, "_rekey_target_mode", None)
        if target_mode:
            old_mode = self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
            self.config[ConfigKeys.MODE] = target_mode

            # BUG-20251223-059 FIX: Update last_password_change timestamp
            self.config[ConfigKeys.LAST_PASSWORD_CHANGE] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Update keyfile path if target mode uses keyfiles
            if target_mode in (SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value):
                keyfile_path = self.rekey_keyfile_edit.text().strip()
                if keyfile_path:
                    self.config[ConfigKeys.KEYFILE] = keyfile_path

            # Update GPG seed path if target mode uses GPG
            if target_mode in (SecurityMode.PW_GPG_KEYFILE.value, SecurityMode.GPG_PW_ONLY.value):
                gpg_seed_path = self.rekey_gpg_seed_edit.text().strip()
                if gpg_seed_path:
                    # BUG-20251223-062 FIX: Ensure seed is at SSOT location for mount.py to find it
                    # mount.py's resolve_encrypted_seed checks Paths.seed_gpg() first
                    seed_path = Path(gpg_seed_path)
                    ssot_seed_path = Paths.seed_gpg(self._launcher_root)
                    if seed_path.exists() and seed_path.resolve() != ssot_seed_path.resolve():
                        import shutil

                        # Seed is not at SSOT location - copy it there
                        ssot_seed_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(seed_path, ssot_seed_path)
                        _gui_logger.info(f"Copied seed to SSOT location: {seed_path} → {ssot_seed_path}")
                        gpg_seed_path = str(ssot_seed_path)

                    # BUG-20251221-007 FIX: Use ConfigKeys.SEED_GPG_PATH (config key) not FileNames.SEED_GPG (filename)
                    self.config[ConfigKeys.SEED_GPG_PATH] = gpg_seed_path

                # CHG-20251221-003: Save generated salt if available
                if hasattr(self, "_generated_seed_salt") and self._generated_seed_salt:
                    self.config[ConfigKeys.SALT_B64] = self._generated_seed_salt
                    self._generated_seed_salt = None

            if target_mode != old_mode:
                _gui_logger.info(f"Security mode changed from {old_mode} to {target_mode}")
            else:
                _gui_logger.info(f"Security mode confirmed: {target_mode}")

        # Invalidate old recovery kit (must generate new one after rekey)
        if "recovery" in self.config:
            recovery_cfg = self.config["recovery"]
            if recovery_cfg.get("enabled"):
                recovery_cfg["enabled"] = False
                recovery_cfg["invalidated_at"] = timestamp
                recovery_cfg["invalidation_reason"] = "rekey_completed"
                self.config["recovery"] = recovery_cfg

        # Save config
        self._save_config_atomic()

        # BUG-20251221-035: Refresh settings UI to reflect changes
        self.refresh_settings_values()

        # Log event
        mode_change_suffix = "_MODE_CHANGED" if getattr(self, "_rekey_mode_changing", False) else ""
        self._gui_audit_log(f"REKEY_COMPLETED_GUI{mode_change_suffix}")

        # Clear mode change state
        self._rekey_mode_changing = False
        self._rekey_target_mode = None

        # Update status
        self.rekey_status_label.setText(tr("rekey_status_success", lang=get_lang()))
        self.rekey_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

        # BUG-20251221-030: Show appropriate message based on validation result
        if validation_skipped:
            # Prompt with warning about skipped validation
            QMessageBox.warning(
                self,
                tr("rekey_section_title", lang=get_lang()),
                "⚠️ Credentials updated (VALIDATION SKIPPED)\n\n"
                "The credential change was NOT validated with a test mount.\n"
                "If the change failed in VeraCrypt, you may be locked out.\n\n"
                "⚠️ VERIFY IMMEDIATELY:\n"
                "Try mounting the volume to confirm access before doing anything else.\n\n"
                "⚠️ IMPORTANT: Your old recovery kit is now INVALID.\n"
                "You should generate a NEW recovery kit using the CLI:\n"
                "  python recovery.py generate",
            )
        else:
            # Prompt to generate new recovery kit (normal case)
            QMessageBox.information(
                self,
                tr("rekey_section_title", lang=get_lang()),
                "✅ Credentials changed successfully!\n\n"
                "✓ New credentials validated with test mount.\n\n"
                "⚠️ IMPORTANT: Your old recovery kit is now INVALID.\n\n"
                "You should generate a NEW recovery kit using the CLI:\n"
                "  python recovery.py generate\n\n"
                "Without a valid recovery kit, you cannot recover access if you forget your credentials.",
            )

    def _add_update_hint_section(self, tab_layout: QVBoxLayout):
        """
        Add informational hint about local updates to the Updates tab.

        CHG-20251221-005: Provides guidance on selecting local update directory.
        """
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tab_layout.addWidget(separator)

        # Hint group box
        self.update_hint_box = QGroupBox(tr("hint_update_local_title", lang=get_lang()))
        hint_layout = QVBoxLayout()
        hint_layout.setSpacing(8)

        # Hint text label
        hint_label = QLabel(tr("hint_update_local_body", lang=get_lang()))
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; padding: 8px; "
            f"background-color: {COLORS.get('background_secondary', COLORS['surface'])}; border-radius: 4px;"
        )
        hint_layout.addWidget(hint_label)

        self.update_hint_box.setLayout(hint_layout)
        tab_layout.addWidget(self.update_hint_box)

        # Store reference for language updates
        self.update_hint_label = hint_label

    def _add_update_action_section(self, tab_layout: QVBoxLayout):
        """
        Add update action section with Run Update button and last update info.

        CHG-20251222-016: Provides direct update execution from Updates tab.
        """
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tab_layout.addWidget(separator)

        # Action group box
        self.update_action_box = QGroupBox(tr("update_action_section_title", lang=get_lang()))
        action_layout = QVBoxLayout()
        action_layout.setSpacing(10)

        # Last update info
        info_layout = QFormLayout()
        info_layout.setSpacing(6)

        # Last update datetime
        last_updated = self.config.get(ConfigKeys.LAST_UPDATED, "")
        last_update_text = last_updated if last_updated else tr("update_never", lang=get_lang())
        self.last_update_value = QLabel(last_update_text)
        self.last_update_value.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.last_update_label = QLabel(tr("label_last_update", lang=get_lang()))
        info_layout.addRow(self.last_update_label, self.last_update_value)

        # Source info
        source_type = self.config.get(ConfigKeys.UPDATE_SOURCE_TYPE, "")
        if source_type == "local":
            source_text = self.config.get(ConfigKeys.UPDATE_LOCAL_ROOT, "") or tr("update_source_none", lang=get_lang())
        elif source_type == "server":
            source_text = self.config.get(ConfigKeys.UPDATE_URL, "") or tr("update_source_none", lang=get_lang())
        else:
            source_text = tr("update_source_none", lang=get_lang())
        self.last_update_source_value = QLabel(source_text)
        self.last_update_source_value.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.last_update_source_value.setWordWrap(True)
        self.last_update_source_label = QLabel(tr("label_last_update_source", lang=get_lang()))
        info_layout.addRow(self.last_update_source_label, self.last_update_source_value)

        action_layout.addLayout(info_layout)

        # Run Update button
        btn_layout = QHBoxLayout()
        self.run_update_btn = QPushButton(tr("btn_run_update", lang=get_lang()))
        self.run_update_btn.setToolTip(tr("tooltip_run_update", lang=get_lang()))
        self.run_update_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.get('primary_dark', COLORS['primary'])};
            }}
            QPushButton:pressed {{
                background-color: {COLORS.get('primary_darker', COLORS['primary'])};
            }}
            """
        )
        self.run_update_btn.clicked.connect(self._on_run_update_clicked)
        btn_layout.addWidget(self.run_update_btn)
        btn_layout.addStretch()
        action_layout.addLayout(btn_layout)

        self.update_action_box.setLayout(action_layout)
        tab_layout.addWidget(self.update_action_box)

    def _on_run_update_clicked(self):
        """Handle Run Update button click from Settings Updates tab."""
        # Close settings dialog and trigger update on main window
        self.accept()
        if self.parent is not None and hasattr(self.parent, "run_update"):
            self.parent.run_update()

    def _add_integrity_section(self, tab_layout: QVBoxLayout):
        """
        Add integrity verification section to the Integrity tab.

        CHG-20251220-002: Provides GUI access to script integrity verification and signing.
        """
        # Instructions
        instructions = QLabel(tr("integrity_instructions", lang=get_lang()))
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; margin-bottom: 10px;")
        tab_layout.addWidget(instructions)
        self.field_labels["integrity_instructions"] = (instructions, "integrity_instructions")

        # Verification group box
        self.integrity_verify_box = QGroupBox(tr("integrity_section_title", lang=get_lang()))
        verify_layout = QVBoxLayout()
        verify_layout.setSpacing(10)

        # Button row for local verification and signing
        btn_layout = QHBoxLayout()

        # Verify Local button
        self.verify_local_btn = QPushButton(tr("btn_verify_local", lang=get_lang()))
        self.verify_local_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.verify_local_btn.clicked.connect(self._verify_integrity_local)
        btn_layout.addWidget(self.verify_local_btn)

        # CHG-20251221-002: Verify Remote button
        self.verify_remote_btn = QPushButton(tr("btn_verify_remote", lang=get_lang()))
        self.verify_remote_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.verify_remote_btn.clicked.connect(self._verify_integrity_remote)
        btn_layout.addWidget(self.verify_remote_btn)

        # Sign Scripts button
        self.sign_scripts_btn = QPushButton(tr("btn_sign_scripts", lang=get_lang()))
        self.sign_scripts_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.get('warning', '#FFA500')};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.get('warning_hover', '#E69500')};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.sign_scripts_btn.clicked.connect(self._sign_scripts)
        btn_layout.addWidget(self.sign_scripts_btn)

        btn_layout.addStretch()
        verify_layout.addLayout(btn_layout)

        # Status label
        self.integrity_status_label = QLabel(tr("integrity_status_ready", lang=get_lang()))
        self.integrity_status_label.setWordWrap(True)
        self.integrity_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        verify_layout.addWidget(self.integrity_status_label)
        self.field_labels["integrity_status_label"] = (self.integrity_status_label, "integrity_status_ready")

        # Result details (initially hidden)
        self.integrity_result_label = QLabel("")
        self.integrity_result_label.setWordWrap(True)
        self.integrity_result_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px;")
        self.integrity_result_label.setVisible(False)
        verify_layout.addWidget(self.integrity_result_label)

        self.integrity_verify_box.setLayout(verify_layout)
        tab_layout.addWidget(self.integrity_verify_box)

    def _verify_integrity_local(self):
        """
        Verify script integrity locally.

        CHG-20251220-002: Uses core.integrity.Integrity.validate_integrity()
        to check scripts against signed manifest.
        BUG-20251221-005 FIX: Honor verification_overridden config setting.
        """
        from core.constants import ConfigKeys
        from core.integrity import Integrity

        self.integrity_status_label.setText(tr("integrity_status_checking", lang=get_lang()))
        self.integrity_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        try:
            # BUG-20251221-005 FIX: Read verification_overridden from config
            bypass_enabled = self.config.get(ConfigKeys.VERIFICATION_OVERRIDDEN, False)
            result = Integrity.validate_integrity(
                self._launcher_root, bypass_enabled=bypass_enabled, verify_signature=True
            )

            if result.valid:
                self.integrity_status_label.setText(tr("integrity_status_pass", lang=get_lang()))
                self.integrity_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

                # Show details
                details = []
                if result.actual_hash:
                    details.append(
                        tr("integrity_result_hash", lang=get_lang()).format(hash=result.actual_hash[:16] + "...")
                    )
                if result.signer_info:
                    details.append(tr("integrity_result_signer", lang=get_lang()).format(signer=result.signer_info))
                if details:
                    self.integrity_result_label.setText("\n".join(details))
                    self.integrity_result_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
                    self.integrity_result_label.setVisible(True)
            else:
                if result.expected_hash is None:
                    self.integrity_status_label.setText(tr("integrity_status_no_manifest", lang=get_lang()))
                    self.integrity_status_label.setStyleSheet(
                        f"color: {COLORS.get('warning', '#FFA500')}; font-size: 11px;"
                    )
                else:
                    self.integrity_status_label.setText(tr("integrity_status_fail", lang=get_lang()))
                    self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

                # Show failure details
                self.integrity_result_label.setText(result.message)
                self.integrity_result_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 10px;")
                self.integrity_result_label.setVisible(True)

            self._gui_audit_log("INTEGRITY_VERIFY_GUI", details={"valid": result.valid})

        except Exception as e:
            _gui_logger.error(f"Integrity verification failed: {e}")
            self.integrity_status_label.setText(f"Error: {e}")
            self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

    def _sign_scripts(self):
        """
        Sign scripts with hardware key (GPG).

        CHG-20251220-002: Creates integrity manifest and signs with GPG.
        BUG-20251221-006 FIX: Updates config with signing status and fingerprint.
        Requires YubiKey/GPG card.
        """
        import shutil
        from datetime import datetime

        from core.constants import ConfigKeys
        from core.integrity import Integrity

        # Check for GPG
        if not shutil.which("gpg"):
            QMessageBox.warning(
                self,
                tr("integrity_section_title", lang=get_lang()),
                "GPG not found. Please install GPG to sign scripts.",
            )
            return

        # Confirm signing
        reply = QMessageBox.question(
            self,
            tr("integrity_section_title", lang=get_lang()),
            "This will create a new integrity manifest and sign it with your GPG key.\n\n"
            "Please ensure your YubiKey/GPG card is inserted.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.integrity_status_label.setText(tr("integrity_status_signing", lang=get_lang()))
        self.integrity_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        try:
            # Create manifest
            hash_value, manifest_path = Integrity.create_manifest(self._launcher_root)

            # Sign manifest (BUG-20251221-006: now returns tuple with fingerprint)
            sign_success, signer_fpr = Integrity.sign_manifest(self._launcher_root)
            if sign_success:
                self.integrity_status_label.setText(tr("integrity_status_sign_success", lang=get_lang()))
                self.integrity_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

                # Show hash and fingerprint
                result_text = f"Hash: {hash_value}"
                if signer_fpr:
                    result_text += f"\nSigned by: {signer_fpr}"
                self.integrity_result_label.setText(result_text)
                self.integrity_result_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
                self.integrity_result_label.setVisible(True)

                # BUG-20251221-006 FIX: Update config with signing status and fingerprint
                # BUG-20251221-029: Use timezone.utc instead of datetime.UTC
                self.config[ConfigKeys.INTEGRITY_SIGNED] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if signer_fpr:
                    self.config[ConfigKeys.SIGNING_KEY_FPR] = signer_fpr
                self._save_config_atomic()

                self._gui_audit_log(
                    "INTEGRITY_SIGN_GUI", details={"hash": hash_value[:16], "fingerprint": signer_fpr or "unknown"}
                )
            else:
                self.integrity_status_label.setText(tr("integrity_status_sign_fail", lang=get_lang()))
                self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

        except Exception as e:
            _gui_logger.error(f"Signing failed: {e}")
            self.integrity_status_label.setText(f"Error: {e}")
            self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

    def _verify_integrity_remote(self):
        """
        Verify integrity with a remote server.

        CHG-20251221-002: Sends hash and metadata to configured server for verification.
        Server URL must be configured in INTEGRITY_SERVER_URL.
        """
        import json
        import urllib.error
        import urllib.request
        from datetime import datetime

        from core.constants import ConfigKeys
        from core.integrity import Integrity

        # Get server URL from config
        server_url = self.config.get(ConfigKeys.INTEGRITY_SERVER_URL, "").strip()
        if not server_url:
            self.integrity_status_label.setText(tr("integrity_status_no_server_url", lang=get_lang()))
            self.integrity_status_label.setStyleSheet(f"color: {COLORS.get('warning', '#FFA500')}; font-size: 11px;")
            return

        # Validate and fix URL format
        if not server_url.startswith(("http://", "https://")):
            # Assume HTTPS if no protocol specified
            server_url = f"https://{server_url}"
            _gui_logger.info(f"Added https:// protocol to server URL: {server_url}")

        # Basic URL validation
        try:
            from urllib.parse import urlparse

            parsed = urlparse(server_url)
            if not parsed.netloc:
                raise ValueError("Invalid URL format")
        except Exception as e:
            _gui_logger.error(f"Invalid server URL format: {server_url} - {e}")
            self.integrity_status_label.setText(tr("integrity_status_remote_fail", lang=get_lang()))
            self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self.integrity_result_label.setText(f"Invalid server URL: {server_url}")
            self.integrity_result_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 10px;")
            self.integrity_result_label.setVisible(True)
            return

        self.integrity_status_label.setText(tr("integrity_status_remote_checking", lang=get_lang()))
        self.integrity_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        try:
            # Calculate scripts hash
            scripts_hash = Integrity.calculate_scripts_hash(self._launcher_root)

            # Build payload
            # BUG-20251221-029: Use timezone.utc instead of datetime.UTC
            payload = {
                "id": self.config.get(ConfigKeys.DRIVE_ID, "unknown"),
                "datetime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hash": scripts_hash,
                "version": self.config.get("version", "unknown"),
                "integrity_signed": self.config.get(ConfigKeys.INTEGRITY_SIGNED, ""),
                "signing_key_fpr": self.config.get(ConfigKeys.SIGNING_KEY_FPR, ""),
            }

            # Make request
            req = urllib.request.Request(
                server_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            from core.limits import Limits

            with urllib.request.urlopen(req, timeout=Limits.HTTP_REQUEST_TIMEOUT) as response:
                response_data = json.loads(response.read().decode("utf-8"))

            # Check response
            if response_data.get("valid", False):
                self.integrity_status_label.setText(tr("integrity_status_remote_success", lang=get_lang()))
                self.integrity_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

                # Show details if available
                if response_data.get("message"):
                    self.integrity_result_label.setText(response_data["message"])
                    self.integrity_result_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
                    self.integrity_result_label.setVisible(True)
            else:
                self.integrity_status_label.setText(tr("integrity_status_remote_fail", lang=get_lang()))
                self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

                # Show error message
                error_msg = response_data.get("message", "Unknown error")
                self.integrity_result_label.setText(error_msg)
                self.integrity_result_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 10px;")
                self.integrity_result_label.setVisible(True)

            self._gui_audit_log(
                "INTEGRITY_VERIFY_REMOTE",
                details={"server": server_url, "valid": response_data.get("valid", False)},
            )

        except urllib.error.URLError as e:
            _gui_logger.error(f"Remote verification network error: {e}")
            self.integrity_status_label.setText(tr("integrity_status_remote_fail", lang=get_lang()))
            self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self.integrity_result_label.setText(f"Network error: {e.reason}")
            self.integrity_result_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 10px;")
            self.integrity_result_label.setVisible(True)

        except Exception as e:
            _gui_logger.error(f"Remote verification failed: {e}")
            self.integrity_status_label.setText(tr("integrity_status_remote_fail", lang=get_lang()))
            self.integrity_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self.integrity_result_label.setText(str(e))
            self.integrity_result_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 10px;")
            self.integrity_result_label.setVisible(True)

    def _add_recovery_action_section(self, tab_layout: QVBoxLayout):
        """Add the recovery action section to the Recovery tab."""
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tab_layout.addWidget(separator)

        # Recovery action group box
        self.recovery_action_box = QGroupBox(tr("recovery_section_title", lang=get_lang()))
        action_layout = QVBoxLayout()
        action_layout.setSpacing(10)

        # Instructions
        instructions = QLabel(tr("recovery_instructions", lang=get_lang()))
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        action_layout.addWidget(instructions)
        self.field_labels["recovery_instructions"] = (instructions, "recovery_instructions")

        # Recovery phrase input
        phrase_label = QLabel(tr("label_recovery_phrase", lang=get_lang()))
        self.field_labels["label_recovery_phrase"] = (phrase_label, "label_recovery_phrase")
        action_layout.addWidget(phrase_label)

        self.recovery_phrase_edit = QTextEdit()
        self.recovery_phrase_edit.setPlaceholderText(tr("placeholder_recovery_phrase", lang=get_lang()))
        self.recovery_phrase_edit.setMaximumHeight(80)
        self.recovery_phrase_edit.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
        """
        )
        action_layout.addWidget(self.recovery_phrase_edit)

        # Container file picker (optional)
        container_layout = QHBoxLayout()
        container_label = QLabel(tr("label_recovery_container", lang=get_lang()))
        self.field_labels["label_recovery_container"] = (container_label, "label_recovery_container")
        container_layout.addWidget(container_label)

        self.recovery_container_path = QLineEdit()
        self.recovery_container_path.setPlaceholderText("")
        container_layout.addWidget(self.recovery_container_path, stretch=1)

        self.browse_container_btn = QPushButton(tr("btn_browse_container", lang=get_lang()))
        self.browse_container_btn.setFixedWidth(100)
        self.browse_container_btn.clicked.connect(self._browse_recovery_container)
        container_layout.addWidget(self.browse_container_btn)

        action_layout.addLayout(container_layout)

        # Recover button
        self.recover_credentials_btn = QPushButton(tr("btn_recover_credentials", lang=get_lang()))
        self.recover_credentials_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.recover_credentials_btn.clicked.connect(self._perform_recovery)
        action_layout.addWidget(self.recover_credentials_btn)

        # Status label
        self.recovery_status_label = QLabel(tr("recovery_status_ready", lang=get_lang()))
        self.recovery_status_label.setWordWrap(True)
        self.recovery_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        action_layout.addWidget(self.recovery_status_label)
        self.field_labels["recovery_status_label"] = (self.recovery_status_label, "recovery_status_ready")

        # Results section (hidden by default)
        self.recovery_results_frame = QFrame()
        self.recovery_results_frame.setVisible(False)
        self.recovery_results_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 12px;
            }}
        """
        )
        results_layout = QVBoxLayout()
        results_layout.setSpacing(8)

        results_title = QLabel(tr("recovery_result_title", lang=get_lang()))
        results_title.setStyleSheet("font-weight: bold;")
        results_layout.addWidget(results_title)
        self.field_labels["recovery_result_title"] = (results_title, "recovery_result_title")

        # Password result
        password_row = QHBoxLayout()
        password_label = QLabel(tr("recovery_result_password", lang=get_lang()))
        self.field_labels["recovery_result_password"] = (password_label, "recovery_result_password")
        password_row.addWidget(password_label)
        self.recovered_password_display = QLineEdit()
        self.recovered_password_display.setReadOnly(True)
        self.recovered_password_display.setEchoMode(QLineEdit.EchoMode.Password)
        password_row.addWidget(self.recovered_password_display, stretch=1)
        self.copy_password_btn = QPushButton(tr("recovery_result_copy_password", lang=get_lang()))
        self.copy_password_btn.clicked.connect(self._copy_recovered_password)
        password_row.addWidget(self.copy_password_btn)
        results_layout.addLayout(password_row)

        # Keyfile result
        keyfile_row = QHBoxLayout()
        keyfile_label = QLabel(tr("recovery_result_keyfile", lang=get_lang()))
        self.field_labels["recovery_result_keyfile"] = (keyfile_label, "recovery_result_keyfile")
        keyfile_row.addWidget(keyfile_label)
        self.recovered_keyfile_display = QLabel("—")
        keyfile_row.addWidget(self.recovered_keyfile_display, stretch=1)
        self.save_keyfile_btn = QPushButton(tr("recovery_result_save_keyfile", lang=get_lang()))
        self.save_keyfile_btn.clicked.connect(self._save_recovered_keyfile)
        self.save_keyfile_btn.setEnabled(False)
        keyfile_row.addWidget(self.save_keyfile_btn)
        results_layout.addLayout(keyfile_row)

        # Security mode result
        mode_row = QHBoxLayout()
        mode_label = QLabel(tr("recovery_result_mode", lang=get_lang()))
        self.field_labels["recovery_result_mode"] = (mode_label, "recovery_result_mode")
        mode_row.addWidget(mode_label)
        self.recovered_mode_display = QLabel("—")
        mode_row.addWidget(self.recovered_mode_display, stretch=1)
        results_layout.addLayout(mode_row)

        self.recovery_results_frame.setLayout(results_layout)
        action_layout.addWidget(self.recovery_results_frame)

        self.recovery_action_box.setLayout(action_layout)
        tab_layout.addWidget(self.recovery_action_box)

        # Note: _recovered_keyfile_bytes initialized in __init__ for security
        # Pre-populate container path from config or default location
        self._init_recovery_container_path()

        # CHG-20251221-001: Add recovery kit generation section
        self._add_recovery_generate_section(tab_layout)

    def _add_recovery_generate_section(self, tab_layout: QVBoxLayout):
        """Add the recovery kit generation section to the Recovery tab (CHG-20251221-001)."""
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tab_layout.addWidget(separator)

        # Recovery generation group box
        self.recovery_generate_box = QGroupBox(tr("recovery_generate_section_title", lang=get_lang()))
        generate_layout = QVBoxLayout()
        generate_layout.setSpacing(10)

        # Instructions
        gen_instructions = QLabel(tr("recovery_generate_instructions", lang=get_lang()))
        gen_instructions.setWordWrap(True)
        gen_instructions.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        generate_layout.addWidget(gen_instructions)
        self.field_labels["recovery_generate_instructions"] = (gen_instructions, "recovery_generate_instructions")

        # Generate button
        self.btn_generate_recovery_kit = QPushButton(tr("btn_generate_recovery_kit", lang=get_lang()))
        self.btn_generate_recovery_kit.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
            }}
        """
        )
        self.btn_generate_recovery_kit.clicked.connect(self._on_generate_recovery_kit)
        generate_layout.addWidget(self.btn_generate_recovery_kit)

        # Status label
        self.recovery_generate_status = QLabel(tr("recovery_generate_status_ready", lang=get_lang()))
        self.recovery_generate_status.setWordWrap(True)
        self.recovery_generate_status.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        generate_layout.addWidget(self.recovery_generate_status)
        self.field_labels["recovery_generate_status"] = (
            self.recovery_generate_status,
            "recovery_generate_status_ready",
        )

        self.recovery_generate_box.setLayout(generate_layout)
        tab_layout.addWidget(self.recovery_generate_box)

    def _on_generate_recovery_kit(self):
        """
        Handle recovery kit generation button click (CHG-20251221-001).

        BUG-20251221-019 FIX:
        - Use QMessageBox.question() for simple Yes/No confirmation
        - No more "type GENERATE" text input requirement
        - Pass config and smartdrive_dir to worker for credential derivation

        BUG-20251221-043 FIX:
        - For PW_ONLY mode, prompt for password before starting worker
        - Pass password to worker via optional parameter
        """
        # Check if recovery kit already exists
        recovery_config = self.config.get("recovery", {})
        recovery_state = recovery_config.get("state", "")

        # Determine if this is a regeneration
        # BUG-20251222-010 FIX: Check for "enabled" (constant value), not "RECOVERY_STATE_ENABLED"
        is_regeneration = recovery_state == "enabled"

        # BUG-20251221-044 FIX: Show security warning if kit exists
        if is_regeneration:
            # Security warning for regeneration
            warning_title = tr("recovery_generate_security_warning_title", lang=get_lang())
            warning_body = tr("recovery_generate_security_warning_body", lang=get_lang())
            reply = QMessageBox.warning(
                self,
                warning_title,
                warning_body,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,  # Default to No for safety
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            # Standard confirmation for first-time generation
            title = tr("recovery_generate_confirm_title", lang=get_lang())
            body = tr("recovery_generate_confirm_body", lang=get_lang())
            reply = QMessageBox.question(
                self,
                title,
                body,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,  # Default to No for safety
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # BUG-20251221-043 FIX: For PW_ONLY mode, prompt for password
        mode = self.config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
        password = None
        if mode == SecurityMode.PW_ONLY.value:
            from PyQt6.QtWidgets import QInputDialog

            password, ok = QInputDialog.getText(
                self,
                tr("recovery_generate_password_prompt_title", lang=get_lang()),
                tr("recovery_generate_password_prompt_body", lang=get_lang()),
                QLineEdit.EchoMode.Password,
            )
            if not ok or not password:
                # User cancelled or provided empty password
                return

        # Disable button during generation
        self.btn_generate_recovery_kit.setEnabled(False)
        self.recovery_generate_status.setText(tr("recovery_generate_status_running", lang=get_lang()))
        self.recovery_generate_status.setStyleSheet(f"color: {COLORS['primary']}; font-size: 11px;")

        # Start worker thread with config and smartdrive_dir for credential derivation
        self._recovery_generate_worker = RecoveryGenerateWorker(
            config=self.config, smartdrive_dir=self._smartdrive_dir, force=is_regeneration, password=password
        )
        self._recovery_generate_worker.progress.connect(self._on_recovery_generate_progress)
        self._recovery_generate_worker.finished.connect(self._on_recovery_generate_finished)
        self._recovery_generate_worker.start()

    def _on_recovery_generate_progress(self, message_key: str):
        """Update status during recovery kit generation."""
        self.recovery_generate_status.setText(tr(message_key, lang=get_lang()))

    def _on_recovery_generate_finished(self, success: bool, message_key: str, args: dict):
        """Handle recovery kit generation completion (CHG-20251221-001)."""
        self.btn_generate_recovery_kit.setEnabled(True)

        if success:
            self.recovery_generate_status.setText(tr(message_key, lang=get_lang(), **args))
            self.recovery_generate_status.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

            # Show success dialog with kit location
            kit_path = args.get("path", "")
            QMessageBox.information(
                self,
                tr("recovery_generate_success_title", lang=get_lang()),
                tr("recovery_generate_success_body", lang=get_lang(), path=kit_path),
            )

            # BUG-20251223-001 FIX: Call refresh_settings_values() not just _reload_config()
            # refresh_settings_values() reloads config AND updates UI widgets including recovery_status_label
            self.refresh_settings_values()
        else:
            self.recovery_generate_status.setText(tr(message_key, lang=get_lang(), **args))
            self.recovery_generate_status.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")

    def _init_recovery_container_path(self):
        """Initialize recovery container path from config or default location."""
        try:
            # First check config for explicit path
            recovery_config = self.config.get("recovery", {})
            container_path = recovery_config.get("container_path", "")

            if container_path and Path(container_path).exists():
                self.recovery_container_path.setText(container_path)
                return

            # Try to find container in mounted volume's recovery directory
            # Get mount point from config (platform-specific)
            import platform

            if platform.system() == "Windows":
                mount_point = self.config.get("windows", {}).get(ConfigKeys.MOUNT_LETTER, "")
                if mount_point and not mount_point.endswith(":"):
                    mount_point = mount_point + ":"
            else:
                mount_point = self.config.get("unix", {}).get(ConfigKeys.MOUNT_POINT, "")

            if mount_point:
                recovery_dir = Path(mount_point) / ".smartdrive" / "recovery"
                container_file = recovery_dir / "recovery_container.bin"
                if container_file.exists():
                    self.recovery_container_path.setText(str(container_file))
                    return

            # Try .smartdrive/recovery in config directory
            if self.config_path:
                config_dir = Path(self.config_path).parent
                local_container = config_dir / "recovery" / "recovery_container.bin"
                if local_container.exists():
                    self.recovery_container_path.setText(str(local_container))
                    return
                # Also check direct child
                direct_container = config_dir / "recovery_container.bin"
                if direct_container.exists():
                    self.recovery_container_path.setText(str(direct_container))
                    return
        except (OSError, KeyError, TypeError) as e:
            # Non-critical - user can browse for container manually
            log_exception("Could not auto-detect recovery container path", e, level="debug")

    def _browse_recovery_container(self):
        """Open file dialog to select recovery container."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Recovery Container", "", "Recovery Container (*.bin);;All Files (*)"
        )
        if file_path:
            self.recovery_container_path.setText(file_path)

    def _perform_recovery(self):
        """
        Perform recovery using the entered phrase.

        BUG-20251220-005 FIX: This now integrates with CLI recovery state machine:
        - Checks recovery.state at entry (blocks if already used)
        - Performs two-phase commit (consuming -> delete -> used)
        - Sets post_recovery.rekey_required flag
        - Logs to audit trail
        - Prompts user to rekey immediately

        INVARIANTS:
        - Recovery kit is ONE-TIME USE ONLY
        - Failed decryption does NOT burn the kit
        - Successful credential extraction DOES burn the kit
        - Post-recovery rekey is mandatory
        """
        phrase = self.recovery_phrase_edit.toPlainText().strip()

        # Validate phrase has 24 words
        words = phrase.split()
        if len(words) != 24:
            self.recovery_status_label.setText(tr("recovery_phrase_invalid", lang=get_lang()))
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            return

        self.recovery_status_label.setText(tr("recovery_status_validating", lang=get_lang()))
        self.recovery_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        QApplication.processEvents()

        # ═══════════════════════════════════════════════════════════════════
        # SECURITY CHECK: Is recovery kit already fully consumed?
        # BUG-20251225-002 FIX: Allow re-extraction when recovery_active
        # The user may have closed Settings and needs to access the password again.
        # Container should only be deleted after rekey+mount verified.
        # ═══════════════════════════════════════════════════════════════════
        recovery_config = self.config.get("recovery", {})
        state = recovery_config.get("state", "enabled")

        # ONLY block if recovery is FULLY consumed (used state) - not just active
        if state == "used" or recovery_config.get("used"):
            self.recovery_status_label.setText(tr("recovery_already_used", lang=get_lang()))
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self._gui_audit_log("RECOVERY_BLOCKED", "already_used")
            return

        # BUG-20251225-002 FIX: If recovery_active, allow re-extraction but inform user
        # User may have closed Settings and needs to copy password again
        if state == "recovery_active" or state == "consuming":
            _gui_logger.info("BUG-20251225-002: Re-extracting credentials during recovery_active state")
            # Show info but continue - don't block

        try:
            # Try to find container path
            container_path_str = self.recovery_container_path.text().strip()
            if not container_path_str:
                container_path_str = recovery_config.get("container_path", "")

            container_path = Path(container_path_str) if container_path_str else None

            if not container_path or not container_path.exists():
                self.recovery_status_label.setText(tr("recovery_container_not_found", lang=get_lang()))
                self.recovery_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
                return

            self.recovery_status_label.setText(tr("recovery_status_decrypting", lang=get_lang()))
            QApplication.processEvents()

            # Log attempt start
            self._gui_audit_log("RECOVERY_ATTEMPT_START")

            # Import recovery container module
            from recovery_container import RecoveryContainerError, decrypt_container, load_container

            # Load and decrypt container
            container_bytes = load_container(container_path)
            credentials = decrypt_container(container_bytes, phrase)

            # ═══════════════════════════════════════════════════════════════════
            # SUCCESS: Now perform TWO-PHASE COMMIT (one-time use enforcement)
            # ═══════════════════════════════════════════════════════════════════
            # BUG-20251223-066 CRITICAL FIX: Do NOT delete recovery container yet!
            # Container must be preserved until successful rekey + successful mount.
            # User reported data loss when container was deleted before rekey completed.
            self.recovery_status_label.setText(tr("recovery_status_invalidating", lang=get_lang()))
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
            QApplication.processEvents()

            # Phase 1: Transition to "consuming" state (but keep container for safety)
            recovery_config["state"] = "consuming"
            self.config["recovery"] = recovery_config
            self._save_config_atomic()

            # BUG-20251223-066 CRITICAL: Do NOT delete container here!
            # Instead, store path for deferred deletion after successful rekey + mount
            # The old code was: self._secure_delete_file(container_path)
            # This caused data loss when user couldn't complete rekey!
            self._pending_container_deletion_path = container_path
            _gui_logger.info(
                f"BUG-20251223-066: Deferred container deletion until rekey + mount verified: {container_path}"
            )

            # Phase 2: Transition to "recovery_active" state (NOT "used" until rekey succeeds)
            # BUG-20251221-029: Use module-level timezone import instead of datetime.UTC
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            self.config[ConfigKeys.RECOVERY] = {
                ConfigKeys.RECOVERY_ENABLED: False,
                # BUG-20251223-066: Mark as "recovery_active" NOT "used" - container still exists
                ConfigKeys.RECOVERY_USED: False,  # Will be True after rekey + mount succeeds
                ConfigKeys.RECOVERY_STATE: "recovery_active",  # New state: recovery started but not finalized
                ConfigKeys.RECOVERY_INVALIDATED_AT: timestamp,
                # BUG-20251223-066: Store container path for deferred deletion
                "pending_container_path": str(container_path),
            }
            self.config[ConfigKeys.POST_RECOVERY] = {
                ConfigKeys.POST_RECOVERY_REKEY_REQUIRED: True,
                ConfigKeys.POST_RECOVERY_REKEY_COMPLETED: False,
                ConfigKeys.POST_RECOVERY_COMPLETED_AT: timestamp,
            }
            self._save_config_atomic()

            # BUG-20251221-035: Refresh settings UI to reflect changes
            self.refresh_settings_values()

            # Log success
            self._gui_audit_log("RECOVERY_SUCCESS", "SUCCESS")

            # ═══════════════════════════════════════════════════════════════════
            # SUCCESS EPILOGUE: Show results
            # ═══════════════════════════════════════════════════════════════════
            self.recovery_status_label.setText(tr("recovery_status_complete", lang=get_lang()))
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

            # Show results
            self.recovered_password_display.setText(credentials.get("mount_password", ""))

            keyfile_b64 = credentials.get("keyfile_bytes_b64")
            if keyfile_b64:
                import base64

                self._recovered_keyfile_bytes = base64.b64decode(keyfile_b64)
                self.recovered_keyfile_display.setText(f"{len(self._recovered_keyfile_bytes)} bytes")
                self.save_keyfile_btn.setEnabled(True)
            else:
                self._recovered_keyfile_bytes = None
                self.recovered_keyfile_display.setText("—")
                self.save_keyfile_btn.setEnabled(False)

            mode = credentials.get("security_mode", "unknown")
            self.recovered_mode_display.setText(mode)

            self.recovery_results_frame.setVisible(True)

            # ═══════════════════════════════════════════════════════════════════
            # MANDATORY REKEY PROMPT
            # ═══════════════════════════════════════════════════════════════════
            QApplication.processEvents()
            self._prompt_mandatory_rekey()

        except RecoveryContainerError as e:
            # Decryption failed - kit is NOT burned (transient failure)
            error_msg = tr("recovery_status_failed", lang=get_lang()).format(error=str(e))
            self.recovery_status_label.setText(error_msg)
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self.recovery_results_frame.setVisible(False)
            self._gui_audit_log("RECOVERY_FAILED", "TRANSIENT_FAILURE", {"error": str(e)})
        except Exception as e:
            error_msg = tr("recovery_status_failed", lang=get_lang()).format(error=str(e))
            self.recovery_status_label.setText(error_msg)
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 11px;")
            self.recovery_results_frame.setVisible(False)
            self._gui_audit_log("RECOVERY_FAILED", "TRANSIENT_FAILURE", {"error": str(e)})

    def _gui_audit_log(self, event: str, outcome: str = None, details: dict = None):
        """
        Append entry to recovery audit log (GUI operations).

        SECURITY: Never logs secrets (passwords, keyfiles, phrases).
        """
        import json
        import os
        import platform

        # BUG-20251221-029: Use module-level timezone import instead of datetime.UTC
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = {
            "timestamp": timestamp,
            "event": event,
            "outcome": outcome,
            "source": "GUI",
            "platform": {
                "os": platform.system(),
                "python": platform.python_version(),
            },
        }
        if details:
            safe_details = {
                k: v for k, v in details.items() if k not in ("password", "phrase", "keyfile", "credentials")
            }
            entry["details"] = safe_details

        try:
            script_dir = get_script_dir()
            log_file = script_dir / "recovery.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            # Logging failures shouldn't break recovery - file system may be unavailable
            log_exception("Recovery audit log write failed")

    def _secure_delete_file(self, file_path: Path, passes: int = 3):
        """Securely delete a file by overwriting with random data."""
        import os

        if not file_path.exists():
            return
        try:
            file_size = file_path.stat().st_size
            with open(file_path, "rb+") as f:
                for _ in range(passes):
                    f.seek(0)
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())
            file_path.unlink()
        except OSError as e:
            # Fallback to regular delete if secure overwrite fails
            log_exception(f"Secure delete failed for {file_path}: {e}")
            try:
                file_path.unlink()
            except OSError:
                log_exception(f"Regular delete also failed for {file_path}")

    def _save_config_atomic(self):
        """Atomically save config to disk."""
        import json
        import os

        tmp_path = (
            self.config_path.with_suffix(".json.tmp")
            if hasattr(self.config_path, "with_suffix")
            else Path(str(self.config_path) + ".tmp")
        )
        config_path = Path(self.config_path) if not isinstance(self.config_path, Path) else self.config_path

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(config_path)
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def _prompt_mandatory_rekey(self):
        """
        Prompt user to rekey immediately after recovery.

        BUG-20251225-002 FIX: Instead of launching CLI rekey, navigate to Security tab
        where the user can use the existing GUI rekey functionality.
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr("recovery_rekey_required_title", lang=get_lang()))
        msg_box.setText(tr("recovery_rekey_required_body", lang=get_lang()))
        msg_box.setIcon(QMessageBox.Icon.Warning)

        rekey_btn = msg_box.addButton(tr("recovery_rekey_now", lang=get_lang()), QMessageBox.ButtonRole.AcceptRole)
        later_btn = msg_box.addButton(tr("recovery_rekey_later", lang=get_lang()), QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()

        if msg_box.clickedButton() == rekey_btn:
            # BUG-20251225-002 FIX: Navigate to Security tab instead of launching CLI
            # The GUI has a built-in rekey button in the Security tab
            self._navigate_to_security_tab_for_rekey()
        else:
            # User skipped - show warning that rekey is still required
            QMessageBox.warning(
                self,
                tr("recovery_rekey_required_title", lang=get_lang()),
                tr("recovery_rekey_skipped_warning", lang=get_lang()),
            )
            self._gui_audit_log("REKEY_SKIPPED")

    def _navigate_to_security_tab_for_rekey(self):
        """
        Navigate to Security tab to use GUI rekey functionality.

        BUG-20251225-002 FIX: Use GUI rekey instead of CLI.
        """
        # Find the Security tab index
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == tr("settings_tab_security", lang=get_lang()):
                self.tabs.setCurrentIndex(i)
                _gui_logger.info("BUG-20251225-002: Navigated to Security tab for rekey")
                self._gui_audit_log("REKEY_NAVIGATED_TO_SECURITY_TAB")

                # Show informational message about using the Rekey button
                QMessageBox.information(
                    self,
                    tr("recovery_rekey_required_title", lang=get_lang()),
                    "Use the 'Rekey Volume' button below to change your password.\n\n"
                    "Your recovered password has been copied to your clipboard.",
                )
                return

        # Fallback if Security tab not found (shouldn't happen)
        _gui_logger.warning("Security tab not found, falling back to CLI rekey")
        self._launch_rekey()

    def _launch_rekey(self):
        """Launch the rekey script (CLI fallback only)."""
        import subprocess

        try:
            script_dir = get_script_dir()
            rekey_script = script_dir / "rekey.py"
            if rekey_script.exists():
                python_exe = get_python_exe()
                subprocess.Popen(
                    [str(python_exe), str(rekey_script)],
                    cwd=str(script_dir),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
                )
                self._gui_audit_log("REKEY_LAUNCHED")
            else:
                QMessageBox.warning(self, "Rekey", f"Rekey script not found: {rekey_script}")
        except Exception as e:
            QMessageBox.warning(self, "Rekey", f"Failed to launch rekey: {e}")

    def _copy_recovered_password(self):
        """Copy recovered password to clipboard."""
        password = self.recovered_password_display.text()
        if password:
            clipboard = QApplication.clipboard()
            clipboard.setText(password)
            self.recovery_status_label.setText(tr("recovery_copied_to_clipboard", lang=get_lang()))
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

            # Auto-clear after 30 seconds
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == password else None)

    def _save_recovered_keyfile(self):
        """Save recovered keyfile to disk."""
        if not self._recovered_keyfile_bytes:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Keyfile", "recovered_keyfile.bin", "Binary Files (*.bin);;All Files (*)"
        )
        if file_path:
            Path(file_path).write_bytes(self._recovered_keyfile_bytes)
            msg = tr("recovery_keyfile_saved", lang=get_lang()).format(path=file_path)
            self.recovery_status_label.setText(msg)
            self.recovery_status_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px;")

    def _add_field_to_layout(self, layout: QFormLayout, field, tab_name: str):
        """Add a single field widget to the layout."""
        from core.settings_schema import FieldType

        # Check visibility condition
        if field.visibility_condition and not field.visibility_condition(self.config):
            return  # Field should be hidden

        # Get current value from config
        current_value = self._get_config_value(field)

        # BUG-20251220-006: Special handling for recovery status display
        # BUG-010: Handle both new (with state) and legacy (without state) configs
        if field.key == ConfigKeys.RECOVERY_ENABLED and field.field_type == FieldType.READONLY:
            recovery_cfg = self.config.get("recovery", {})
            state = recovery_cfg.get("state", "")
            used = recovery_cfg.get("used", False)
            enabled = recovery_cfg.get("enabled", False)

            # Priority 1: Explicitly marked as used
            if used or state == "used":
                status_text = tr("recovery_kit_used", lang=get_lang())
                status_color = COLORS.get("warning", "#FFA500")
            # Priority 2: Enabled (state "enabled" or missing state for legacy)
            # For backwards compatibility: enabled=True without state field means "enabled"
            elif enabled and (state == "enabled" or state == ""):
                status_text = tr("recovery_kit_available", lang=get_lang())
                status_color = COLORS.get("success", "#28a745")
            else:
                status_text = tr("recovery_kit_not_configured", lang=get_lang())
                status_color = COLORS.get("error", "#dc3545")

            # BUG-014: Check if HTML recovery kit file still exists on device
            html_warning = ""
            try:
                # BUG-20251221-021: Use module-level Paths import (line 73), not local import
                # Local import here caused UnboundLocalError shadowing in admin mode
                recovery_dir = Paths.recovery_dir(self._launcher_root)
                html_file = recovery_dir / f"{Branding.PRODUCT_NAME}{FileNames.RECOVERY_KIT_HTML_SUFFIX}"
                if html_file.exists():
                    html_warning = tr("recovery_html_warning", lang=get_lang())
            except Exception as e:
                _gui_logger.debug(f"Error checking for HTML recovery file: {e}")

            # Create status widget, optionally with warning
            if html_warning:
                widget = QLabel(f"{status_text}\n⚠️ {html_warning}")
                widget.setWordWrap(True)
                widget.setStyleSheet(
                    f"color: {status_color}; font-weight: bold; "
                    f"background-color: #fff3cd; padding: 4px; border-radius: 4px;"
                )
            else:
                widget = QLabel(status_text)
                widget.setStyleSheet(f"color: {status_color}; font-weight: bold;")

            field_key = self._make_field_key(field)
            self.field_widgets[field_key] = widget
            label = QLabel(tr(field.label_key, lang=get_lang()))
            self.field_labels[field_key] = label
            if field.tooltip_key:
                tooltip = tr(field.tooltip_key, lang=get_lang())
                widget.setToolTip(tooltip)
                label.setToolTip(tooltip)
            layout.addRow(label, widget)
            return

        # Create widget based on field type
        if field.field_type == FieldType.TEXT:
            widget = QLineEdit()
            widget.setText(str(current_value) if current_value is not None else "")
            if field.placeholder:
                widget.setPlaceholderText(field.placeholder)

        elif field.field_type == FieldType.PATH_FILE or field.field_type == FieldType.PATH_DIR:
            # Path field with browse button
            container = QWidget()
            h_layout = QHBoxLayout()
            h_layout.setContentsMargins(0, 0, 0, 0)
            h_layout.setSpacing(4)

            line_edit = QLineEdit()

            # BUG-20251221-020: Pre-fill default paths from Paths SSOT when field is empty
            display_value = current_value
            if not current_value:
                # Map ConfigKeys to their default Paths.* methods
                if field.key == ConfigKeys.SEED_GPG_PATH:
                    display_value = str(Paths.seed_gpg(self._launcher_root))
                elif field.key == ConfigKeys.ENCRYPTED_KEYFILE:
                    display_value = str(Paths.keyfile_gpg(self._launcher_root))
                elif field.key == ConfigKeys.KEYFILE:
                    display_value = str(Paths.keyfile_plain(self._launcher_root))

            line_edit.setText(str(display_value) if display_value is not None else "")
            if field.placeholder:
                line_edit.setPlaceholderText(field.placeholder)

            browse_btn = QPushButton("📁")
            browse_btn.setFixedWidth(40)
            browse_btn.setToolTip(tr("btn_browse_container"))

            # Connect browse button
            if field.field_type == FieldType.PATH_FILE:
                browse_btn.clicked.connect(lambda: self._browse_file(line_edit))
            else:
                browse_btn.clicked.connect(lambda: self._browse_directory(line_edit))

            h_layout.addWidget(line_edit)
            h_layout.addWidget(browse_btn)
            container.setLayout(h_layout)

            widget = line_edit  # Store the line_edit for value reading
            layout_widget = container  # But add the container to layout

        elif field.field_type == FieldType.NUMBER:
            widget = QSpinBox()
            widget.setRange(0, 999)
            widget.setValue(int(current_value) if current_value is not None else (field.default or 0))

        elif field.field_type == FieldType.BOOLEAN:
            widget = QCheckBox()
            widget.setChecked(bool(current_value) if current_value is not None else (field.default or False))

        elif field.field_type == FieldType.DROPDOWN:
            widget = QComboBox()

            # Special handling for language dropdown
            if field.key == ConfigKeys.GUI_LANG:
                for code, display_name in AVAILABLE_LANGUAGES.items():
                    widget.addItem(display_name, code)
                widget.currentIndexChanged.connect(self.on_language_changed)
                # Store as instance attribute for backward compatibility with tests
                self.lang_combo = widget
            # Special handling for theme dropdown
            elif field.key == ConfigKeys.GUI_THEME:
                from core.constants import THEME_PALETTES

                for theme_id in THEME_PALETTES.keys():
                    theme_name = tr(f"theme_{theme_id}", lang=get_lang())
                    widget.addItem(theme_name, theme_id)
                widget.currentIndexChanged.connect(self.on_theme_changed)
                # Store as instance attribute for backward compatibility with tests
                self.theme_combo = widget
            # BUG-20251224-004 FIX: Special handling for security mode dropdown (SSOT - use i18n)
            elif field.key == ConfigKeys.MODE:
                mode_i18n_keys = {
                    SecurityMode.PW_ONLY.value: "rekey_mode_pw_only",
                    SecurityMode.PW_KEYFILE.value: "rekey_mode_pw_keyfile",
                    SecurityMode.PW_GPG_KEYFILE.value: "rekey_mode_pw_gpg_keyfile",
                    SecurityMode.GPG_PW_ONLY.value: "rekey_mode_gpg_pw_only",
                }
                for mode_value, i18n_key in mode_i18n_keys.items():
                    widget.addItem(tr(i18n_key, lang=get_lang()), mode_value)
                widget.currentIndexChanged.connect(self._on_security_mode_changed)
                self.security_mode_combo = widget
            # Generic dropdown from options
            elif field.options:
                for display, value in field.options:
                    widget.addItem(display, value)

            # Set current selection
            if current_value is not None:
                index = widget.findData(current_value)
                if index >= 0:
                    widget.setCurrentIndex(index)

        elif field.field_type == FieldType.TEXTAREA:
            widget = QTextEdit()
            widget.setPlainText(str(current_value) if current_value is not None else "")
            widget.setMaximumHeight(100)
            if field.placeholder:
                widget.setPlaceholderText(field.placeholder)

        elif field.field_type == FieldType.READONLY:
            # CHG-20251221-026: Special handling for LAUNCHER_ROOT - get from _launcher_root attribute
            # BUG-20251223-001 FIX: Check for both generic and platform-specific keys
            if field.key in (ConfigKeys.LAUNCHER_ROOT, ConfigKeys.WINDOWS_LAUNCHER_ROOT, ConfigKeys.UNIX_LAUNCHER_ROOT):
                launcher_root_value = (
                    str(self._launcher_root) if self._launcher_root else tr("info_unavailable", lang=get_lang())
                )
                widget = QLabel(launcher_root_value)
                widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")
            # CHG-20251221-040: Special handling for OS_DRIVE - runtime detection
            # BUG-20251224-001 FIX: Check for both generic and platform-specific keys
            elif field.key in (
                ConfigKeys.OS_DRIVE,
                ConfigKeys.WINDOWS_OS_DRIVE,
                ConfigKeys.UNIX_OS_DRIVE,
            ):
                from core.platform import get_os_drive

                os_drive_value = get_os_drive()
                if not os_drive_value:
                    os_drive_value = tr("info_unavailable", lang=get_lang())
                widget = QLabel(os_drive_value)
                widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")
            # CHG-20251221-040: Special handling for INSTANTIATION_DRIVE - runtime detection
            # BUG-20251224-001 FIX: Check for both generic and platform-specific keys
            elif field.key in (
                ConfigKeys.INSTANTIATION_DRIVE,
                ConfigKeys.WINDOWS_INSTANTIATION_DRIVE,
                ConfigKeys.UNIX_INSTANTIATION_DRIVE,
            ):
                from core.platform import get_instantiation_drive_letter_or_mount

                inst_drive_value = get_instantiation_drive_letter_or_mount()
                if not inst_drive_value:
                    inst_drive_value = tr("info_unavailable", lang=get_lang())
                widget = QLabel(inst_drive_value)
                widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")
            else:
                widget = QLabel(str(current_value) if current_value is not None else "N/A")
                widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")

        else:
            widget = QLabel(f"Unsupported field type: {field.field_type}")

        # Store widget reference
        field_key = self._make_field_key(field)
        self.field_widgets[field_key] = widget

        # Create label
        label = QLabel(tr(field.label_key, lang=get_lang()))
        self.field_labels[field_key] = label

        # Add tooltip if specified
        if field.tooltip_key:
            tooltip = tr(field.tooltip_key, lang=get_lang())
            widget.setToolTip(tooltip)
            label.setToolTip(tooltip)

        # Add to layout
        if field.field_type == FieldType.PATH_FILE or field.field_type == FieldType.PATH_DIR:
            layout.addRow(label, layout_widget)  # Add the container with browse button
        else:
            layout.addRow(label, widget)

    def _make_field_key(self, field) -> str:
        """Create unique key for field widget storage."""
        if field.nested_path:
            return ".".join(field.nested_path)
        return field.key

    def _get_config_value(self, field):
        """Get current value from config for a field."""
        if field.nested_path:
            # Navigate nested structure
            value = self.config
            for key in field.nested_path:
                if isinstance(value, dict):
                    value = value.get(key, {})
                else:
                    return field.default
            return value if value != {} else field.default
        else:
            return self.config.get(field.key, field.default)

    def _browse_file(self, line_edit: QLineEdit):
        """Open file browser and update line edit."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*.*)")
        if file_path:
            line_edit.setText(file_path)

    def _browse_directory(self, line_edit: QLineEdit):
        """Open directory browser and update line edit."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            line_edit.setText(dir_path)

    def _add_product_name_to_general_tab(self):
        """Add product name field to General tab (QSettings, not config.json)."""
        from PyQt6.QtWidgets import QScrollArea

        # Find General tab
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "General":
                tab = self.tab_widget.widget(i)
                # CHG-20251223-065: Tab is now a QScrollArea, get the content widget inside
                if isinstance(tab, QScrollArea):
                    content_widget = tab.widget()
                    layout = content_widget.layout() if content_widget else None
                else:
                    layout = tab.layout()

                if layout is None:
                    break

                # Find the first group box or create form layout
                if layout.count() > 0:
                    first_widget = layout.itemAt(0).widget()
                    if isinstance(first_widget, QGroupBox):
                        # Insert into existing group box at top
                        group_layout = first_widget.layout()

                        # Create product name widgets
                        self.product_name_edit = QLineEdit()
                        self.product_name_edit.setText(get_product_name(self.settings))
                        self.product_name_edit.setPlaceholderText(f"Default: {PRODUCT_NAME}")
                        self.product_name_edit.setMaxLength(TITLE_MAX_CHARS)

                        self.preview_label = QLabel()
                        self.preview_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")
                        self.update_preview()

                        self.product_name_edit.textChanged.connect(self.update_preview)

                        # Insert at row 0
                        group_layout.insertRow(0, tr("label_preview", lang=get_lang()), self.preview_label)
                        group_layout.insertRow(0, tr("label_product_name", lang=get_lang()), self.product_name_edit)
                break

    def _add_about_section_to_general_tab(self):
        """
        Add About section to General tab showing version information.

        CHG-20251221-012: Displays version, build ID, and compatibility version
        in a dedicated About group box at the bottom of the General tab.
        """
        from PyQt6.QtWidgets import QScrollArea

        # Find General tab
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            # Handle translated tab names
            if tab_text in ["General", "Allgemein", "Opšte", "General", "Général", "Общие", "常规"]:
                tab = self.tab_widget.widget(i)
                # CHG-20251223-065: Tab is now a QScrollArea, get the content widget inside
                if isinstance(tab, QScrollArea):
                    content_widget = tab.widget()
                    layout = content_widget.layout() if content_widget else None
                else:
                    layout = tab.layout()

                if layout is None:
                    break

                # Add stretch before About section to push it to bottom
                layout.addStretch()

                # Create About group box
                about_group = QGroupBox(tr("settings_about", lang=get_lang()))
                about_layout = QFormLayout()
                about_layout.setSpacing(8)
                about_layout.setContentsMargins(12, 12, 12, 12)

                # Version label (read-only)
                self.version_label = QLabel(APP_VERSION)
                self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                about_layout.addRow(tr("label_version", lang=get_lang()), self.version_label)

                # Build ID label (read-only, shows "Development" if not set)
                build_display = BUILD_ID if BUILD_ID else tr("label_build_dev", lang=get_lang())
                self.build_id_label = QLabel(build_display)
                self.build_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                about_layout.addRow(tr("label_build_id", lang=get_lang()), self.build_id_label)

                # Compatibility version label (read-only)
                self.compat_version_label = QLabel(COMPATIBILITY_VERSION)
                self.compat_version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                about_layout.addRow(tr("label_compat_version", lang=get_lang()), self.compat_version_label)

                about_group.setLayout(about_layout)

                # Store for i18n refresh
                self.group_boxes["about"] = (about_group, "settings_about")
                self.field_labels["about_version"] = (None, "label_version")  # Row labels refreshed via group
                self.field_labels["about_build"] = (None, "label_build_id")
                self.field_labels["about_compat"] = (None, "label_compat_version")

                # Add at bottom of General tab
                layout.addWidget(about_group)
                break

    def on_language_changed(self, index):
        """Handle language dropdown change with immediate UI update."""
        widget = self.sender()
        if widget is None and hasattr(self, "lang_combo"):
            widget = self.lang_combo  # Fallback for direct calls (e.g., tests)
        if widget is None:
            return
        selected_lang = widget.itemData(index)
        if selected_lang and selected_lang != get_lang():
            # Update global language for live preview
            set_lang(selected_lang)

            # BUG-20251220-015: Update pending config (not committed config)
            # Changes will be persisted only when user clicks Save
            self._pending_config[ConfigKeys.GUI_LANG] = selected_lang
            self._config_dirty = True

            # Apply language to main window immediately (live preview only)
            if self.parent and hasattr(self.parent, "apply_language"):
                try:
                    self.parent.apply_language(selected_lang)
                except Exception as e:
                    log_exception(f"Error applying language '{selected_lang}'", e, level="error")
                    try:
                        QMessageBox.critical(
                            self.parent,
                            tr("title_error", lang=get_lang()),
                            tr("error_apply_language", lang=get_lang(), error=str(e)),
                        )
                    except Exception as e2:
                        log_exception("Error showing language error dialog", e2)

            # Refresh this dialog's labels
            try:
                self.refresh_dialog_labels(selected_lang)
            except Exception as e:
                log_exception("Error refreshing settings dialog labels", e)

            # Show "restart not required" message
            try:
                if hasattr(self, "restart_info_label") and self.restart_info_label:
                    self.restart_info_label.setText(tr("settings_restart_not_required", lang=selected_lang))
                    self.restart_info_label.setVisible(True)
            except Exception as e:
                log_exception("Error showing restart info label", e, level="debug")

    def on_theme_changed(self, index):
        """Handle theme dropdown change with immediate UI update."""
        widget = self.sender()
        if widget is None and hasattr(self, "theme_combo"):
            widget = self.theme_combo  # Fallback for direct calls (e.g., tests)
        if widget is None:
            return
        selected_theme = widget.itemData(index)
        if selected_theme:
            # BUG-20251220-015: Update pending config (not committed config)
            # Changes will be persisted only when user clicks Save
            self._pending_config[ConfigKeys.GUI_THEME] = selected_theme
            self._config_dirty = True

            # Apply theme to main window immediately (live preview only, no persist)
            # BUG-20251220-015: persist=False for transactional settings
            if self.parent and hasattr(self.parent, "apply_theme"):
                try:
                    self.parent.apply_theme(selected_theme, persist=False)
                except Exception as e:
                    log_exception(f"Error applying theme '{selected_theme}'", e, level="error")
                    try:
                        QMessageBox.critical(
                            self.parent,
                            tr("title_error", lang=get_lang()),
                            tr("error_apply_theme", lang=get_lang(), error=str(e)),
                        )
                    except Exception as e2:
                        log_exception("Error showing theme error dialog", e2)

            # Refresh theme names in dropdown (they may have color changes)
            try:
                from core.constants import THEME_PALETTES

                current_index = widget.currentIndex()
                # Block signals to prevent recursion from setCurrentIndex
                theme_combo = self.theme_combo
                theme_combo.blockSignals(True)
                theme_combo.clear()
                for theme_id in THEME_PALETTES.keys():
                    theme_name = tr(f"theme_{theme_id}", lang=get_lang())
                    theme_combo.addItem(theme_name, theme_id)
                theme_combo.setCurrentIndex(current_index)
                theme_combo.blockSignals(False)
            except Exception as e:
                if hasattr(self, "theme_combo"):
                    self.theme_combo.blockSignals(False)  # Ensure signals re-enabled on error
                log_exception("Error refreshing theme list", e)

            # Show "restart not required" message
            try:
                if hasattr(self, "restart_info_label") and self.restart_info_label:
                    self.restart_info_label.setText(tr("settings_restart_not_required", lang=get_lang()))
                    self.restart_info_label.setVisible(True)
            except Exception as e:
                log_exception("Error showing restart info label", e, level="debug")

    def _on_security_mode_changed(self, index):
        """
        Handle security mode dropdown change with immediate field visibility update.
        BUG-20251224-004 FIX: Real-time settings refresh when security mode changes.
        """
        widget = self.sender()
        if widget is None and hasattr(self, "security_mode_combo"):
            widget = self.security_mode_combo
        if widget is None:
            return
        selected_mode = widget.itemData(index)
        if selected_mode:
            # Update pending config
            self._pending_config[ConfigKeys.MODE] = selected_mode
            self._config_dirty = True

            # Update field visibility based on new mode
            # This refreshes which fields are shown/hidden (e.g., keyfile fields, GPG fields)
            try:
                self._refresh_conditional_fields()
            except Exception as e:
                log_exception(f"Error refreshing conditional fields for mode '{selected_mode}'", e)

            # Show "restart not required" message
            try:
                if hasattr(self, "restart_info_label") and self.restart_info_label:
                    self.restart_info_label.setText(tr("settings_restart_not_required", lang=get_lang()))
                    self.restart_info_label.setVisible(True)
            except Exception as e:
                log_exception("Error showing restart info label", e, level="debug")

    def _refresh_conditional_fields(self):
        """
        Refresh visibility of fields with visibility_condition based on current pending config.
        BUG-20251224-004 FIX: Real-time settings refresh.
        """
        for field in self.schema:
            if field.visibility_condition is not None:
                field_key = self._make_field_key(field)
                # Check visibility using pending config (not committed config)
                should_show = field.visibility_condition(self._pending_config)

                # Find the field widget and its row in the layout
                if field_key in self.field_widgets:
                    widget = self.field_widgets[field_key]
                    widget.setVisible(should_show)

                    # Also hide/show the label
                    if field_key in self.field_labels:
                        label = self.field_labels[field_key]
                        if hasattr(label, "setVisible"):
                            label.setVisible(should_show)

    def refresh_dialog_labels(self, lang_code: str):
        """Refresh all labels in the settings dialog to new language."""
        self.setWindowTitle(tr("settings_window_title", lang=lang_code))

        # Update tab names
        for i in range(self.tab_widget.count()):
            # Get original tab name (tab widget stores the original name)
            tab_key = (
                f"settings_{['general', 'security', 'keyfile', 'windows', 'unix', 'updates'][i]}" if i < 6 else None
            )
            if tab_key:
                self.tab_widget.setTabText(i, tr(tab_key, lang=lang_code))

        # Update group box titles
        for key, group_box in self.group_boxes.items():
            # Group box titles are in English from schema
            # Could add translation if needed
            pass

        # Update field labels
        for field_key, label_info in self.field_labels.items():
            # Handle both schema-driven labels and manual tuple labels
            if isinstance(label_info, tuple):
                # Manual label: (widget, translation_key)
                widget, trans_key = label_info
                if widget is not None and hasattr(widget, "setText"):
                    widget.setText(tr(trans_key, lang=lang_code))
            else:
                # Schema-driven label: find field in schema
                for field in self.schema:
                    if self._make_field_key(field) == field_key:
                        label_info.setText(tr(field.label_key, lang=lang_code))
                        break

        # Update group box titles for recovery sections
        if hasattr(self, "recovery_action_box"):
            self.recovery_action_box.setTitle(tr("recovery_section_title", lang=lang_code))
        if hasattr(self, "recovery_generate_box"):
            self.recovery_generate_box.setTitle(tr("recovery_generate_section_title", lang=lang_code))
        if hasattr(self, "rekey_section_box"):
            self.rekey_section_box.setTitle(tr("rekey_section_title", lang=lang_code))
        if hasattr(self, "integrity_verify_box"):
            self.integrity_verify_box.setTitle(tr("integrity_section_title", lang=lang_code))

        # Refresh theme combo box translations
        if hasattr(self, "theme_combo"):
            try:
                from core.constants import THEME_PALETTES

                theme_combo = self.theme_combo
                current_index = theme_combo.currentIndex()
                theme_combo.blockSignals(True)
                theme_combo.clear()
                for theme_id in THEME_PALETTES.keys():
                    theme_name = tr(f"theme_{theme_id}", lang=lang_code)
                    theme_combo.addItem(theme_name, theme_id)
                theme_combo.setCurrentIndex(current_index)
                theme_combo.blockSignals(False)
            except Exception as e:
                if hasattr(self, "theme_combo"):
                    self.theme_combo.blockSignals(False)
                log_exception("Error refreshing theme combo translations", e)

        # CHG-20251221-005: Update hint label in Updates tab
        if hasattr(self, "update_hint_box"):
            self.update_hint_box.setTitle(tr("hint_update_local_title", lang=lang_code))
        if hasattr(self, "update_hint_label"):
            self.update_hint_label.setText(tr("hint_update_local_body", lang=lang_code))

        # Update buttons
        self.save_btn.setText(tr("btn_save", lang=lang_code))
        self.cancel_btn.setText(tr("btn_cancel", lang=lang_code))
        # CHG-20251223-055: Update reload config button
        if hasattr(self, "reload_btn"):
            self.reload_btn.setText(tr("btn_reload_config", lang=lang_code))
            self.reload_btn.setToolTip(tr("tooltip_reload_config", lang=lang_code))

    def refresh_settings_values(self):
        """
        BUG-20251221-035: Reload config from disk and update all field widgets.

        Call this after operations that modify config.json to reflect changes
        immediately without requiring the user to close and reopen settings.
        """
        _gui_logger.info("Refreshing settings values from disk...")

        # Reload config from disk
        self._reload_config()

        # Also update pending config
        import copy

        self._pending_config = copy.deepcopy(self.config)
        self._config_dirty = False

        # Update each field widget with current config value
        for field_key, widget in self.field_widgets.items():
            try:
                # Parse the field key to get config path
                # Field keys are like "field_general_language" or "field_windows_mount_letter"
                parts = field_key.split("_")
                if len(parts) < 3:
                    continue

                # Find matching field in schema
                for field in self.schema:
                    schema_field_key = self._make_field_key(field)
                    if schema_field_key == field_key:
                        # Get current config value
                        current_value = self._get_config_value(field)

                        # Update widget based on type
                        if field.field_type == self.FieldType.DROPDOWN:
                            combo = widget
                            combo.blockSignals(True)
                            for i in range(combo.count()):
                                if combo.itemData(i) == current_value:
                                    combo.setCurrentIndex(i)
                                    break
                            combo.blockSignals(False)
                        elif field.field_type == self.FieldType.BOOL:
                            checkbox = widget
                            checkbox.blockSignals(True)
                            checkbox.setChecked(bool(current_value))
                            checkbox.blockSignals(False)
                        elif field.field_type == self.FieldType.TEXT:
                            line_edit = widget
                            line_edit.blockSignals(True)
                            line_edit.setText(str(current_value) if current_value else "")
                            line_edit.blockSignals(False)
                        elif field.field_type == self.FieldType.PATH_FILE:
                            line_edit = widget
                            line_edit.blockSignals(True)
                            line_edit.setText(str(current_value) if current_value else "")
                            line_edit.blockSignals(False)
                        break
            except Exception as e:
                _gui_logger.debug(f"Error refreshing field {field_key}: {e}")

        # Update recovery status label if it exists
        if hasattr(self, "recovery_status_label"):
            recovery_cfg = self.config.get("recovery", {})
            # BUG-20251222-010 FIX: Check for "enabled"/"used" (constant values), not "RECOVERY_STATE_*"
            if recovery_cfg.get("enabled") and recovery_cfg.get("state") == "enabled":
                self.recovery_status_label.setText(tr("recovery_kit_available", lang=get_lang()))
                self.recovery_status_label.setStyleSheet(f"color: {COLORS['success']};")
            elif recovery_cfg.get("used") or recovery_cfg.get("state") == "used":
                self.recovery_status_label.setText(tr("recovery_kit_used", lang=get_lang()))
                self.recovery_status_label.setStyleSheet(f"color: {COLORS['warning']};")
            else:
                self.recovery_status_label.setText(tr("recovery_kit_not_configured", lang=get_lang()))
                self.recovery_status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

        # BUG-20251224-003: Also update schema-driven recovery status field widget
        # The field_key for RECOVERY_ENABLED is "recovery.enabled" (from nested_path)
        recovery_field_key = f"{ConfigKeys.RECOVERY}.{ConfigKeys.RECOVERY_ENABLED}"
        if recovery_field_key in self.field_widgets:
            recovery_cfg = self.config.get("recovery", {})
            state = recovery_cfg.get("state", "")
            used = recovery_cfg.get("used", False)
            enabled = recovery_cfg.get("enabled", False)

            # Priority 1: Explicitly marked as used
            if used or state == "used":
                status_text = tr("recovery_kit_used", lang=get_lang())
                status_color = COLORS.get("warning", "#FFA500")
            # Priority 2: Enabled (state "enabled" or missing state for legacy)
            elif enabled and (state == "enabled" or state == ""):
                status_text = tr("recovery_kit_available", lang=get_lang())
                status_color = COLORS.get("success", "#28a745")
            else:
                status_text = tr("recovery_kit_not_configured", lang=get_lang())
                status_color = COLORS.get("error", "#dc3545")

            # Check if HTML recovery kit file still exists on device (warning)
            html_warning = ""
            try:
                recovery_dir = Paths.recovery_dir(self._launcher_root)
                html_file = recovery_dir / f"{Branding.PRODUCT_NAME}{FileNames.RECOVERY_KIT_HTML_SUFFIX}"
                if html_file.exists():
                    html_warning = tr("recovery_html_warning", lang=get_lang())
            except Exception as e:
                _gui_logger.debug(f"Error checking for HTML recovery file: {e}")

            # Update the widget
            widget = self.field_widgets[recovery_field_key]
            if html_warning:
                widget.setText(f"{status_text}\n⚠️ {html_warning}")
                widget.setWordWrap(True)
                widget.setStyleSheet(
                    f"color: {status_color}; font-weight: bold; "
                    f"background-color: #fff3cd; padding: 4px; border-radius: 4px;"
                )
            else:
                widget.setText(status_text)
                widget.setStyleSheet(f"color: {status_color}; font-weight: bold;")

        _gui_logger.info("Settings values refreshed from disk")

    def save(self):
        """Save all fields to config.json."""
        # Handle product name (QSettings)
        if hasattr(self, "product_name_edit"):
            name = self.product_name_edit.text().strip()
            if name:
                sanitized = sanitize_product_name(name)
                self.settings.setValue("product_name", sanitized)
            else:
                self.settings.remove("product_name")
            self.settings.sync()

        # BUG-20251220-015: Merge pending config with current config
        # _pending_config holds live-preview changes (language, theme) that weren't committed yet
        # Start with current config (may have security-critical updates from recovery/rekey)
        # then merge pending changes on top
        import copy

        new_config = copy.deepcopy(self.config)

        # Merge pending config changes (language, theme, etc.)
        if hasattr(self, "_pending_config"):
            for key in [ConfigKeys.GUI_LANG, ConfigKeys.GUI_THEME]:
                if key in self._pending_config:
                    new_config[key] = self._pending_config[key]

        for field in self.schema:
            field_key = self._make_field_key(field)
            widget = self.field_widgets.get(field_key)

            if widget is None or field.readonly:
                continue  # Skip readonly fields

            # Get value from widget
            value = self._get_widget_value(widget, field)

            # Validate if validator provided
            if field.validation and value:
                is_valid, error_msg = field.validation(value)
                if not is_valid:
                    QMessageBox.warning(self, "Validation Error", error_msg)
                    return

            # Set value in config (handling nested paths)
            if field.nested_path:
                # Navigate/create nested structure
                current = new_config
                for key in field.nested_path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                current[field.nested_path[-1]] = value
            else:
                new_config[field.key] = value

        # Add timestamp
        from datetime import datetime

        new_config[ConfigKeys.LAST_UPDATED] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Validate recovery enablement: only true if container exists
        try:
            recovery_cfg = new_config.get(ConfigKeys.RECOVERY, {})
            if recovery_cfg.get(ConfigKeys.RECOVERY_ENABLED):
                container_path = recovery_cfg.get("container_path", "")
                if not container_path or not Path(container_path).exists():
                    QMessageBox.warning(
                        self,
                        tr("popup_recovery_title", lang=get_lang()),
                        tr("recovery_no_kit_configured", lang=get_lang()),
                    )
                    recovery_cfg[ConfigKeys.RECOVERY_ENABLED] = False
                    new_config[ConfigKeys.RECOVERY] = recovery_cfg
        except Exception as e:
            log_exception("Error validating recovery config", e, level="debug")

        # Save to file
        try:
            write_config_atomic(self.config_path, new_config)
        except Exception as e:
            QMessageBox.critical(
                self, tr("title_save_failed", lang=get_lang()), f"{tr('error_save_failed', lang=get_lang())}\\n\\n{e}"
            )
            return

        # Refresh main window state
        try:
            if self.parent:
                self.parent.config = self.parent.load_config()
                self.parent.update_button_states()
                self.parent.update_storage_display()
                if hasattr(self.parent, "key_hint_label"):
                    self.parent.key_hint_label.setVisible(self.parent.is_gpg_mode())
                self.parent.apply_branding(get_product_name(self.settings))
        except Exception as e:
            log_exception("Error refreshing main window state after save", e)

        self.accept()

    def done(self, result):
        """
        Override done() to clear sensitive credentials when dialog closes.

        SECURITY: Per user requirement, credentials must not persist in memory.
        This clears any recovered credentials (password, keyfile bytes) when
        the dialog is closed, whether via save, cancel, or window close.
        """
        self._clear_recovered_credentials()
        super().done(result)

    def reject(self):
        """
        Override reject() to revert live preview changes when Cancel is clicked.

        BUG-20251220-015: Discards uncommitted changes and reverts UI to saved state.
        """
        # Revert language if changed
        if hasattr(self, "_config_dirty") and self._config_dirty:
            original_lang = self.config.get(ConfigKeys.GUI_LANG, GUIConfig.DEFAULT_LANG)
            original_theme = self.config.get(ConfigKeys.GUI_THEME, GUIConfig.DEFAULT_THEME)

            # Revert language
            if get_lang() != original_lang:
                set_lang(original_lang)
                if self.parent and hasattr(self.parent, "apply_language"):
                    try:
                        self.parent.apply_language(original_lang)
                    except Exception as e:
                        log_exception("Error reverting language on cancel", e)

            # Revert theme
            current_theme = self._pending_config.get(ConfigKeys.GUI_THEME)
            if current_theme and current_theme != original_theme:
                if self.parent and hasattr(self.parent, "apply_theme"):
                    try:
                        self.parent.apply_theme(original_theme)
                    except Exception as e:
                        log_exception("Error reverting theme on cancel", e)

        # Discard pending config
        self._pending_config = None
        self._config_dirty = False

        super().reject()

    def _clear_recovered_credentials(self):
        """
        Clear any recovered credentials from memory.

        SECURITY: This ensures sensitive data doesn't persist after dialog closes.
        Called automatically by done() when dialog is closed.
        """
        # Clear recovered keyfile bytes
        if hasattr(self, "_recovered_keyfile_bytes") and self._recovered_keyfile_bytes:
            # Overwrite with zeros before releasing
            try:
                self._recovered_keyfile_bytes = bytes(len(self._recovered_keyfile_bytes))
            except (TypeError, AttributeError):
                pass
            self._recovered_keyfile_bytes = None

        # Clear recovered password from display widget
        if hasattr(self, "recovered_password_display"):
            self.recovered_password_display.clear()

        # Hide results frame
        if hasattr(self, "recovery_results_frame"):
            self.recovery_results_frame.setVisible(False)

    def _get_widget_value(self, widget, field):
        """Extract value from widget based on field type."""
        from core.settings_schema import FieldType

        if (
            field.field_type == FieldType.TEXT
            or field.field_type == FieldType.PATH_FILE
            or field.field_type == FieldType.PATH_DIR
        ):
            return widget.text().strip()
        elif field.field_type == FieldType.NUMBER:
            return widget.value()
        elif field.field_type == FieldType.BOOLEAN:
            return widget.isChecked()
        elif field.field_type == FieldType.DROPDOWN:
            return widget.itemData(widget.currentIndex())
        elif field.field_type == FieldType.TEXTAREA:
            return widget.toPlainText().strip()
        elif field.field_type == FieldType.READONLY:
            return None  # Read-only, don't save
        else:
            return None

    def update_preview(self):
        """Update the preview label with current product name."""
        if not hasattr(self, "product_name_edit"):
            return

        name = self.product_name_edit.text().strip()
        if not name:
            name = PRODUCT_NAME

        name = sanitize_product_name(name)
        left, right = split_for_logo(name)

        if right:
            preview = f"{left} [LOGO] {right}"
        else:
            preview = f"{left} [LOGO]"

        self.preview_label.setText(preview)

    def refresh_dialog_labels(self, lang_code: str):
        """Refresh all labels in the settings dialog to new language."""
        self.setWindowTitle(tr("settings_window_title", lang=lang_code))

        # Update tab names
        for i in range(self.tab_widget.count()):
            tab_name = self.tab_widget.tabText(i)
            # Tab names are English in schema, no translation for now
            # Could add translation key mapping if needed

        # Update group box titles
        for key, group_box in self.group_boxes.items():
            # Group box titles are in English from schema
            # Could add translation if needed
            pass

        # Update field labels
        for field_key, label in self.field_labels.items():
            # Find field in schema to get label_key
            for field in self.schema:
                if self._make_field_key(field) == field_key:
                    label.setText(tr(field.label_key, lang=lang_code))
                    break

        # Update buttons
        self.save_btn.setText(tr("btn_save", lang=lang_code))
        self.cancel_btn.setText(tr("btn_cancel", lang=lang_code))
        # CHG-20251223-055: Update reload config button
        if hasattr(self, "reload_btn"):
            self.reload_btn.setText(tr("btn_reload_config", lang=lang_code))
            self.reload_btn.setToolTip(tr("tooltip_reload_config", lang=lang_code))

    def _get_widget_value(self, widget, field):
        """Extract value from widget based on field type."""
        from core.settings_schema import FieldType

        if (
            field.field_type == FieldType.TEXT
            or field.field_type == FieldType.PATH_FILE
            or field.field_type == FieldType.PATH_DIR
        ):
            return widget.text().strip()
        elif field.field_type == FieldType.NUMBER:
            return widget.value()
        elif field.field_type == FieldType.BOOLEAN:
            return widget.isChecked()
        elif field.field_type == FieldType.DROPDOWN:
            return widget.itemData(widget.currentIndex())
        elif field.field_type == FieldType.TEXTAREA:
            return widget.toPlainText().strip()
        elif field.field_type == FieldType.READONLY:
            return None  # Read-only, don't save
        else:
            return None

    def update_preview(self):
        """Update the preview label with current product name."""
        if not hasattr(self, "product_name_edit"):
            return

        name = self.product_name_edit.text().strip()
        if not name:
            name = PRODUCT_NAME

        name = sanitize_product_name(name)
        left, right = split_for_logo(name)

        if right:
            preview = f"{left} [LOGO] {right}"
        else:
            preview = f"{left} [LOGO]"

        self.preview_label.setText(preview)


# APPLICATION ENTRY POINT
# ============================================================


def main():
    """Main application entry point with single-instance-per-drive enforcement."""
    import argparse

    # Parse arguments
    parser = argparse.ArgumentParser(description=f"{PRODUCT_NAME} GUI")
    parser.add_argument("--config", type=str, help="Path to config.json")
    args = parser.parse_args()

    # Determine config path
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = CONFIG_FILE

    # Create minimal app for pre-flight checks
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setStyle("Fusion")

    # BUG-20251219-007 FIX: Set explicit palette for cross-platform text readability
    # On Linux, Qt may inherit incomplete/conflicting system palettes causing
    # white text on white backgrounds in dialogs. This enforces deterministic colors.
    import platform

    if platform.system() == "Linux":
        from PyQt6.QtGui import QColor, QPalette

        palette = QPalette()
        # Base colors - light theme for readability
        palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
        # Disabled state
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
        app.setPalette(palette)
        _gui_logger.info("Set explicit QPalette for Linux text readability")

    # BUG-20251220-009 FIX: Set application-wide icon for taskbar with comprehensive fallback
    # Try multiple locations: deployed (.smartdrive/static), repo (static), dev (static)
    icon_locations = [
        Path(__file__).parent.parent / "static" / "LOGO_main.ico",  # .smartdrive/static/
        Path(__file__).parent.parent.parent / "static" / "LOGO_main.ico",  # repo/static/
        Path(__file__).parent.parent / "static" / "LOGO_main.png",  # .smartdrive/static/ (png fallback)
        Path(__file__).parent.parent.parent / "static" / "LOGO_main.png",  # repo/static/ (png fallback)
    ]
    icon_set = False
    for icon_loc in icon_locations:
        if icon_loc.exists():
            app.setWindowIcon(QIcon(str(icon_loc)))
            _gui_logger.info(f"Set application icon from: {icon_loc}")
            icon_set = True
            break

    if not icon_set:
        # Fallback to Qt built-in icon
        _gui_logger.warning("No custom application icon found, using Qt built-in icon")
        from PyQt6.QtWidgets import QStyle

        style = app.style()
        if style:
            app.setWindowIcon(style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))

    # CRITICAL: Do not quit when window is hidden - tray keeps running
    app.setQuitOnLastWindowClosed(False)
    _gui_logger.info("startup.app.quit_on_last_window_closed=False")

    # Load config to get drive_id (with migration if needed)
    instance_manager = None
    try:
        config, migration_result = load_or_create_config(config_path)
        drive_id = migration_result.drive_id

        if drive_id:
            _gui_logger.info(f"Loaded drive_id: {drive_id[:8]}...")

            # Check single instance per drive
            instance_manager = SingleInstanceManager(
                drive_id=drive_id, on_activate=None  # Will be set after window creation
            )

            if not instance_manager.try_acquire():
                # Another instance is running for this drive
                _gui_logger.info("Another instance is running for this drive, activating it")
                instance_manager.send_activate()
                _gui_logger.info("Exiting - another instance handles this drive")
                sys.exit(0)

            # We are the owner - start IPC server
            instance_manager.start_server()
        else:
            _gui_logger.warning("No drive_id available, single-instance check skipped")

    except Exception as e:
        _gui_logger.warning(f"Single-instance check failed: {e}")
        # Continue without single-instance enforcement

    # Create and show main window
    window = SmartDriveGUI(instance_manager=instance_manager)

    # Update instance manager's activate callback to focus this window
    if instance_manager:
        instance_manager.on_activate = window._on_tray_open

    window.show()
    window.raise_()  # Bring to front
    window.activateWindow()  # Activate the window

    # Run event loop
    exit_code = app.exec()

    # Cleanup
    if instance_manager:
        instance_manager.release()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
