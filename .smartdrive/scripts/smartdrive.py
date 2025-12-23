#!/usr/bin/env python3
"""
SmartDrive Manager - Unified CLI Interface
==========================================

Context-aware menu that detects whether it's running from:
- SMARTDRIVE partition (external drive) → Mount/Unmount/Rekey
- SYSTEM drive (development/setup) → Setup wizard/Recovery tools

Author: SmartDrive Project
License: This project is licensed under a custom non-commercial, no-derivatives license.
Commercial use and modified versions are not permitted.
See the LICENSE file for details.

"""

import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/smartdrive.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/smartdrive.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.config import write_config_atomic, write_file_atomic
    from core.constants import CLIOperations, ConfigKeys, ConsoleStyle, Defaults, FileNames
    from core.limits import Limits
    from core.modes import SECURITY_MODE_DISPLAY, SecurityMode
    from core.paths import Paths
    from core.platform import _set_admin_override, is_admin
    from core.version import VERSION

    _HAS_ATOMIC_WRITE = True
except ImportError:
    # Fallback for standalone operation - VERSION imported above
    _HAS_ATOMIC_WRITE = False
    write_file_atomic = None

    class ConfigKeys:
        MODE = "mode"
        DRIVE_NAME = "drive_name"
        WINDOWS = "windows"
        UNIX = "unix"
        VOLUME_PATH = "volume_path"
        MOUNT_LETTER = "mount_letter"
        MOUNT_POINT = "mount_point"
        # Backwards-compatible timestamp keys
        SETUP_DATE = "setup_date"
        LAST_PASSWORD_CHANGE = "last_password_change"
        LAST_VERIFIED = "last_verified"
        LAST_UPDATED = "last_updated"

    class Defaults:
        WINDOWS_MOUNT_LETTER = "V"
        UNIX_MOUNT_POINT = "~/veradrive"

    SECURITY_MODE_DISPLAY = {}
    CLIOperations = None
    ConsoleStyle = None

    def is_admin():
        """Fallback admin check."""
        import ctypes

        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return os.geteuid() == 0 if hasattr(os, "geteuid") else False

    def _set_admin_override(value):
        pass


# Import constants
try:
    from variables import PRODUCT_DESCRIPTION, PRODUCT_NAME
except ImportError:
    PRODUCT_NAME = "SmartDrive"
    PRODUCT_DESCRIPTION = "SmartDrive Manager"
try:
    from update import update_deployment_drive
except ImportError:
    # Fallback if update.py not available
    def update_deployment_drive(*args, **kwargs):
        _style = ConsoleStyle.detect() if ConsoleStyle else None
        _failure = _style.symbol("FAILURE") if _style else "[X]"
        print(f"{_failure} Update functionality not available (update.py missing)")
        return False


# CLI i18n support
try:
    from cli_i18n import get_cli_lang, init_cli_i18n, set_cli_lang
    from cli_i18n import tr as cli_tr

    _HAS_CLI_I18N = True
except ImportError:
    _HAS_CLI_I18N = False

    def init_cli_i18n(config_path=None):
        return "en"

    def cli_tr(key, **kwargs):
        return key

    def get_cli_lang():
        return "en"

    def set_cli_lang(lang):
        pass


# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path(__file__).parent.resolve()

# Detect if running from .smartdrive/ (deployed) or scripts/ (development)
# In deployed mode: SCRIPT_DIR is .smartdrive/scripts/, parent is .smartdrive/
# In dev mode: SCRIPT_DIR is scripts/, parent is project root
if SCRIPT_DIR.parent.name == ".smartdrive":
    # Deployed on external drive
    SMARTDRIVE_DIR = SCRIPT_DIR.parent
    KEYS_DIR = SMARTDRIVE_DIR / Paths.KEYS_SUBDIR
    INTEGRITY_DIR = SMARTDRIVE_DIR / "integrity"
else:
    # Development environment - check for .smartdrive or fall back to old structure
    if (SCRIPT_DIR.parent / ".smartdrive").exists():
        SMARTDRIVE_DIR = SCRIPT_DIR.parent / ".smartdrive"
        KEYS_DIR = SMARTDRIVE_DIR / Paths.KEYS_SUBDIR
        INTEGRITY_DIR = SMARTDRIVE_DIR / "integrity"
    else:
        # Legacy structure (scripts/ and keys/ at root)
        SMARTDRIVE_DIR = SCRIPT_DIR.parent
        KEYS_DIR = SMARTDRIVE_DIR / Paths.KEYS_SUBDIR
        INTEGRITY_DIR = SMARTDRIVE_DIR  # integrity files at root in legacy mode

# CONFIG is at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
CONFIG_FILE = SMARTDRIVE_DIR / FileNames.CONFIG_JSON

# ============================================================
# INVARIANT CHECK: SINGLE ENTRYPOINT
# ============================================================
# Per AGENT_ARCHITECTURE.md, there must be exactly ONE smartdrive.py at
# .smartdrive/scripts/smartdrive.py. A duplicate at the drive root is an error.


def check_single_entrypoint_invariant():
    """
    Verify only one smartdrive.py exists at the canonical location.

    INVARIANT: smartdrive.py must exist ONLY at .smartdrive/scripts/smartdrive.py
    A duplicate at the launcher/drive root is a deployment error.

    Returns:
        True if invariant holds, False if violated
    """
    # Determine the launcher root (drive root for deployed, project root for dev)
    if SCRIPT_DIR.parent.name == ".smartdrive":
        launcher_root = SCRIPT_DIR.parent.parent
    else:
        launcher_root = SCRIPT_DIR.parent

    # Canonical location is .smartdrive/scripts/smartdrive.py
    canonical = launcher_root / ".smartdrive" / "scripts" / "smartdrive.py"
    duplicate_at_root = launcher_root / "smartdrive.py"

    # Check for duplicate
    if duplicate_at_root.exists() and canonical.exists():
        # Duplicate found - this is an error
        return False, duplicate_at_root

    return True, None


def enforce_single_entrypoint():
    """
    Enforce the single entrypoint invariant at startup.
    Warns loudly if a duplicate smartdrive.py exists.
    """
    ok, duplicate_path = check_single_entrypoint_invariant()
    if not ok:
        print("\n" + "!" * 70)
        print("  INVARIANT VIOLATION: Duplicate smartdrive.py detected!")
        print("!" * 70)
        print(f"\n  Canonical: {SCRIPT_DIR / 'smartdrive.py'}")
        print(f"  Duplicate: {duplicate_path}")
        print("\n  The duplicate at the root should be removed.")
        print("  Run 'python .smartdrive/scripts/update.py' to fix.")
        print("!" * 70 + "\n")
        # Do not abort - just warn loudly


# ============================================================
# DISPLAY HELPERS
# ============================================================


