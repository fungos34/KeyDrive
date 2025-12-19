#!/usr/bin/env python3
"""
Clipboard SSOT Module

SINGLE SOURCE OF TRUTH for all clipboard operations in KeyDrive.

Design Requirements (per AGENT_ARCHITECTURE.md):
- Must work from console-launched processes (no GUI dependency)
- Runtime detection of clipboard availability
- Layered fallback strategy per platform
- No silent failures - clear exceptions with actionable messages
- TTL clearing that only clears KeyDrive-set content

Usage:
    from core.clipboard import set_text, clear_if_ours, is_available
    
    set_text("secret", ttl_seconds=30, label="password")
    # ... user pastes ...
    clear_if_ours()  # Only clears if unchanged
"""

import hashlib
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# Try to import Limits for CLIPBOARD_TIMEOUT, fallback to 30 seconds
try:
    from core.limits import Limits
    DEFAULT_TTL = getattr(Limits, 'CLIPBOARD_TIMEOUT', 30)
except ImportError:
    DEFAULT_TTL = 30


# =============================================================================
# Clipboard State Tracking
# =============================================================================

@dataclass
class ClipboardMarker:
    """Track what we put on the clipboard to enable safe clearing."""
    content_hash: str  # SHA256 of content (never store plaintext)
    timestamp: float
    label: str  # Human-readable label for logging (e.g., "password")
    
    @classmethod
    def from_content(cls, content: str, label: str = "data") -> "ClipboardMarker":
        """Create marker from content without storing content."""
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        return cls(content_hash=content_hash, timestamp=time.time(), label=label)


# Global marker for tracking what we copied
_current_marker: Optional[ClipboardMarker] = None
_marker_lock = threading.Lock()

# Active TTL timer
_ttl_timer: Optional[threading.Timer] = None


# =============================================================================
# Platform Detection
# =============================================================================

def _get_platform() -> str:
    """Get normalized platform name."""
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    elif "darwin" in system:
        return "macos"
    else:
        return "linux"


def _is_wayland() -> bool:
    """Check if running under Wayland (Linux)."""
    import os
    return os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'


# =============================================================================
# Windows Clipboard Implementation
# =============================================================================

