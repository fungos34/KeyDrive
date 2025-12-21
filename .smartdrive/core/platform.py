# core/platform.py - SINGLE SOURCE OF TRUTH for platform detection
"""
Platform-specific detection and capability checks.

This module provides:
- is_admin(): Check if current process has admin/root privileges
- get_platform(): Get normalized platform name
- veracrypt_flag_prefix(): Get CLI flag prefix (/ or --)
- clipboard_copy_cmd(): Get platform-specific clipboard copy command

No heuristics. No "try and see" with privileged commands.
Direct OS API checks only.
"""

import os
import platform as _platform
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def is_admin() -> bool:
    """
    Check if the current process has administrator/root privileges.

    Windows: Uses ctypes to check for admin token
    Unix: Checks effective user ID (euid == 0)

    Returns:
        True if running with elevated privileges, False otherwise.

    Note:
        This does NOT attempt privileged operations to detect admin status.
        It uses direct OS API checks only.
    """
    system = _platform.system().lower()

    if system == "windows":
        try:
            import ctypes

            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except (AttributeError, OSError):
            # Fallback: assume not admin if check fails
            return False
    else:
        # Unix-like (Linux, macOS, BSD, etc.)
        try:
            return os.geteuid() == 0
        except AttributeError:
            # geteuid not available (shouldn't happen on Unix)
            return False


def get_platform() -> str:
    """
    Get normalized platform name.

    Returns:
        One of: "windows", "darwin", "linux", or the raw system name lowercase.
    """
    return _platform.system().lower()


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_platform() == "windows"


def is_macos() -> bool:
    """Check if running on macOS."""
    return get_platform() == "darwin"


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_platform() == "linux"


def is_unix() -> bool:
    """Check if running on Unix-like system (Linux or macOS)."""
    return get_platform() in ("linux", "darwin")


# ===========================================================================
# Drive Context Detection (Per FEATURE_FLOWS.md CHG-20251221-040)
# ===========================================================================