def clear_screen():
    """Clear terminal screen.

    BUG-20251221-024: Use subprocess.run instead of os.system to prevent
    "syntax error in command line" popup errors on Windows.
    """
    import subprocess

    if os.name == "nt":
        # Windows: use subprocess with CREATE_NO_WINDOW flag
        subprocess.run(
            ["cmd", "/c", "cls"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        # Unix: use clear command
        subprocess.run(["clear"], check=False)


def get_drive_metadata() -> dict:
    """
    Load drive metadata from config.json.
    Returns dict with drive info for display.
    """
    metadata = {
        ConfigKeys.DRIVE_NAME: None,
        "security_mode": None,
        ConfigKeys.VOLUME_PATH: None,
        "mount_target": None,
        ConfigKeys.LAST_PASSWORD_CHANGE: None,
        ConfigKeys.SETUP_DATE: None,
        "version": None,
        "last_updated": None,
        "keyfile_fingerprints": None,
    }

    if not CONFIG_FILE.exists():
        return metadata

    try:
        import json

        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)

        # Drive name (user-defined label)
        metadata[ConfigKeys.DRIVE_NAME] = cfg.get(ConfigKeys.DRIVE_NAME, None)

        # Security mode
        mode = cfg.get("security_mode", "")
        if not mode:
            # Detect from keyfile config
            if cfg.get(ConfigKeys.ENCRYPTED_KEYFILE):
                mode = "yubikey"
            elif cfg.get(ConfigKeys.KEYFILE):
                mode = "keyfile"
            else:
                mode = "password"
        metadata["security_mode"] = mode

        # Volume path and mount target
        system = platform.system().lower()
        if system == "windows":
            metadata[ConfigKeys.VOLUME_PATH] = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.VOLUME_PATH, "")
            metadata["mount_target"] = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.MOUNT_LETTER, "V") + ":"
        else:
            metadata[ConfigKeys.VOLUME_PATH] = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.VOLUME_PATH, "")
            metadata["mount_target"] = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.MOUNT_POINT, "")

        # Timestamps
        metadata[ConfigKeys.LAST_PASSWORD_CHANGE] = cfg.get(ConfigKeys.LAST_PASSWORD_CHANGE)
        metadata[ConfigKeys.SETUP_DATE] = cfg.get(ConfigKeys.SETUP_DATE)
        metadata["version"] = cfg.get("version")
        metadata["last_updated"] = cfg.get("last_updated")

        # YubiKey fingerprints (if stored)
        metadata["keyfile_fingerprints"] = cfg.get("keyfile_fingerprints")

    except Exception:
        pass

    return metadata


def get_security_mode_display(mode: str) -> str:
    """Get display string for security mode using core.modes."""
    style = ConsoleStyle.detect()
    lock = style.symbol("LOCK")
    key = style.symbol("KEY")
    encrypt = style.symbol("ENCRYPT")
    info = style.symbol("INFO")

    # Try to use SecurityMode enum first
    try:
        sec_mode = SecurityMode.from_config(mode)
        return SECURITY_MODE_DISPLAY.get(sec_mode, f"{info} {mode}")
    except (ValueError, AttributeError):
        # Fallback for legacy mode strings
        legacy_modes = {
            "yubikey": f"{lock} YubiKey + Password",
            "keyfile": f"{key} Keyfile + Password",
            "password": f"{encrypt} Password Only",
        }
        return legacy_modes.get(mode, f"{info} {mode}")


