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
import platform
import shutil
import subprocess
import sys
from pathlib import Path


CONFIG_FILENAME = "config.json"


def log(msg: str) -> None:
    print(f"[SmartDrive] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def load_config() -> dict:
    """Load config.json from current directory."""
    cfg_path = Path(CONFIG_FILENAME)
    if not cfg_path.exists():
        return {}
    
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_veracrypt_windows() -> Path | None:
    """Find VeraCrypt.exe on Windows."""
    if have("VeraCrypt.exe"):
        return Path(shutil.which("VeraCrypt.exe"))
    
    veracrypt_paths = [
        Path(r"C:\Program Files\VeraCrypt\VeraCrypt.exe"),
        Path(r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"),
    ]
    for p in veracrypt_paths:
        if p.exists():
            return p
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
                log("✓ All volumes unmounted successfully")
            else:
                log(f"✓ Drive {target}: unmounted successfully")
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
    
    Args:
        target: Mount point to unmount (e.g., "/mnt/veracrypt")
        unmount_all: If True, unmount all volumes
    
    Returns:
        True if successful, False otherwise.
    """
    if unmount_all:
        args = ["veracrypt", "--text", "--dismount"]
        log("Unmounting all VeraCrypt volumes...")
    elif target:
        # Expand ~ in path
        mount_point = str(Path(target).expanduser())
        args = ["veracrypt", "--text", "--dismount", mount_point]
        log(f"Unmounting {mount_point}...")
    else:
        error("No target specified. Use a mount point or --all")
        return False
    
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            if unmount_all:
                log("✓ All volumes unmounted successfully")
            else:
                log(f"✓ {target} unmounted successfully")
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
    system = platform.system().lower()
    
    # Parse arguments
    unmount_all = "--all" in sys.argv or "-a" in sys.argv
    
    # Get target from args (skip script name and flags)
    target = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            target = arg
            break
    
    # If no target specified, try to get from config
    if not target and not unmount_all:
        cfg = load_config()
        if "windows" in system:
            target = cfg.get("windows", {}).get("mount_letter", "")
        else:
            target = cfg.get("unix", {}).get("mount_point", "")
        
        if not target:
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
            error("VeraCrypt.exe not found. Please install VeraCrypt.")
            sys.exit(1)
        
        success = unmount_windows(vc_exe, target, unmount_all)
    else:
        if not have("veracrypt"):
            error("veracrypt not found in PATH. Please install VeraCrypt.")
            sys.exit(1)
        
        success = unmount_unix(target, unmount_all)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