def get_os_drive() -> str:
    """
    Get the drive letter or mount point running the operating system.

    This is a SAFETY-CRITICAL function. The OS drive must NEVER be offered
    for repartitioning in setup.py.

    Windows: Returns the system drive (e.g., "C:" or "D:")
    Linux/macOS: Returns the root mount point device (e.g., "/dev/sda1")

    Returns:
        Drive letter with colon (Windows) or device path (Unix).
        Returns empty string if detection fails.
    """
    system = get_platform()

    if system == "windows":
        try:
            import ctypes
            from ctypes import wintypes

            # GetSystemWindowsDirectory returns "C:\Windows" or similar
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buf, 260)
            win_path = buf.value
            if win_path and len(win_path) >= 2 and win_path[1] == ":":
                return win_path[:2].upper()  # "C:"
        except (AttributeError, OSError):
            pass

        # Fallback: environment variable
        systemroot = os.environ.get("SystemRoot", "")
        if systemroot and len(systemroot) >= 2 and systemroot[1] == ":":
            return systemroot[:2].upper()

        return ""

    else:
        # Unix-like: parse /proc/mounts or use df /
        try:
            result = subprocess.run(
                ["df", "-P", "/"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    # First column of second line is the device
                    parts = lines[1].split()
                    if parts:
                        return parts[0]  # e.g., "/dev/sda1"
        except (subprocess.TimeoutExpired, OSError):
            pass

        return ""


def get_instantiation_drive() -> str:
    """
    Get the drive from which the current .smartdrive instance was launched.

    This is a SAFETY-CRITICAL function. The instantiation drive must NEVER
    be offered for repartitioning in setup.py.

    The detection uses the actual script path (__file__), walking up to find
    the .smartdrive folder, then returning its containing drive.

    Windows: Returns drive letter (e.g., "H:")
    Linux/macOS: Returns the device mounted at the script's location

    Returns:
        Drive letter with colon (Windows) or device path (Unix).
        Returns empty string if detection fails.
    """
    try:
        # Walk up from this file to find the drive root
        current_file = Path(__file__).resolve()

        if is_windows():
            # On Windows, Path.drive returns "H:" for "H:\\.smartdrive\\core\\platform.py"
            drive = current_file.drive
            if drive and len(drive) >= 2 and drive[1] == ":":
                return drive.upper()
            return ""

        else:
            # Unix: find the mount point of the script's location
            script_path = str(current_file)
            try:
                result = subprocess.run(
                    ["df", "-P", script_path],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if parts:
                            return parts[0]  # e.g., "/dev/sdb1"
            except (subprocess.TimeoutExpired, OSError):
                pass

            return ""

    except Exception:
        return ""


def get_instantiation_drive_letter_or_mount() -> str:
    """
    Get user-friendly instantiation drive identifier.

    Windows: Returns just the drive letter with colon (e.g., "H:")
    Unix: Returns the mount point path (e.g., "/media/user/KEYDRIVE")

    Returns:
        User-readable drive identifier or empty string if detection fails.
    """
    try:
        current_file = Path(__file__).resolve()

        if is_windows():
            return get_instantiation_drive()  # Already returns "H:"

        else:
            # Unix: get mount point, not device
            script_path = str(current_file)
            try:
                result = subprocess.run(
                    ["df", "-P", script_path],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if len(parts) >= 6:
                            # Last column is mount point
                            return parts[-1]  # e.g., "/media/user/KEYDRIVE"
            except (subprocess.TimeoutExpired, OSError):
                pass

            return ""

    except Exception:
        return ""


def is_drive_protected(drive: str) -> tuple[bool, str]:
    """
    Check if a drive is protected from repartitioning.

    A drive is protected if it is:
    1. The OS drive (running the operating system)
    2. The instantiation drive (running the current .smartdrive instance)

    Args:
        drive: Drive letter (Windows, e.g., "H:") or device path (Unix, e.g., "/dev/sdb1")

    Returns:
        Tuple of (is_protected, reason).
        If protected, reason explains why (e.g., "OS drive", "Instantiation drive").
        If not protected, reason is empty string.
    """
    drive_upper = drive.upper() if is_windows() else drive

    os_drive = get_os_drive()
    if os_drive and drive_upper == os_drive.upper() if is_windows() else drive == os_drive:
        return True, "os_drive"

    inst_drive = get_instantiation_drive()
    if inst_drive:
        if is_windows():
            if drive_upper == inst_drive.upper():
                return True, "instantiation_drive"
        else:
            if drive == inst_drive:
                return True, "instantiation_drive"

    return False, ""


# ===========================================================================
# Cross-Platform CLI Support (Per AGENT_ARCHITECTURE.md Section 2.5)
# ===========================================================================


def veracrypt_flag_prefix() -> str:
    """
    Get the VeraCrypt CLI flag prefix for current platform.

    Windows: Uses forward-slash syntax (/volume, /password, /dismount)
    Unix: Uses double-dash syntax (--volume, --password, --dismount)

    Returns:
        "/" for Windows, "--" for Unix-like systems.
    """
    return "/" if is_windows() else "--"


def clipboard_copy_cmd() -> Optional[List[str]]:
    """
    Get the platform-specific clipboard copy command.

    Returns:
        List of command args that accept stdin for clipboard, or None if unavailable.

    Platform commands:
        Windows: ['clip']
        macOS: ['pbcopy']
        Linux: ['xclip', '-selection', 'clipboard'] or ['xsel', '--clipboard', '--input']
    """
    plat = get_platform()

    if plat == "windows":
        return ["clip"]
    elif plat == "darwin":
        return ["pbcopy"]
    elif plat == "linux":
        # Check for xclip first, then xsel
        import shutil

        if shutil.which("xclip"):
            return ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            return ["xsel", "--clipboard", "--input"]

    return None


def veracrypt_cli_dialect() -> str:
    """
    Get the VeraCrypt CLI dialect identifier.

    Used for documentation and capability checks.

    Returns:
        "windows" or "unix"
    """
    return "windows" if is_windows() else "unix"


# For testing: allow monkeypatching
_admin_override = None


def _set_admin_override(value: bool | None) -> None:
    """
    Override admin status for testing.

    Args:
        value: True/False to override, None to use real detection.
    """
    global _admin_override
    _admin_override = value


def _get_admin_status() -> bool:
    """
    Get admin status, respecting any test override.

    For internal use by is_admin() when testing.
    """
    if _admin_override is not None:
        return _admin_override
    return is_admin()


# ===========================================================================
# Windows Shell Helpers (OS-specific commands live here)
# ===========================================================================


def windows_set_attributes(
    target: Path,
    *,
    hidden: bool | None = None,
    system: bool | None = None,
    timeout_s: float = 5.0,
) -> None:
    """Set Windows file attributes via attrib.exe.

    Args:
        target: File or directory path
        hidden: True to add +h, False to add -h, None to leave unchanged
        system: True to add +s, False to add -s, None to leave unchanged
        timeout_s: Subprocess timeout
    """
    if not is_windows():
        return

    args: list[str] = ["attrib"]
    if hidden is True:
        args.append("+h")
    elif hidden is False:
        args.append("-h")
    if system is True:
        args.append("+s")
    elif system is False:
        args.append("-s")
    args.append(str(target))

    # attrib returns non-zero for some edge cases; treat as best-effort.
    subprocess.run(args, capture_output=True, timeout=timeout_s, check=False)


def windows_refresh_explorer(*, timeout_s: float = 10.0) -> None:
    """Best-effort Explorer refresh for icon/cache updates."""
    if not is_windows():
        return

    # ie4uinit.exe exists on modern Windows; ignore failure.
    subprocess.run(
        ["ie4uinit.exe", "-show"],
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def windows_create_shortcut(
    *,
    shortcut_path: Path,
    target_path: Path,
    arguments: Optional[str] = None,
    working_dir: Optional[Path] = None,
    icon_path: Optional[Path] = None,
    description: Optional[str] = None,
    timeout_s: float = 20.0,
) -> None:
    """Create a .lnk shortcut using PowerShell COM automation.

    Notes:
    - This is Windows-only.
    - Uses single-quoted PowerShell strings with escaping.
    """
    if not is_windows():
        return

    def _ps_sq(value: str) -> str:
        # PowerShell single-quote escaping is doubling the quote.
        return value.replace("'", "''")

    sp = _ps_sq(str(shortcut_path))
    tp = _ps_sq(str(target_path))

    parts: list[str] = [
        "$WshShell = New-Object -ComObject WScript.Shell;",
        f"$Shortcut = $WshShell.CreateShortcut('{sp}');",
        f"$Shortcut.TargetPath = '{tp}';",
    ]

    if arguments:
        parts.append(f"$Shortcut.Arguments = '{_ps_sq(arguments)}';")
    if working_dir:
        parts.append(f"$Shortcut.WorkingDirectory = '{_ps_sq(str(working_dir))}';")
    if icon_path:
        # IconLocation format: <path>,<index>
        parts.append(f"$Shortcut.IconLocation = '{_ps_sq(str(icon_path))},0';")
    if description:
        parts.append(f"$Shortcut.Description = '{_ps_sq(description)}';")

    parts.append("$Shortcut.Save();")

    ps_script = "\n".join(parts)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