def print_banner():
    """Print the SmartDrive banner."""
    print()
    print("═" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print(f"  ║                {PRODUCT_NAME} Manager                         ║")
    print("  ║         Encrypted External Drive with YubiKey 2FA             ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("═" * 70)


def print_drive_info():
    """Print drive metadata panel."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    failure = style.symbol("FAILURE")
    warning = style.symbol("WARNING")
    drive = style.symbol("DRIVE")
    h = style.symbol("BOX_H")
    v = style.symbol("BOX_V")
    tl = style.symbol("BOX_TL")
    tr = style.symbol("BOX_TR")
    bl = style.symbol("BOX_BL")
    br = style.symbol("BOX_BR")
    ml = style.symbol("BOX_ML")
    mr = style.symbol("BOX_MR")

    metadata = get_drive_metadata()

    if not any(metadata.values()):
        return  # No config, skip

    # Check recovery status
    recovery_info = None
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            recovery_info = cfg.get("recovery", {})
        except:
            pass

    print()
    print(tl + h * 68 + tr)

    # Drive name or default
    drive_name = metadata[ConfigKeys.DRIVE_NAME] or "Unnamed Drive"
    print(f"{v}  {drive} {drive_name:<63}{v}")

    print(ml + h * 68 + mr)

    # Security mode
    if metadata["security_mode"]:
        mode_str = get_security_mode_display(metadata["security_mode"])
        print(f"{v}  Security: {mode_str:<56}{v}")

    # Recovery status
    if recovery_info:
        if recovery_info.get("enabled"):
            recovery_date = recovery_info.get("created_date", "Unknown")
            recovery_text = f"Recovery: {success} Enabled (created {recovery_date[:10]})"
            print(f"{v}  {recovery_text:<66}{v}")

            # Show recovery events if any
            events = recovery_info.get("recovery_events", [])
            if events:
                last_event = events[-1]
                event_date = last_event.get("date", "Unknown")
                event_reason = last_event.get("reason", "Unknown")
                warning_text = f"{warning}  Recovery used on {event_date[:10]} ({event_reason})"
                print(f"{v}  {warning_text:<66}{v}")
        else:
            print(f"{v}  {'Recovery: ' + failure + ' Not enabled':<66}{v}")

    # Mount target
    if metadata["mount_target"]:
        print(f"{v}  Mounts to: {metadata['mount_target']:<55}{v}")

    # Last password change (if tracked)
    if metadata[ConfigKeys.LAST_PASSWORD_CHANGE]:
        # Calculate days since change
        try:
            from datetime import datetime

            last_change = datetime.fromisoformat(metadata[ConfigKeys.LAST_PASSWORD_CHANGE])
            days_ago = (datetime.now() - last_change).days
            if days_ago > 90:
                status = f"{warning}  {days_ago} days ago (consider rotating)"
            else:
                status = f"{success} {days_ago} days ago"
            print(f"{v}  Password changed: {status:<48}{v}")
        except:
            print(f"{v}  Password changed: {metadata[ConfigKeys.LAST_PASSWORD_CHANGE]:<48}{v}")

    # Setup date
    if metadata[ConfigKeys.SETUP_DATE]:
        print(f"{v}  Setup date: {metadata[ConfigKeys.SETUP_DATE]:<54}{v}")

    # Version
    if metadata["version"]:
        version_str = f"v{metadata['version']}"
        if metadata["last_updated"]:
            version_str += f" (updated {metadata['last_updated'][:10]})"
        print(f"{v}  Version: {version_str:<57}{v}")

    print(bl + h * 68 + br)


def print_status(context: str, is_mounted: bool = None, admin_status: bool = False):
    """Print current status."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    info = style.symbol("INFO")
    unlock = style.symbol("UNLOCK")
    lock = style.symbol("LOCK")

    print()
    # Always show drive info if config exists
    if CONFIG_FILE.exists():
        print_drive_info()
        print()
        if is_mounted is True:
            print(f"  Status: {unlock} Volume MOUNTED")
        elif is_mounted is False:
            print(f"  Status: {lock} Volume NOT mounted")
        else:
            print(f"  Status: {info} Volume status unknown")

    # Show admin status
    if admin_status:
        print(f"  Admin:  {success} Running with administrator privileges")
    else:
        print(f"  Admin:  {warning} Not running as administrator (some options disabled)")
    print()


def print_unified_menu(admin_status: bool, style: "ConsoleStyle" = None):
    """
    Print unified menu with all operations, organized by section.

    Admin-required operations are shown but marked as disabled when not admin.
    Uses CLIOperations from core/constants.py as SSOT.

    Args:
        admin_status: True if running as admin
        style: ConsoleStyle instance for output formatting (auto-detected if None)
    """
    # Auto-detect console style if not provided
    if style is None:
        if ConsoleStyle is not None:
            style = ConsoleStyle.detect()
        else:
            # Fallback: use unicode by default
            style = None

    # Get box characters from style
    if style:
        h = style.BOX_H
        v = style.BOX_V
        tl = style.BOX_TL
        tr = style.BOX_TR
        bl = style.BOX_BL
        br = style.BOX_BR
        ml = style.BOX_ML
        mr = style.BOX_MR
    else:
        h, v, tl, tr, bl, br, ml, mr = "─", "│", "┌", "┐", "└", "┘", "├", "┤"

    width = 68

    print(tl + h * width + tr)
    title = "SMARTDRIVE - Unified Menu"
    print(f"{v}  {title}" + " " * (width - len(title) - 2) + v)
    print(ml + h * width + mr)

    # Get menu sections from CLIOperations (SSOT)
    if CLIOperations is not None and hasattr(CLIOperations, "MENU_SECTIONS"):
        menu_sections = CLIOperations.MENU_SECTIONS
    else:
        # Fallback: single section with all operations
        menu_sections = [
            (
                "Operations",
                [
                    "mount",
                    "unmount",
                    "setup",
                    "rekey",
                    "keyfile_utils",
                    "config_status",
                    "recovery",
                    "sign_scripts",
                    "verify_integrity",
                    "challenge_hash",
                    "update",
                    "help",
                ],
            )
        ]

    # Build operation number mapping (1-indexed, skip exit which is 0)
    op_to_num = {}
    item_num = 1
    for section_name, ops in menu_sections:
        for op_id in ops:
            op_to_num[op_id] = item_num
            item_num += 1

    # Render sections
    first_section = True
    for section_name, ops in menu_sections:
        # Section separator (except for first section)
        if not first_section:
            print(v + " " * width + v)
            # Lighter separator
            section_sep = h if style else "─"
            print(f"{v}  {section_sep * 20}" + " " * (width - 24) + v)
        first_section = False

        # Section header
        print(f"{v}  {section_name.upper()}" + " " * (width - len(section_name) - 2) + v)

        # Render operations in section
        for op_id in ops:
            if CLIOperations is not None:
                op_meta = CLIOperations.get_operation(op_id)
            else:
                op_meta = {}

            # Get label (with style-aware transformation)
            unicode_label = op_meta.get("label", op_id)
            if style and hasattr(style, "label_for_op"):
                label = style.label_for_op(op_id, unicode_label)
            else:
                label = unicode_label

            requires_admin = op_meta.get("requires_admin", False)
            num = op_to_num.get(op_id, 0)

            prefix = f"  [{num:>2}]"

            if requires_admin and not admin_status:
                # Show disabled with admin hint
                suffix = "[ADMIN]"
                line_content = f"{prefix} {label}"
                padding = width - len(line_content) - len(suffix) - 1
                if padding < 1:
                    padding = 1
                line = f"{v}{line_content}{' ' * padding}{suffix}{v}"
            else:
                line_content = f"{prefix} {label}"
                padding = width - len(line_content)
                if padding < 1:
                    padding = 1
                line = f"{v}{line_content}{' ' * padding}{v}"

            print(line)

    # Exit option
    print(v + " " * width + v)
    exit_label = style.label_for_op("exit", "❌ Exit") if style and hasattr(style, "label_for_op") else "❌ Exit"
    print(f"{v}  [ 0] {exit_label}" + " " * (width - len(exit_label) - 8) + v)
    print(v + " " * width + v)

    # Admin hint footer
    if not admin_status:
        # Check if any operation actually requires admin
        any_admin_required = False
        if CLIOperations is not None:
            for section_name, ops in menu_sections:
                for op_id in ops:
                    if CLIOperations.is_admin_required(op_id):
                        any_admin_required = True
                        break

        if any_admin_required:
            print(ml + h * width + mr)
            hint = "[ADMIN] = Requires administrator privileges to run"
            print(f"{v}  {hint}" + " " * (width - len(hint) - 2) + v)

    print(bl + h * width + br)


def print_menu_smartdrive():
    """Print menu for SMARTDRIVE context. DEPRECATED - use print_unified_menu."""
    # Delegate to unified menu
    print_unified_menu(is_admin())


def print_menu_system():
    """Print menu for SYSTEM context. DEPRECATED - use print_unified_menu."""
    # Delegate to unified menu
    print_unified_menu(is_admin())


def print_keyfile_menu():
    """Print keyfile utilities submenu."""
    style = ConsoleStyle.detect()
    tl = style.symbol("BOX_TL")
    tr = style.symbol("BOX_TR")
    bl = style.symbol("BOX_BL")
    br = style.symbol("BOX_BR")
    ml = style.symbol("BOX_ML")
    mr = style.symbol("BOX_MR")
    h = style.symbol("BOX_H")
    v = style.symbol("BOX_V")

    lock = style.symbol("LOCK")
    unlock = style.symbol("UNLOCK")
    encrypt = style.symbol("ENCRYPT")
    back = style.symbol("BACK")

    print()
    print(tl + h * 68 + tr)
    print(v + "  KEYFILE UTILITIES" + " " * 49 + v)
    print(ml + h * 68 + mr)
    print(v + " " * 68 + v)
    print(v + f"  [1] {lock} Create new keyfile (encrypted to YubiKeys)".ljust(68) + v)
    print(v + f"  [2] {unlock} Decrypt keyfile (for recovery/migration)".ljust(68) + v)
    print(v + f"  [3] {encrypt} Encrypt existing file to YubiKeys".ljust(68) + v)
    print(v + " " * 68 + v)
    print(v + f"  [0] {back} Back to main menu".ljust(68) + v)
    print(v + " " * 68 + v)
    print(bl + h * 68 + br)


# ============================================================
# CONTEXT DETECTION (for path resolution ONLY, NOT for menu/feature gating)
# ============================================================


def detect_context() -> str:
    """
    Detect execution context for PATH RESOLUTION ONLY.

    This is used ONLY to determine where to find scripts and config files.
    It must NOT be used to decide which menu options to show or which
    features are available. All features are shown in unified menu.

    Returns:
        "SMARTDRIVE" if running from deployed .smartdrive structure
        "SYSTEM" if running from development environment
    """
    # Check directory structure for path resolution
    if SCRIPT_DIR.parent.name == ".smartdrive":
        return "SMARTDRIVE"
    return "SYSTEM"


def check_mount_status() -> bool:
    """
    Check if the volume is currently mounted.
    Returns True if mounted, False if not, None if unknown.
    """
    if not CONFIG_FILE.exists():
        return None

    try:
        import json

        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)

        system = platform.system().lower()

        if system == "windows":
            mount_letter = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.MOUNT_LETTER, "V")
            drive_path = Path(f"{mount_letter}:/")
            return drive_path.exists() and drive_path.is_dir()
        else:
            mount_point = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.MOUNT_POINT, "")
            if mount_point:
                mount_path = Path(mount_point).expanduser()
                # Check if something is mounted there
                if mount_path.exists():
                    # On Unix, check if it's a mount point
                    try:
                        result = subprocess.run(["mountpoint", "-q", str(mount_path)], capture_output=True)
                        return result.returncode == 0
                    except FileNotFoundError:
                        # mountpoint command not available, check if dir has content
                        return any(mount_path.iterdir())
            return False
    except Exception:
        return None


# ============================================================
# ACTION HANDLERS
# ============================================================


def run_script(script_name: str, args: list = None):
    """Run a Python script from the scripts directory.

    Always passes --config explicitly to avoid cwd-based path guessing,
    EXCEPT for scripts that use subcommands (keyfile.py) where --config
    would interfere with argparse subparser ordering.

    BUG-20251218-001 FIX: keyfile.py uses subparsers and doesn't accept --config.
    Put args BEFORE --config for scripts that have subcommands.
    """
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    failure = style.symbol("FAILURE")
    divider = style.symbol("MENU_DIVIDER")

    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        print(f"\n{failure} Error: Script not found: {script_path}")
        input("\nPress Enter to continue...")
        return False

    cmd = [sys.executable, str(script_path)]

    # Scripts with subcommands need args FIRST (no --config support)
    scripts_no_config = {"keyfile.py"}
    if script_name in scripts_no_config:
        # These scripts don't accept --config
        if args:
            cmd.extend(args)
    else:
        # Standard scripts: pass --config for consistent path resolution
        cmd.extend(["--config", str(CONFIG_FILE)])
        if args:
            cmd.extend(args)

    print(f"\n{divider * 70}")
    print(f"Running: {script_name}")
    print(divider * 70 + "\n")

    try:
        result = subprocess.run(cmd)
        print("\n" + divider * 70)
        if result.returncode == 0:
            print(f"{success} {script_name} completed successfully")
        else:
            print(f"{warning} {script_name} exited with code {result.returncode}")
        print(divider * 70)
    except KeyboardInterrupt:
        print(f"\n\n{warning} Operation cancelled by user")
    except Exception as e:
        print(f"\n{failure} Error running {script_name}: {e}")

    input("\nPress Enter to continue...")
    return True