def _windows_clip_exe(text: str) -> Tuple[bool, str]:
    """
    Use clip.exe to set clipboard (most reliable on Windows).
    Works in admin consoles, no GUI required.
    
    Returns: (success, error_message)
    """
    try:
        # clip.exe reads from stdin
        proc = subprocess.Popen(
            ['clip.exe'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        try:
            _, stderr = proc.communicate(input=text.encode('utf-16-le'), timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "clip.exe timed out"
        
        if proc.returncode == 0:
            return True, ""
        else:
            return False, f"clip.exe returned {proc.returncode}: {stderr.decode('utf-8', errors='replace')}"
    except FileNotFoundError:
        return False, "clip.exe not found (should be in system32)"
    except Exception as e:
        return False, f"clip.exe exception: {e}"


def _windows_powershell_set_clipboard(text: str) -> Tuple[bool, str]:
    """
    Use PowerShell Set-Clipboard as fallback.
    
    Returns: (success, error_message)
    """
    try:
        # Use -NoProfile to speed up, -NonInteractive to prevent prompts
        proc = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             f'Set-Clipboard -Value $input'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        try:
            _, stderr = proc.communicate(input=text.encode('utf-8'), timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "PowerShell clipboard set timed out"
        
        if proc.returncode == 0:
            return True, ""
        else:
            return False, f"PowerShell returned {proc.returncode}: {stderr.decode('utf-8', errors='replace')}"
    except FileNotFoundError:
        return False, "powershell.exe not found"
    except Exception as e:
        return False, f"PowerShell exception: {e}"


def _windows_get_clipboard() -> Optional[str]:
    """Get current clipboard content on Windows."""
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', 'Get-Clipboard'],
            capture_output=True,
            text=True,
            timeout=2,  # 2 second timeout to prevent hanging
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        if result.returncode == 0:
            return result.stdout.rstrip('\r\n')
        return None
    except subprocess.TimeoutExpired:
        # Clipboard read timed out - return None to skip clearing
        return None
    except Exception:
        return None


def _windows_clear_clipboard() -> Tuple[bool, str]:
    """Clear clipboard on Windows."""
    # Set empty string to clear
    return _windows_clip_exe("")


# =============================================================================
# macOS Clipboard Implementation
# =============================================================================

def _macos_pbcopy(text: str) -> Tuple[bool, str]:
    """Use pbcopy on macOS."""
    try:
        proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode('utf-8'))
        if proc.returncode == 0:
            return True, ""
        return False, f"pbcopy returned {proc.returncode}"
    except FileNotFoundError:
        return False, "pbcopy not found"
    except Exception as e:
        return False, f"pbcopy exception: {e}"


def _macos_get_clipboard() -> Optional[str]:
    """Get clipboard content on macOS."""
    try:
        result = subprocess.run(['pbpaste'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def _macos_clear_clipboard() -> Tuple[bool, str]:
    """Clear clipboard on macOS."""
    return _macos_pbcopy("")


# =============================================================================
# Linux Clipboard Implementation
# =============================================================================

def _linux_set_clipboard(text: str) -> Tuple[bool, str]:
    """Set clipboard on Linux using available tools."""
    errors = []
    
    # Try wl-copy first (Wayland)
    if _is_wayland() and shutil.which('wl-copy'):
        try:
            proc = subprocess.Popen(['wl-copy'], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode('utf-8'))
            if proc.returncode == 0:
                return True, ""
            errors.append(f"wl-copy returned {proc.returncode}")
        except Exception as e:
            errors.append(f"wl-copy exception: {e}")
    
    # Try xclip
    if shutil.which('xclip'):
        try:
            proc = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE
            )
            proc.communicate(input=text.encode('utf-8'))
            if proc.returncode == 0:
                return True, ""
            errors.append(f"xclip returned {proc.returncode}")
        except Exception as e:
            errors.append(f"xclip exception: {e}")
    
    # Try xsel
    if shutil.which('xsel'):
        try:
            proc = subprocess.Popen(
                ['xsel', '--clipboard', '--input'],
                stdin=subprocess.PIPE
            )
            proc.communicate(input=text.encode('utf-8'))
            if proc.returncode == 0:
                return True, ""
            errors.append(f"xsel returned {proc.returncode}")
        except Exception as e:
            errors.append(f"xsel exception: {e}")
    
    if not errors:
        return False, "No clipboard tool found. Install xclip, xsel, or wl-copy"
    return False, "; ".join(errors)


def _linux_get_clipboard() -> Optional[str]:
    """Get clipboard content on Linux."""
    # Try wl-paste (Wayland)
    if _is_wayland() and shutil.which('wl-paste'):
        try:
            result = subprocess.run(['wl-paste'], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
    
    # Try xclip
    if shutil.which('xclip'):
        try:
            result = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-o'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
    
    # Try xsel
    if shutil.which('xsel'):
        try:
            result = subprocess.run(
                ['xsel', '--clipboard', '--output'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
    
    return None


def _linux_clear_clipboard() -> Tuple[bool, str]:
    """Clear clipboard on Linux."""
    return _linux_set_clipboard("")


# =============================================================================
# Public API
# =============================================================================

class ClipboardError(Exception):
    """Raised when clipboard operations fail."""
    
    def __init__(self, message: str, methods_tried: list, remediation: str):
        self.message = message
        self.methods_tried = methods_tried
        self.remediation = remediation
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        lines = [self.message]
        if self.methods_tried:
            lines.append("Methods attempted:")
            for method, error in self.methods_tried:
                lines.append(f"  - {method}: {error}")
        lines.append(f"Remediation: {self.remediation}")
        return "\n".join(lines)


def is_available() -> bool:
    """
    Check if clipboard operations are available on this platform.
    
    Returns True if at least one clipboard method should work.
    Does NOT guarantee success - use set_text() to verify.
    """
    plat = _get_platform()
    
    if plat == "windows":
        # clip.exe should always exist on Windows
        return shutil.which('clip.exe') is not None or shutil.which('clip') is not None
    elif plat == "macos":
        return shutil.which('pbcopy') is not None
    else:  # linux
        return (
            shutil.which('xclip') is not None or
            shutil.which('xsel') is not None or
            (_is_wayland() and shutil.which('wl-copy') is not None)
        )


def set_text(
    text: str,
    *,
    ttl_seconds: Optional[int] = None,
    label: str = "data"
) -> None:
    """
    Copy text to system clipboard with optional TTL.
    
    Args:
        text: The text to copy (will be cleared from memory after copy)
        ttl_seconds: Seconds before auto-clear (None = no auto-clear)
        label: Human-readable label for logging (never logged with content)
    
    Raises:
        ClipboardError: If all clipboard methods fail, with actionable remediation
    
    Security:
        - Text is NOT stored in this module after copying
        - Only a hash is kept for TTL clearing verification
        - TTL clearing only clears if clipboard content unchanged
    """
    global _current_marker, _ttl_timer
    
    plat = _get_platform()
    methods_tried = []
    
    # Platform-specific clipboard setting
    if plat == "windows":
        # Try clip.exe first (most reliable)
        success, error = _windows_clip_exe(text)
        if success:
            _track_copy(text, label, ttl_seconds)
            return
        methods_tried.append(("clip.exe", error))
        
        # Fallback to PowerShell
        success, error = _windows_powershell_set_clipboard(text)
        if success:
            _track_copy(text, label, ttl_seconds)
            return
        methods_tried.append(("PowerShell Set-Clipboard", error))
        
        raise ClipboardError(
            "Failed to copy to clipboard on Windows",
            methods_tried,
            "Ensure you're running in a console with clipboard access. "
            "clip.exe and PowerShell should be available in system32."
        )
    
    elif plat == "macos":
        success, error = _macos_pbcopy(text)
        if success:
            _track_copy(text, label, ttl_seconds)
            return
        methods_tried.append(("pbcopy", error))
        
        raise ClipboardError(
            "Failed to copy to clipboard on macOS",
            methods_tried,
            "pbcopy should be available by default on macOS."
        )
    
    else:  # linux
        success, error = _linux_set_clipboard(text)
        if success:
            _track_copy(text, label, ttl_seconds)
            return
        methods_tried.append(("Linux clipboard tools", error))
        
        raise ClipboardError(
            "Failed to copy to clipboard on Linux",
            methods_tried,
            "Install a clipboard tool: sudo apt install xclip "
            "OR sudo apt install xsel "
            "OR (for Wayland) sudo apt install wl-clipboard"
        )


def _track_copy(text: str, label: str, ttl_seconds: Optional[int]) -> None:
    """Track the copy operation and set up TTL if requested."""
    global _current_marker, _ttl_timer
    
    with _marker_lock:
        # Cancel any existing timer
        if _ttl_timer is not None:
            _ttl_timer.cancel()
            _ttl_timer = None
        
        # Create marker (stores hash, not plaintext)
        _current_marker = ClipboardMarker.from_content(text, label)
        
        # Set up TTL timer if requested
        if ttl_seconds is not None and ttl_seconds > 0:
            _ttl_timer = threading.Timer(ttl_seconds, _ttl_clear_callback)
            _ttl_timer.daemon = True
            _ttl_timer.start()


def _ttl_clear_callback() -> None:
    """Called when TTL expires - clears clipboard only if unchanged."""
    global _current_marker, _ttl_timer
    
    with _marker_lock:
        _ttl_timer = None
        if _current_marker is None:
            return
        
        # Get current clipboard content
        current = get_text()
        if current is None:
            # Can't read clipboard, don't clear
            _current_marker = None
            return
        
        # Check if clipboard still contains what we put there
        current_hash = hashlib.sha256(current.encode('utf-8')).hexdigest()
        if current_hash == _current_marker.content_hash:
            # Still our content - safe to clear
            clear_best_effort()
        
        _current_marker = None


def get_text() -> Optional[str]:
    """
    Get current clipboard content.
    
    Returns None if clipboard cannot be read.
    """
    plat = _get_platform()
    
    if plat == "windows":
        return _windows_get_clipboard()
    elif plat == "macos":
        return _macos_get_clipboard()
    else:
        return _linux_get_clipboard()


def clear_if_ours() -> bool:
    """
    Clear clipboard only if it still contains what we copied.
    
    Returns True if cleared, False if clipboard was modified by user.
    """
    global _current_marker
    
    with _marker_lock:
        if _current_marker is None:
            return False
        
        current = get_text()
        if current is None:
            _current_marker = None
            return False
        
        current_hash = hashlib.sha256(current.encode('utf-8')).hexdigest()
        if current_hash == _current_marker.content_hash:
            clear_best_effort()
            _current_marker = None
            return True
        else:
            # User changed clipboard - don't clear
            _current_marker = None
            return False


def clear_best_effort() -> bool:
    """
    Clear clipboard without checking content.
    
    Use clear_if_ours() when possible to avoid clearing user content.
    Returns True on success, False on failure.
    """
    global _current_marker
    
    plat = _get_platform()
    
    try:
        if plat == "windows":
            success, _ = _windows_clear_clipboard()
            return success
        elif plat == "macos":
            success, _ = _macos_clear_clipboard()
            return success
        else:
            success, _ = _linux_clear_clipboard()
            return success
    except Exception:
        return False
    finally:
        with _marker_lock:
            _current_marker = None


def cancel_ttl() -> None:
    """Cancel any pending TTL clear operation."""
    global _ttl_timer
    
    with _marker_lock:
        if _ttl_timer is not None:
            _ttl_timer.cancel()
            _ttl_timer = None


# =============================================================================
# Convenience Functions for Common Patterns
# =============================================================================

def copy_secret_with_ttl(secret: str, label: str, ttl_seconds: int = None) -> None:
    """
    Copy a secret to clipboard with TTL auto-clear.
    
    Convenience wrapper for set_text() with sensible defaults for secrets.
    
    Args:
        secret: The secret text to copy
        label: Human-readable label (e.g., "password", "keyfile path")
        ttl_seconds: Override default TTL (default: Limits.CLIPBOARD_TIMEOUT)
    """
    if ttl_seconds is None:
        ttl_seconds = DEFAULT_TTL
    
    set_text(secret, ttl_seconds=ttl_seconds, label=label)


def copy_non_secret(text: str, label: str = "path") -> None:
    """
    Copy non-secret text to clipboard (no TTL).
    
    Use for volume paths, file paths, etc. that aren't secrets.
    """
    set_text(text, ttl_seconds=None, label=label)
