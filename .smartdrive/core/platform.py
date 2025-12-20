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