def show_config_status():
    """Display current configuration and status."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    failure = style.symbol("FAILURE")
    info = style.symbol("INFO")
    divider = style.symbol("MENU_DIVIDER")

    clear_screen()
    print_banner()
    print("\n" + divider * 70)
    print("  CONFIGURATION & STATUS")
    print(divider * 70 + "\n")

    # Context
    context = detect_context()
    print(f"  Context:      {context}")
    print(f"  Script dir:   {SCRIPT_DIR}")
    print(f"  Keys dir:     {KEYS_DIR}")
    print()

    # Config file
    cfg = {}
    if CONFIG_FILE.exists():
        print(f"  {success} Config:     {CONFIG_FILE.name}")
        try:
            import json

            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)

            # Drive name
            drive_name = cfg.get(ConfigKeys.DRIVE_NAME)
            if drive_name:
                print(f"    Name:       {drive_name}")
            else:
                print(f"    Name:       Not set (use option below to set)")

            # Security mode
            security_mode = cfg.get("security_mode", "unknown")
            mode_display = get_security_mode_display(security_mode)
            print(f"    Security:   {mode_display}")

            # Setup date
            setup_date = cfg.get(ConfigKeys.SETUP_DATE)
            if setup_date:
                print(f"    Setup:      {setup_date}")

            # Last password change
            last_pw = cfg.get(ConfigKeys.LAST_PASSWORD_CHANGE)
            if last_pw:
                try:
                    from datetime import datetime

                    last_change = datetime.strptime(last_pw, "%Y-%m-%d")
                    days_ago = (datetime.now() - last_change).days
                    if days_ago > 90:
                        print(f"    Password:   {last_pw} ({warning} {days_ago} days - consider rotating)")
                    else:
                        print(f"    Password:   {last_pw} ({days_ago} days ago)")
                except:
                    print(f"    Password:   {last_pw}")

            print()

            system = platform.system().lower()
            if system == "windows":
                vol_path = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.VOLUME_PATH, "Not set")
                mount_letter = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.MOUNT_LETTER, "V")
                print(f"    Volume:     {vol_path}")
                print(f"    Mount:      {mount_letter}:")
            else:
                vol_path = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.VOLUME_PATH, "Not set")
                mount_point = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.MOUNT_POINT, "Not set")
                print(f"    Volume:     {vol_path}")
                print(f"    Mount:      {mount_point}")

            keyfile = cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, "")
            if keyfile:
                print(f"    Keyfile:    {keyfile} (GPG encrypted)")
            else:
                plain_keyfile = cfg.get(ConfigKeys.KEYFILE, "")
                if plain_keyfile:
                    print(f"    Keyfile:    {plain_keyfile} (plain)")
                else:
                    print(f"    Keyfile:    None (password-only mode)")
        except Exception as e:
            print(f"    {warning} Error reading config: {e}")
    else:
        print(f"  {failure} Config:     Not found")

    print()

    # Encrypted keyfile
    if KEYS_DIR.exists():
        gpg_files = list(KEYS_DIR.glob("*.gpg"))
        if gpg_files:
            print(f"  {success} Keyfiles:   {len(gpg_files)} encrypted keyfile(s)")
            for gpg in gpg_files:
                print(f"                - {gpg.name}")
        else:
            print(f"  {failure} Keyfiles:   No encrypted keyfiles found")
    else:
        print(f"  {failure} Keys dir:   Not found")

    print()

    # Mount status
    is_mounted = check_mount_status()
    if is_mounted is True:
        print(f"  {success} Volume:     MOUNTED")
    elif is_mounted is False:
        print(f"  {failure} Volume:     Not mounted")
    else:
        print(f"  {info} Volume:     Status unknown")

    print("\n" + divider * 70)

    # Option to set drive name
    if CONFIG_FILE.exists():
        print("\n  [N] Set/change drive name")
        print("  [Enter] Back to menu")
        choice = input("\n  > ").strip().lower()

        if choice == "n":
            set_drive_name()
    else:
        input("\nPress Enter to continue...")


def set_drive_name():
    """Set or change the drive name in config."""
    import json

    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    failure = style.symbol("FAILURE")

    if not CONFIG_FILE.exists():
        print(f"\n  {failure} No config.json found")
        input("\n  Press Enter to continue...")
        return

    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)

        current_name = cfg.get(ConfigKeys.DRIVE_NAME, "")
        print(f"\n  Current name: {current_name or '(not set)'}")
        print("  Enter new name (or press Enter to cancel):")
        new_name = input("  > ").strip()

        if new_name:
            cfg[ConfigKeys.DRIVE_NAME] = new_name
            # ALWAYS use atomic write - no fallback
            if _HAS_ATOMIC_WRITE:
                write_config_atomic(CONFIG_FILE, cfg)
            else:
                raise ImportError("write_config_atomic required but not available")
            print(f"\n  {success} Drive name set to: {new_name}")
        else:
            print("\n  Cancelled.")
    except Exception as e:
        print(f"\n  {failure} Error: {e}")

    input("\n  Press Enter to continue...")


# ============================================================
# README DOCUMENTATION VIEWER
# ============================================================

# Try to import Rich for beautiful markdown rendering
RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    pass


def find_readme() -> Path:
    """Find README.md in project structure."""
    # Try various locations
    candidates = [
        SCRIPT_DIR.parent / "README.md",  # Standard location
        SCRIPT_DIR / "README.md",  # In scripts folder
        Path.cwd() / "README.md",  # Current directory
        Path.cwd().parent / "README.md",  # Parent directory
    ]

    for path in candidates:
        if path.exists():
            return path
    return None


def show_documentation_rich(readme_path: Path):
    """Display README.md using Rich library for beautiful rendering."""
    console = Console()

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        console.print(f"[red]Error reading README: {e}[/red]")
        input("\nPress Enter to continue...")
        return

    # Split into sections for paginated viewing
    sections = []
    current_section = []
    current_title = "Introduction"

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections.append((current_title, "\n".join(current_section)))
            current_title = line[3:].strip()
            current_section = [line]
        else:
            current_section.append(line)

    if current_section:
        sections.append((current_title, "\n".join(current_section)))

    current_idx = 0

    while True:
        console.clear()

        # Header
        console.print(Panel(Text("📖 SmartDrive Documentation", justify="center", style="bold cyan"), style="cyan"))

        if sections:
            title, section_content = sections[current_idx]

            # Section indicator
            console.print(f"\n[dim]Section {current_idx + 1} of {len(sections)}[/dim]")
            console.print()

            # Render markdown
            md = Markdown(section_content)
            console.print(md)

        # Navigation footer
        console.print("\n" + "─" * 70)
        console.print("[bold]Navigation:[/bold]")
        nav_options = []
        if current_idx > 0:
            nav_options.append("[b] Previous section")
        if current_idx < len(sections) - 1:
            nav_options.append("[Enter/n] Next section")
        nav_options.append("[t] Table of contents")
        nav_options.append("[q] Quit")
        console.print("  " + "  │  ".join(nav_options))
        console.print("─" * 70)

        choice = input("  > ").strip().lower()

        if choice == "q":
            break
        elif choice == "b" and current_idx > 0:
            current_idx -= 1
        elif choice == "t":
            show_toc_rich(console, sections)
            # Let user jump to a section
            try:
                jump = input("\n  Jump to section (1-{}) or Enter to cancel: ".format(len(sections))).strip()
                if jump.isdigit():
                    idx = int(jump) - 1
                    if 0 <= idx < len(sections):
                        current_idx = idx
            except:
                pass
        elif choice in ("", "n") and current_idx < len(sections) - 1:
            current_idx += 1


def show_toc_rich(console, sections: list):
    """Show table of contents with Rich."""
    console.clear()
    console.print(Panel(Text("📑 Table of Contents", justify="center", style="bold cyan"), style="cyan"))
    console.print()

    for i, (title, _) in enumerate(sections, 1):
        console.print(f"  [bold cyan]{i:2}.[/bold cyan] {title}")

    console.print("\n" + "─" * 70)


def format_markdown_line(line: str, in_code_block: bool, in_table: bool) -> tuple:
    """
    Format a single markdown line for terminal display (fallback mode).
    Returns (formatted_line, in_code_block, in_table).
    """
    import re

    stripped = line.rstrip()

    # Code block handling
    if stripped.startswith("```"):
        if in_code_block:
            return ("  └" + "─" * 66 + "┘", False, in_table)
        else:
            lang = stripped[3:].strip() or "code"
            return ("  ┌" + f"─ {lang} " + "─" * (64 - len(lang)) + "┐", True, in_table)

    if in_code_block:
        # Inside code block - show with indent and border
        content = line.rstrip()[:64]
        return (f"  │ {content:<64} │", True, in_table)

    # Table detection
    if "|" in stripped and stripped.startswith("|"):
        return (f"  {stripped}", in_code_block, True)
    elif in_table and not stripped.startswith("|") and stripped:
        in_table = False

    # Headers
    if stripped.startswith("# "):
        title = stripped[2:]
        return ("\n" + "═" * 70 + f"\n  {title.upper()}\n" + "═" * 70, in_code_block, in_table)
    elif stripped.startswith("## "):
        title = stripped[3:]
        return ("\n" + "─" * 70 + f"\n  {title}\n" + "─" * 70, in_code_block, in_table)
    elif stripped.startswith("### "):
        title = stripped[4:]
        return (f"\n  ▸ {title}\n", in_code_block, in_table)
    elif stripped.startswith("#### "):
        title = stripped[5:]
        return (f"\n    ▹ {title}", in_code_block, in_table)

    # Horizontal rules
    if stripped in ("---", "***", "___"):
        return ("\n" + "─" * 70 + "\n", in_code_block, in_table)

    # List items
    if stripped.startswith("- "):
        return (f"    • {stripped[2:]}", in_code_block, in_table)
    if stripped.startswith("* "):
        return (f"    • {stripped[2:]}", in_code_block, in_table)

    # Numbered lists
    for i in range(1, 10):
        if stripped.startswith(f"{i}. "):
            return (f"    {i}. {stripped[3:]}", in_code_block, in_table)

    # Bold and emphasis (simple replacement)
    result = stripped
    # **bold** → BOLD
    result = re.sub(r"\*\*([^*]+)\*\*", lambda m: m.group(1).upper(), result)
    # *italic* → _italic_
    result = re.sub(r"\*([^*]+)\*", r"_\1_", result)
    # `code` → [code]
    result = re.sub(r"`([^`]+)`", r"[\1]", result)

    # Regular paragraph
    if result:
        return (f"  {result}", in_code_block, in_table)
    else:
        return ("", in_code_block, in_table)


def show_documentation_fallback(readme_path: Path):
    """Display README.md with basic formatting (no Rich library)."""
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"\n  Error reading README: {e}")
        input("\n  Press Enter to continue...")
        return

    # Format all lines
    formatted_lines = []
    in_code_block = False
    in_table = False

    for line in lines:
        formatted, in_code_block, in_table = format_markdown_line(line, in_code_block, in_table)
        if formatted:
            formatted_lines.append(formatted)

    # Pagination
    terminal_height = 30  # Approximate lines per page
    total_lines = len(formatted_lines)
    current_line = 0

    while current_line < total_lines:
        clear_screen()
        print("═" * 70)
        print("  📖 SmartDrive Documentation")
        if not RICH_AVAILABLE:
            print("  [Tip: Install 'rich' package for better rendering: pip install rich]")
        print("═" * 70)

        # Show a page of content
        page_end = min(current_line + terminal_height - 6, total_lines)
        for i in range(current_line, page_end):
            print(formatted_lines[i])

        # Navigation footer
        print("\n" + "─" * 70)
        progress = f"Line {current_line + 1}-{page_end} of {total_lines}"
        print(f"  {progress}")
        print("  [Enter] Next page  [b] Back  [q] Quit  [t] Table of contents")
        print("─" * 70)

        choice = input("  > ").strip().lower()

        if choice == "q":
            break
        elif choice == "b":
            current_line = max(0, current_line - terminal_height + 6)
        elif choice == "t":
            show_table_of_contents(formatted_lines)
            current_line = 0  # Reset to start after TOC
        else:
            current_line = page_end


def show_documentation():
    """Display README.md - uses Rich if available, otherwise fallback."""
    readme_path = find_readme()

    if not readme_path:
        clear_screen()
        print_banner()
        print("\n" + "─" * 70)
        print("  README NOT FOUND")
        print("─" * 70 + "\n")
        print("  Could not find README.md in the expected locations.")
        print("\n  Searched in:")
        print(f"    • {SCRIPT_DIR.parent / 'README.md'}")
        print(f"    • {SCRIPT_DIR / 'README.md'}")
        print(f"    • {Path.cwd() / 'README.md'}")
        input("\n  Press Enter to continue...")
        return

    if RICH_AVAILABLE:
        show_documentation_rich(readme_path)
    else:
        show_documentation_fallback(readme_path)


def show_table_of_contents(lines: list):
    """Show a table of contents extracted from headers (fallback mode)."""
    clear_screen()
    print("═" * 70)
    print("  📑 TABLE OF CONTENTS")
    print("═" * 70 + "\n")

    toc = []
    for i, line in enumerate(lines):
        if line.strip().startswith("═") and i + 1 < len(lines):
            # Main header (##)
            next_line = lines[i + 1].strip()
            if next_line and not next_line.startswith("═") and not next_line.startswith("─"):
                toc.append(f"  {next_line}")
        elif line.strip().startswith("  ▸ "):
            # Subheader (###)
            toc.append(f"    {line.strip()}")

    # Remove duplicates while preserving order
    seen = set()
    unique_toc = []
    for item in toc:
        if item not in seen:
            seen.add(item)
            unique_toc.append(item)

    for item in unique_toc[:40]:  # Limit to 40 items
        print(item)

    if len(unique_toc) > 40:
        print(f"\n  ... and {len(unique_toc) - 40} more sections")

    print("\n" + "─" * 70)
    input("  Press Enter to return to documentation...")


def show_help():
    """Display help - either README or basic help."""
    readme_path = find_readme()

    if readme_path:
        # Show full README with pagination
        show_documentation()
    else:
        # Fallback to basic help
        clear_screen()
        print_banner()
        print("\n" + "─" * 70)
        print("  HELP & DOCUMENTATION")
        print("─" * 70 + "\n")

        print(
            f"""
  SmartDrive creates encrypted external drives with optional YubiKey 2FA.

  SECURITY MODES:
  ───────────────
  • Password-only:     VeraCrypt password protection
  • Plain keyfile:     Password + unencrypted keyfile
  • YubiKey + GPG:     Password + YubiKey-encrypted keyfile (recommended)

  TYPICAL WORKFLOW:
  ─────────────────
  1. Run setup.py to prepare a new external drive
  2. Use mount.py to mount the encrypted volume
  3. Use unmount.py when done
  4. Use rekey.py to change password or rotate keyfiles

  FILES:
  ──────
  • {FileNames.CONFIG_JSON}        Volume path and mount settings
  • {FileNames.KEYFILE_GPG}     GPG-encrypted keyfile (if using YubiKey mode)
  
  For full documentation, see README.md in the project root.
