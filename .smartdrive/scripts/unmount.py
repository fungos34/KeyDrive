#!/usr/bin/env python3
"""
SmartDrive unmount script

Unmount a VeraCrypt volume previously mounted with mount.py.

Usage:
    python unmount.py          # Unmount using config.json settings
    python unmount.py V        # Unmount drive V: (Windows)
    python unmount.py /mnt/vc  # Unmount mount point (Linux/macOS)
    python unmount.py --all    # Unmount all VeraCrypt volumes

Dependencies (runtime):
- Python 3
- VeraCrypt:
    - Windows: VeraCrypt.exe
    - Linux/macOS: 'veracrypt' in PATH
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/unmount.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/unmount.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.constants import ConfigKeys, Defaults, FileNames
    from core.paths import Paths
    from core.platform import is_windows as _is_windows
    from core.platform import windows_refresh_explorer, windows_set_attributes

    CONFIG_FILENAME = FileNames.CONFIG_JSON
except ImportError:
    CONFIG_FILENAME = "config.json"

    class Defaults:
        WINDOWS_MOUNT_LETTER = "V"


def log(msg: str) -> None:
    print(f"[SmartDrive] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def update_drive_icon(mounted: bool):
    """Update the drive icon based on mount state (no admin required)."""
    if not _is_windows():
        return

    try:
        launcher_root = _project_root
        desktop_ini = launcher_root / "desktop.ini"

        icon_filename = FileNames.ICON_MOUNTED if mounted else FileNames.ICON_MAIN
        icon_rel = Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.STATIC_SUBDIR / icon_filename
        icon_win = icon_rel.as_posix().replace("/", "\\")

        ini_content = (
            "[.ShellClassInfo]\n"
            f"IconFile={icon_win}\n"
            "IconIndex=0\n\n"
            "[ViewState]\n"
            "Mode=\n"
            "Vid=\n"
            "FolderType=Generic\n"
        )

        with open(desktop_ini, "w", encoding="utf-8") as f:
            f.write(ini_content)

        windows_set_attributes(desktop_ini, hidden=True, system=True)
        windows_set_attributes(launcher_root, system=True)
        windows_refresh_explorer()
    except Exception as e:
        print(f"Could not update drive icon: {e}")


def load_config(config_path: Path = None) -> dict:
    """Load config.json from specified path or infer from script location.

    Args:
        config_path: Optional explicit path to config.json

    Returns:
        Config dictionary, or empty dict if not found
    """
    if config_path:
        cfg_path = Path(config_path)
    else:
        # Infer from script location
        script_dir = Path(__file__).resolve().parent
        if script_dir.parent.name == ".smartdrive":
            # Deployed: config at .smartdrive/config.json
            cfg_path = script_dir.parent / CONFIG_FILENAME
        else:
            # Development: check .smartdrive first, then scripts/
            if (script_dir.parent / ".smartdrive" / CONFIG_FILENAME).exists():
                cfg_path = script_dir.parent / ".smartdrive" / CONFIG_FILENAME
            else:
                cfg_path = script_dir / CONFIG_FILENAME

    if not cfg_path.exists():
        return {}

    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_veracrypt_windows() -> Path | None:
    """Find VeraCrypt.exe on Windows using core.paths."""
    # First check PATH
    vc_which = shutil.which(Paths.VERACRYPT_EXE_NAME)
    if vc_which:
        return Path(vc_which)

    # Use centralized path from core.paths
    try:
        vc_path = Paths.veracrypt_exe()
        if vc_path and vc_path.exists():
            return vc_path
    except (RuntimeError, NameError):
        pass
    return None


def unmount_windows(vc_exe: Path, target: str | None = None, unmount_all: bool = False) -> bool:
    """Unmount VeraCrypt volume(s) on Windows.

    Args:
        vc_exe: Path to VeraCrypt.exe
        target: Drive letter to unmount (e.g., "V" or "V:")
        unmount_all: If True, unmount all volumes

    Returns:
        True if successful, False otherwise.
    """
    args = [str(vc_exe), "/q", "/s"]

    if unmount_all:
        args.append("/d")  # Dismount all
        log("Unmounting all VeraCrypt volumes...")
    elif target:
        # Normalize drive letter (remove colon if present)
        letter = target.strip().rstrip(":").upper()
        if len(letter) != 1 or not letter.isalpha():
            error(f"Invalid drive letter: {target}")
            return False
        args.extend(["/d", letter])
        log(f"Unmounting drive {letter}:...")
    else:
        error("No target specified. Use a drive letter or --all")
        return False

    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            if unmount_all:
                log("[OK] All volumes unmounted successfully")
            else:
                log(f"[OK] Drive {target}: unmounted successfully")
            # Update drive icon to unmounted state
            update_drive_icon(False)
            return True
        else:
            if "not mounted" in result.stderr.lower() or result.returncode == 1:
                log(f"Volume was not mounted")
                return True
            error(f"Unmount failed: {result.stderr}")
            return False
    except Exception as e:
        error(f"Failed to run VeraCrypt: {e}")
        return False


def unmount_unix(target: str | None = None, unmount_all: bool = False) -> bool:
    """Unmount VeraCrypt volume(s) on Linux/macOS.

    BUG-20260102-020: VeraCrypt on Linux requires root privileges for unmount.
    Use pkexec (PolicyKit) to elevate just the VeraCrypt command.

    Args:
        target: Mount point to unmount (e.g., "/mnt/veracrypt")
        unmount_all: If True, unmount all volumes

    Returns:
        True if successful, False otherwise.
    """
    # BUG-20260102-020: Use pkexec for privilege elevation on Linux
    needs_elevation = os.geteuid() != 0
    elevation_prefix = []
    if needs_elevation:
        if shutil.which("pkexec"):
            elevation_prefix = ["pkexec"]
            log("Using pkexec for privilege elevation")
        else:
            log("WARNING: pkexec not found, unmount may fail without root privileges")

    if unmount_all:
        args = elevation_prefix + ["veracrypt", "--text", "--dismount"]
        log("Unmounting all VeraCrypt volumes...")
    elif target:
        # Expand ~ in path
        mount_point = str(Path(target).expanduser())
        args = elevation_prefix + ["veracrypt", "--text", "--dismount", mount_point]
        log(f"Unmounting {mount_point}...")
    else:
        error("No target specified. Use a mount point or --all")
        return False

    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            if unmount_all:
                log("[OK] All volumes unmounted successfully")
            else:
                log(f"[OK] {target} unmounted successfully")
            return True
        else:
            if "not mounted" in result.stderr.lower():
                log(f"Volume was not mounted")
                return True
            error(f"Unmount failed: {result.stderr}")
            return False
    except Exception as e:
        error(f"Failed to run veracrypt: {e}")
        return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Unmount SmartDrive encrypted volume")
    parser.add_argument("target", nargs="?", help="Drive letter (Windows) or mount point (Unix)")
    parser.add_argument("--all", "-a", action="store_true", help="Unmount all VeraCrypt volumes")
    parser.add_argument("--gui", action="store_true", help="GUI mode (suppress interactive prompts)")
    parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", help="Absolute path to config.json (propagated from caller)"
    )

    args = parser.parse_args()

    system = platform.system().lower()
    unmount_all = args.all
    gui_mode = args.gui
    target = args.target
    config_path = args.config.resolve() if args.config else None

    # If no target specified, try to get from config
    if not target and not unmount_all:
        cfg = load_config(config_path)
        if "windows" in system:
            target = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.MOUNT_LETTER, "")
        else:
            target = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.MOUNT_POINT, "")

        if not target:
            error_msg = "No mount target specified. Configure mount_letter/mount_point in config.json"
            if gui_mode:
                raise RuntimeError(error_msg)
            print("Usage:")
            print("  python unmount.py <drive_letter>  # Windows: unmount specific drive")
            print("  python unmount.py <mount_point>   # Linux/macOS: unmount specific path")
            print("  python unmount.py --all           # Unmount all VeraCrypt volumes")
            print("")
            print("Or configure mount_letter/mount_point in config.json")
            sys.exit(1)

    # Perform unmount
    if "windows" in system:
        vc_exe = find_veracrypt_windows()
        if not vc_exe:
            error_msg = "VeraCrypt.exe not found. Please install VeraCrypt."
            if gui_mode:
                raise RuntimeError(error_msg)
            error(error_msg)
            sys.exit(1)

        success = unmount_windows(vc_exe, target, unmount_all)
    else:
        if not have("veracrypt"):
            error_msg = "veracrypt not found in PATH. Please install VeraCrypt."
            if gui_mode:
                raise RuntimeError(error_msg)
            error(error_msg)
            sys.exit(1)

        success = unmount_unix(target, unmount_all)

    if gui_mode and not success:
        raise RuntimeError("Unmount operation failed")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