"""
        )

        print("─" * 70)
        input("\nPress Enter to continue...")


# ============================================================
# INTEGRITY VERIFICATION (GPG Signature)
# ============================================================

import hashlib
import shutil


def have_gpg() -> bool:
    """Check if GPG is available."""
    return shutil.which("gpg") is not None


def calculate_scripts_hash() -> str:
    """Calculate SHA256 hash of all script files."""
    hash_obj = hashlib.sha256()

    # List of scripts to hash (in consistent order)
    # Only include scripts that are deployed to SMARTDRIVE partition
    # (setup.py is NOT deployed, so it's excluded)
    scripts = sorted(
        [FileNames.KEYDRIVE_PY, FileNames.MOUNT_PY, FileNames.UNMOUNT_PY, FileNames.REKEY_PY, FileNames.KEYFILE_PY]
    )

    for script_name in scripts:
        script_path = SCRIPT_DIR / script_name
        if script_path.exists():
            # Include filename in hash to detect renames
            hash_obj.update(script_name.encode("utf-8"))
            with open(script_path, "rb") as f:
                hash_obj.update(f.read())

    return hash_obj.hexdigest()


def generate_challenge_hash():
    """Generate a salted hash for remote verification."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    failure = style.symbol("FAILURE")
    lock = style.symbol("LOCK")
    divider = style.symbol("MENU_DIVIDER")
    double = style.symbol("MENU_DOUBLE")

    clear_screen()
    print_banner()
    print("\n" + divider * 70)
    print(f"  {lock} CHALLENGE HASH GENERATION (Remote Verification)")
    print(divider * 70 + "\n")

    print(f"{warning}  SECURITY WARNING:")
    print("   This automated verification CANNOT detect sophisticated system compromises!")
    print("   For maximum security, perform MANUAL partition verification using official")
    print("   server guidelines. This automated tool is for convenience only.")
    print()
    print("   Manual verification requires you to personally witness:")
    print("   • Accessing the official server endpoint (verify domain authenticity)")
    print("   • Copying the salt file to your SMARTDRIVE partition")
    print("   • Manually hashing the entire partition (excluding config files)")
    print("   • Submitting and verifying the server response")
    print()

    confirm = input("  Continue with automated verification? [y/N]: ").strip().lower()
    if confirm != "y":
        print("\n  Cancelled. Please perform manual verification for maximum security.")
        input("\n  Press Enter to continue...")
        return

    print("\nThis generates a salted hash of your ENTIRE scripts directory for secure remote verification.")
    print("The process ensures that:")
    print("• No one can pre-compute the correct hash")
    print("• Tampered scripts cannot generate valid hashes")
    print("• Verification requires manual server interaction")
    print()

    # Get server endpoint from user
    print("Enter the verification server endpoint URL:")
    print(f"{warning}  CRITICAL: Verify this is the OFFICIAL, UNALTERED domain!")
    server_endpoint = input("Server URL: ").strip()

    if not server_endpoint:
        print(f"\n{failure} No server endpoint provided.")
        input("\nPress Enter to continue...")
        return

    # Get salt from user
    print("\nEnter the salt/challenge from the verification server:")
    salt = input("Salt: ").strip()

    if not salt:
        print(f"\n{failure} No salt provided.")
        input("\nPress Enter to continue...")
        return

    # Save salt to a file in the scripts directory (atomically)
    salt_file = SCRIPT_DIR / ".challenge_salt"
    try:
        if write_file_atomic:
            write_file_atomic(salt_file, salt)
        else:
            # Fallback: manual atomic write
            tmp_file = salt_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                f.write(salt)
                f.flush()
                import os as _os

                _os.fsync(f.fileno())
            tmp_file.replace(salt_file)
        print(f"{success} Salt saved to: {salt_file}")
    except Exception as e:
        print(f"{failure} Error saving salt file: {e}")
        input("\nPress Enter to continue...")
        return

    # Hash the entire scripts directory INCLUDING the salt file
    try:
        challenge_hash = hash_directory_with_salt(SCRIPT_DIR)
        print("\n" + double * 70)
        print(f"  {success} DIRECTORY HASH GENERATED")
        print(double * 70)
        print(f"\nDirectory:   {SCRIPT_DIR}")
        print(f"Salt file:   {salt_file}")
        print(f"Server URL:  {server_endpoint}")
        print(f"Result:      {challenge_hash}")
        print()
        print(f"{warning}  REMINDER: This automated verification may be spoofed on compromised systems!")
        print("   For maximum security, perform manual partition verification.")
        print()
        print("Submit this information to your verification server:")
        print(f"  Challenge Hash: {challenge_hash}")
        print(f"  Server Endpoint: {server_endpoint}")
        print()
        print(f"{warning}  IMPORTANT: The server must have the same clean scripts")
        print("   directory and will add the salt file before hashing.")

    except Exception as e:
        print(f"{failure} Error generating hash: {e}")
    finally:
        # Clean up salt file
        try:
            if salt_file.exists():
                salt_file.unlink()
                print(f"{success} Salt file cleaned up: {salt_file}")
        except Exception as e:
            print(f"{warning}  Warning: Could not clean up salt file: {e}")

    input("\nPress Enter to continue...")

    input("\nPress Enter to continue...")


def hash_directory_with_salt(dir_path: Path) -> str:
    """Hash an entire directory recursively, including all files."""
    hash_obj = hashlib.sha256()

    # Get all files in sorted order for consistent hashing
    all_files = []
    for root, dirs, files in os.walk(dir_path):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git"]]
        for file in files:
            # Skip temporary files and certain extensions
            if not file.startswith(".") or file == ".challenge_salt":
                all_files.append(str(Path(root) / file))

    all_files.sort()

    for file_path in all_files:
        # Include relative path in hash to detect file moves
        rel_path = os.path.relpath(file_path, dir_path)
        hash_obj.update(rel_path.encode("utf-8"))
        hash_obj.update(b"\x00")  # Separator

        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
        except (OSError, IOError) as e:
            # Skip files that can't be read
            hash_obj.update(f"[ERROR: {e}]".encode("utf-8"))

        hash_obj.update(b"\x00")  # File separator

    return hash_obj.hexdigest()


def get_hash_file_path() -> Path:
    """Get path to the hash file."""
    return INTEGRITY_DIR / "scripts.sha256"


def get_signature_file_path() -> Path:
    """Get path to the signature file."""
    return INTEGRITY_DIR / "scripts.sha256.sig"


def verify_integrity():
    """Verify script integrity using GPG signature."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    failure = style.symbol("FAILURE")
    verify_sym = style.symbol("VERIFY")
    divider = style.symbol("MENU_DIVIDER")
    double = style.symbol("MENU_DOUBLE")

    clear_screen()
    print_banner()
    print("\n" + divider * 70)
    print(f"  {verify_sym} SCRIPT INTEGRITY VERIFICATION")
    print(divider * 70 + "\n")

    hash_file = get_hash_file_path()
    sig_file = get_signature_file_path()

    # Check if signature files exist
    if not hash_file.exists():
        print(f"  {failure} Hash file not found: scripts.sha256")
        print("     Scripts have not been signed yet.")
        print("\n     To sign scripts, run from System menu or use:")
        print("     gpg --detach-sign scripts.sha256")
        input("\n  Press Enter to continue...")
        return

    if not sig_file.exists():
        print(f"  {failure} Signature file not found: scripts.sha256.sig")
        print("     Scripts have not been signed yet.")
        print("\n     To sign scripts, run from System menu or use:")
        print("     gpg --detach-sign scripts.sha256")
        input("\n  Press Enter to continue...")
        return

    if not have_gpg():
        print(f"  {failure} GPG not found in PATH")
        print("     Cannot verify signature without GPG installed.")
        input("\n  Press Enter to continue...")
        return

    print("  Checking integrity...\n")

    # Step 1: Verify GPG signature
    print("  Step 1: Verifying GPG signature...")
    signature_time = None
    signer_info = None

    try:
        result = subprocess.run(["gpg", "--verify", str(sig_file), str(hash_file)], capture_output=True, text=True)

        if result.returncode == 0:
            print(f"  {success} GPG signature is VALID")
            # Extract signer info and timestamp from stderr (GPG outputs to stderr)
            for line in result.stderr.split("\n"):
                if "Good signature" in line:
                    signer_info = line.strip()
                    print(f"     {signer_info}")
                elif "Signature made" in line:
                    signature_time = line.strip()
                    print(f"     {signature_time}")
                elif "using" in line and "key" in line.lower():
                    print(f"     {line.strip()}")
        else:
            print(f"  {failure} GPG signature is INVALID!")
            print(f"\n  {warning}  WARNING: Scripts may have been tampered with!")
            print("     Do NOT use these scripts!")
            print("\n  GPG output:")
            for line in result.stderr.split("\n"):
                if line.strip():
                    print(f"     {line}")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"  {failure} Error verifying signature: {e}")
        input("\n  Press Enter to continue...")
        return

    # Step 2: Verify file hashes match
    print("\n  Step 2: Verifying file hashes...")

    # Read stored hash
    try:
        with open(hash_file, "r") as f:
            stored_data = f.read().strip()
        stored_hash = stored_data.split()[0]  # Format: "hash  filename" or just "hash"
    except Exception as e:
        print(f"  {failure} Error reading hash file: {e}")
        input("\n  Press Enter to continue...")
        return

    # Calculate current hash
    current_hash = calculate_scripts_hash()

    if current_hash == stored_hash:
        print(f"  {success} File hashes MATCH")
        print(f"     Hash: {current_hash[:16]}...{current_hash[-16:]}")
    else:
        print(f"  {failure} File hashes DO NOT MATCH!")
        print(f"\n  {warning}  WARNING: Scripts have been modified!")
        print("     Do NOT use these scripts!")
        print(f"\n     Expected: {stored_hash[:32]}...")
        print(f"     Got:      {current_hash[:32]}...")
        input("\n  Press Enter to continue...")
        return

        return

    # Step 3: Manual salted hash generation for remote verification
    print("\n  Step 3: Manual verification hash generation")
    print("     For secure remote verification, use the 'Generate Challenge Hash' option")
    print("     from the main menu to create a salted hash for server verification.")

    # All checks passed
    print("\n" + double * 70)
    print(f"  {success} INTEGRITY CHECK PASSED")
    print("     Scripts are authentic and unmodified.")
    print("     (Local verification only)")
    print(double * 70)

    # Show timestamp warning
    print("\n" + divider * 70)
    print(f"  {warning}  IMPORTANT: Check the signature timestamp above!")
    print(divider * 70)
    print(
        """
  A valid signature only proves the scripts were signed by YOUR key.
  If an attacker had access while your YubiKey was plugged in, they
  could have modified scripts AND re-signed them.

  Ask yourself:
  • Does the signature timestamp match when YOU last signed?
  • Has anyone else had access to this drive + your YubiKey?

  PROTECTION: Enable touch requirement for GPG signing:
    ykman openpgp keys set-touch sig on

  This prevents signing without physical touch, even if YubiKey
  is plugged in.
"""
    )

    input("  Press Enter to continue...")


def sign_scripts():
    """Sign scripts with GPG (creates hash + signature)."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    warning = style.symbol("WARNING")
    failure = style.symbol("FAILURE")
    sign_sym = style.symbol("SIGN")
    divider = style.symbol("MENU_DIVIDER")
    double = style.symbol("MENU_DOUBLE")

    clear_screen()
    print_banner()
    print("\n" + divider * 70)
    print(f"  {sign_sym}  SIGN SCRIPTS (Create Integrity Signature)")
    print(divider * 70 + "\n")

    if not have_gpg():
        print(f"  {failure} GPG not found in PATH")
        print("     Cannot sign without GPG installed.")
        input("\n  Press Enter to continue...")
        return

    # Ensure integrity directory exists
    INTEGRITY_DIR.mkdir(parents=True, exist_ok=True)

    hash_file = get_hash_file_path()
    sig_file = get_signature_file_path()

    print("  This will:")
    print("  1. Calculate SHA256 hash of all scripts")
    print("  2. Sign the hash with your GPG key (requires YubiKey if configured)")
    print()
    print(f"  Output files:")
    print(f"    • {hash_file}")
    print(f"    • {sig_file}")
    print()

    # Show available GPG keys
    print("  Available GPG signing keys:")
    try:
        result = subprocess.run(["gpg", "--list-secret-keys", "--keyid-format", "LONG"], capture_output=True, text=True)

        keys_found = False
        for line in result.stdout.split("\n"):
            if "sec" in line or "uid" in line:
                print(f"    {line}")
                keys_found = True

        if not keys_found:
            print("    No secret keys found!")
            print("    You need a GPG key to sign scripts.")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"    Error listing keys: {e}")

    print()
    confirm = input("  Sign scripts now? [y/N]: ").strip().lower()

    if confirm != "y":
        print("\n  Cancelled.")
        input("\n  Press Enter to continue...")
        return

    # Step 1: Calculate and save hash (atomically)
    print("\n  Step 1: Calculating hash...")
    current_hash = calculate_scripts_hash()
    hash_content = f"{current_hash}  scripts\n"

    try:
        if write_file_atomic:
            write_file_atomic(hash_file, hash_content)
        else:
            # Fallback: manual atomic write
            tmp_file = hash_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                f.write(hash_content)
                f.flush()
                import os as _os

                _os.fsync(f.fileno())
            tmp_file.replace(hash_file)
        print(f"  {success} Hash saved: {hash_file.name}")
        print(f"     {current_hash}")
    except Exception as e:
        print(f"  {failure} Error saving hash: {e}")
        input("\n  Press Enter to continue...")
        return

    # Step 2: Sign with GPG
    print("\n  Step 2: Signing with GPG...")
    print("  (You may be prompted to insert YubiKey or enter PIN)")

    try:
        # Remove old signature if exists
        if sig_file.exists():
            sig_file.unlink()

        result = subprocess.run(["gpg", "--detach-sign", str(hash_file)], capture_output=True, text=True)

        if result.returncode == 0 and sig_file.exists():
            print(f"  {success} Signature created: {sig_file.name}")
        else:
            print(f"  {failure} Signing failed!")
            if result.stderr:
                print(f"     {result.stderr}")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"  {failure} Error signing: {e}")
        input("\n  Press Enter to continue...")
        return

    # Success
    print("\n" + double * 70)
    print(f"  {success} SCRIPTS SIGNED SUCCESSFULLY")
    print()
    print("  To verify on any machine with your public key:")
    print("    gpg --verify scripts.sha256.sig scripts.sha256")
    print(double * 70)

    input("\n  Press Enter to continue...")


def keyfile_utilities_menu():
    """Handle keyfile utilities submenu."""
    while True:
        clear_screen()
        print_banner()
        print_keyfile_menu()

        choice = input("\n  Select option [0-3]: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            run_script("keyfile.py", ["create"])
        elif choice == "2":
            # Ask for file to decrypt
            print("\n  Enter path to encrypted keyfile")
            print(f"  (or press Enter for default: ../keys/{FileNames.KEYFILE_GPG})")
            filepath = input("  Path: ").strip()
            if not filepath:
                filepath = str(KEYS_DIR / FileNames.KEYFILE_GPG)
            run_script("keyfile.py", ["decrypt", filepath])
        elif choice == "3":
            print("\n  Enter path to file to encrypt:")
            filepath = input("  Path: ").strip()
            if filepath:
                run_script("keyfile.py", ["encrypt", filepath])
            else:
                style = ConsoleStyle.detect()
                warning = style.symbol("WARNING")
                print(f"\n  {warning} No file specified")
                input("\n  Press Enter to continue...")
        else:
            style = ConsoleStyle.detect()
            warning = style.symbol("WARNING")
            print(f"\n  {warning} Invalid option")
            input("\n  Press Enter to continue...")


def recovery_menu():
    """Recovery kit management submenu."""
    style = ConsoleStyle.detect()
    success = style.symbol("SUCCESS")
    failure = style.symbol("FAILURE")
    warning = style.symbol("WARNING")
    divider = style.symbol("MENU_DIVIDER")

    while True:
        clear_screen()
        print_banner()
        print("\n" + divider * 70)
        print("  RECOVERY KIT MANAGEMENT")
        print(divider * 70 + "\n")

        # Check current recovery status
        recovery_status = None
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                recovery_status = cfg.get("recovery", {})
            except:
                pass

        if recovery_status and recovery_status.get("enabled"):
            print(f"  Status: {success} Recovery Kit ENABLED")
            print(f"  Created: {recovery_status.get('created_date', 'Unknown')}")
            events = recovery_status.get("recovery_events", [])
            if events:
                print(f"  Used: {len(events)} time(s)")
                last_event = events[-1]
                print(f"  Last: {last_event.get('date')} - {last_event.get('reason')}")
        else:
            print(f"  Status: {failure} Recovery Kit NOT enabled")
            print("  ")
            print("  A recovery kit allows emergency access if you lose your")
            print("  YubiKey or password. It's a 24-word phrase that grants")
            print("  ONE-TIME access to your drive.")

        print("\n" + divider * 70)
        print()
        print("  [1] Generate new recovery kit")
        print("  [2] Check recovery status")
        if recovery_status and recovery_status.get("enabled"):
            print("  [3] Use recovery phrase (EMERGENCY)")
        print("  [0] Back to main menu")
        print()

        choice = input("  Select option: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            run_script("recovery.py", ["generate"])
        elif choice == "2":
            run_script("recovery.py", ["status"])
        elif choice == "3" and recovery_status and recovery_status.get("enabled"):
            print(f"\n  {warning}  WARNING: This will use your one-time recovery phrase!")
            print("  Only proceed if you have lost access through normal means.")
            confirm = input("\n  Continue? [y/N]: ").strip().lower()
            if confirm == "y":
                run_script("recovery.py", ["recover"])
        else:
            print(f"\n  {warning} Invalid option")
            input("\n  Press Enter to continue...")


def update_deployment_drive_menu():
    """Update deployment drive with latest SmartDrive files."""
    style = ConsoleStyle.detect()
    warning = style.symbol("WARNING")
    success = style.symbol("SUCCESS")
    failure = style.symbol("FAILURE")
    divider = style.symbol("MENU_DIVIDER")

    print("\n" + divider * 70)
    print("  UPDATE DEPLOYMENT DRIVE")
    print(divider * 70 + "\n")

    print("This will update an external drive with the latest SmartDrive scripts")
    print("and documentation from your development environment.\n")

    print(f"{warning}  IMPORTANT:")
    print("  • User data (keys, recovery kits, integrity files) will NOT be overwritten")
    print("  • Scripts, README, and documentation will be updated")
    print("  • config.json version metadata will be updated to current version")
    print("  • Make sure the target drive is not currently mounted\n")

    confirm = input("Continue with update? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Update cancelled.")
        input("\nPress Enter to continue...")
        return

    # Call the update function
    try:
        success_result = update_deployment_drive()
        if success_result:
            print(f"\n{success} Update completed successfully!")
        else:
            print(f"\n{warning} Update completed with warnings/errors.")
    except Exception as e:
        print(f"\n{failure} Update failed: {e}")

    input("\nPress Enter to continue...")


# ============================================================
# MAIN MENU LOOP - UNIFIED
# ============================================================


def get_operation_handler(op_id: str):
    """
    Get handler function for an operation ID.

    Returns tuple: (handler_function, script_name) or (None, None) if invalid.
    """
    # Map operation IDs to handlers
    handlers = {
        "mount": (lambda: run_script(FileNames.MOUNT_PY), FileNames.MOUNT_PY),
        "unmount": (lambda: run_script(FileNames.UNMOUNT_PY), FileNames.UNMOUNT_PY),
        "setup": (lambda: run_script(FileNames.SETUP_PY), FileNames.SETUP_PY),
        "rekey": (lambda: run_script(FileNames.REKEY_PY), FileNames.REKEY_PY),
        "keyfile_utils": (keyfile_utilities_menu, None),
        "config_status": (show_config_status, None),
        "recovery": (recovery_menu, None),
        "sign_scripts": (sign_scripts, None),
        "verify_integrity": (verify_integrity, None),
        "challenge_hash": (generate_challenge_hash, None),
        "update": (update_deployment_drive_menu, None),
        "help": (show_help, None),
        "exit": (None, None),
    }
    return handlers.get(op_id, (None, None))


def main_menu_unified():
    """
    Unified main menu - shows ALL operations regardless of launch context.

    Admin-required operations are shown but blocked when not running as admin.
    This is the ONLY menu loop - no context-based branching.
    """
    admin_status = is_admin()

    # Detect console style (handles broken UTF-8 in elevated PowerShell)
    style = ConsoleStyle.detect() if ConsoleStyle else None

    # Get menu order from SSOT (operations in flat order for selection mapping)
    if CLIOperations is not None and hasattr(CLIOperations, "MENU_SECTIONS"):
        # Build flat list from sections
        menu_order = []
        for section_name, ops in CLIOperations.MENU_SECTIONS:
            menu_order.extend(ops)
    elif CLIOperations is not None:
        menu_order = [op for op in CLIOperations.UNIFIED_MENU_ORDER if op != "exit"]
    else:
        menu_order = [
            "mount",
            "unmount",
            "setup",
            "rekey",
            "keyfile_utils",
            "config_status",
            "recovery",
            "sign_scripts",
            "verify_integrity",
            "challenge_hash",
            "update",
            "help",
        ]

    while True:
        clear_screen()
        is_mounted = check_mount_status()
        print_banner()
        print_status("UNIFIED", is_mounted, admin_status)
        print_unified_menu(admin_status, style)

        max_option = len(menu_order)
        choice = input(f"\n  Select option [0-{max_option}]: ").strip()

        if choice == "0":
            goodbye = "Goodbye!" if not style or style.mode == "unicode" else "Goodbye!"
            print(f"\n  {goodbye}\n")
            break

        try:
            choice_num = int(choice)
            if 1 <= choice_num <= max_option:
                op_id = menu_order[choice_num - 1]

                # Check admin requirement
                if CLIOperations is not None:
                    requires_admin = CLIOperations.is_admin_required(op_id)
                else:
                    requires_admin = op_id in ("setup", "rekey")  # Updated: mount/unmount don't require admin

                if requires_admin and not admin_status:
                    warning = style.WARNING if style else "⚠️"
                    print(f"\n  {warning} This operation requires administrator privileges.")
                    print("     Please run as Administrator (Windows) or with sudo (Linux/macOS).")
                    print("     The operation will be cancelled and you will return to the menu.")
                    input("\n  Press Enter to continue...")
                    continue

                # Execute handler
                handler, _ = get_operation_handler(op_id)
                if handler:
                    handler()
            else:
                warning = style.WARNING if style else "⚠️"
                print(f"\n  {warning} Invalid option")
                input("\n  Press Enter to continue...")
        except ValueError:
            warning = style.WARNING if style else "⚠️"
            print(f"\n  {warning} Please enter a valid number")
            input("\n  Press Enter to continue...")


# Legacy aliases for backward compatibility
def main_menu_smartdrive():
    """DEPRECATED: Use main_menu_unified instead."""
    main_menu_unified()


def main_menu_system():
    """DEPRECATED: Use main_menu_unified instead."""
    main_menu_unified()


# ============================================================
# ENTRY POINT
# ============================================================


def main():
    """
    Main entry point.

    Always shows unified menu - NO context-based menu selection.
    Context detection is used ONLY for path resolution.

    Supports --config <path> for explicit config path (avoids cwd guessing).
    """
    import argparse

    # INVARIANT CHECK: Single entrypoint
    enforce_single_entrypoint()

    parser = argparse.ArgumentParser(description="SmartDrive CLI")
    parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", help="Absolute path to config.json (propagated from caller)"
    )
    args = parser.parse_args()

    # Override global CONFIG_FILE if --config provided
    global CONFIG_FILE
    if args.config:
        config_path = Path(args.config).resolve()
        if config_path.exists():
            CONFIG_FILE = config_path
            print(f"[smartdrive] Using explicit config: {CONFIG_FILE}")
        else:
            print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

    # Initialize CLI i18n - load language from config
    init_cli_i18n(CONFIG_FILE)

    try:
        # Context is used for path resolution only, NOT for menu selection
        _ = detect_context()  # Sets up paths

        # Always use unified menu
        main_menu_unified()

    except KeyboardInterrupt:
        print("\n\n  Goodbye!\n")
        sys.exit(0)
    except Exception as e:
        style = ConsoleStyle.detect() if ConsoleStyle else None
        failure = style.symbol("FAILURE") if style else "[X]"
        print(f"\n{failure} Unexpected error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
