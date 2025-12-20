#!/usr/bin/env python3
"""
VeraCrypt CLI Wrapper

Provides robust wrapper around VeraCrypt command-line interface:
- Header export/restore
- Mount/unmount with credential validation
- Error parsing and detection
- Capability detection

Handles platform differences and VeraCrypt version variations.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# ===========================================================================
# Core module imports (single source of truth)
# ===========================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
from core.paths import Paths
if _script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
    # Deployed: .smartdrive/scripts/veracrypt_cli.py
    # DEPLOY_ROOT = .smartdrive/, add to sys.path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/veracrypt_cli.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.constants import UserInputs
    from core.limits import Limits
    from core.paths import Paths
    from core.platform import is_windows, veracrypt_flag_prefix

    TIMEOUT_MOUNT = Limits.VERACRYPT_MOUNT_TIMEOUT
    TIMEOUT_LONG = Limits.TIMEOUT_LONG
except ImportError:
    # Fallback timeouts if core not available
    TIMEOUT_MOUNT = 30
    TIMEOUT_LONG = 60
    UserInputs = None
    # No Paths fallback - if core is missing, VeraCrypt path resolution will fail
    # This is intentional per AGENT_ARCHITECTURE.md - SSOT must be authoritative
    Paths = None

    # Minimal platform fallback
    def is_windows():
        return platform.system().lower() == "windows"

    def veracrypt_flag_prefix():
        return "/" if is_windows() else "--"


class VeraCryptError(Exception):
    """VeraCrypt operation failed."""

    pass


class HeaderCorruptionError(VeraCryptError):
    """VeraCrypt header is corrupted or damaged."""

    pass


class InvalidCredentialsError(VeraCryptError):
    """Mount credentials are invalid."""

    pass


class CLICapabilityError(VeraCryptError):
    """VeraCrypt CLI does not support the requested operation."""

    pass


# ===========================================================================
# Module-level state for GUI launch guard
# ===========================================================================

# P1: Prevent multiple VeraCrypt GUI launches per session
# This flag is set when render_header_export_gui_guide opens the GUI
# and prevents reopening if the function is called again (e.g., on retry)
_veracrypt_gui_opened_this_session = False


def reset_gui_launched_state():
    """Reset the GUI launched flag - for testing only."""
    global _veracrypt_gui_opened_this_session
    _veracrypt_gui_opened_this_session = False


# ===========================================================================
# Clipboard Utilities (SSOT: core/clipboard.py)
# ===========================================================================
# These are compatibility wrappers around the SSOT clipboard module.
# New code should import from core.clipboard directly.

try:
    from core.clipboard import ClipboardError
    from core.clipboard import clear_best_effort as _clipboard_clear
    from core.clipboard import clear_if_ours as _clipboard_clear_if_ours
    from core.clipboard import copy_secret_with_ttl as _clipboard_copy_secret
    from core.clipboard import get_text as _clipboard_get_text
    from core.clipboard import is_available as _clipboard_is_available
    from core.clipboard import set_text as _clipboard_set_text

    _CLIPBOARD_SSOT_AVAILABLE = True
except ImportError:
    _CLIPBOARD_SSOT_AVAILABLE = False
    ClipboardError = Exception  # Fallback


def clipboard_available() -> bool:
    """Check if clipboard operations are available."""
    if _CLIPBOARD_SSOT_AVAILABLE:
        return _clipboard_is_available()
    # Fallback for standalone operation
    system = platform.system().lower()
    if "windows" in system:
        return shutil.which("clip.exe") is not None
    elif "darwin" in system:
        return shutil.which("pbcopy") is not None
    else:
        return shutil.which("xclip") is not None or shutil.which("xsel") is not None


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to system clipboard.
    Returns True on success, False on failure.

    NOTE: Prefer using core.clipboard.set_text() directly for new code.
    This is a compatibility wrapper.
    """
    if _CLIPBOARD_SSOT_AVAILABLE:
        try:
            _clipboard_set_text(text, label="legacy_copy")
            return True
        except ClipboardError:
            return False

    # Fallback: Use subprocess for reliability (ctypes has 64-bit issues)
    system = platform.system().lower()

    try:
        if "windows" in system:
            # Use clip.exe (most reliable on Windows)
            proc = subprocess.Popen(
                ["clip.exe"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.communicate(input=text.encode("utf-16-le"))
            return proc.returncode == 0

        elif "darwin" in system:
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"))
            return proc.returncode == 0

        else:
            if shutil.which("xclip"):
                proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
            elif shutil.which("xsel"):
                proc = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
            return False

    except Exception:
        return False


def clear_clipboard() -> bool:
    """Clear the system clipboard."""
    if _CLIPBOARD_SSOT_AVAILABLE:
        return _clipboard_clear()
    return copy_to_clipboard("")


def password_to_clipboard_with_timeout(password: str, timeout_seconds: int = 60, wait_for_enter: bool = True) -> bool:
    """
    Copy password to clipboard and clear after user presses Enter.

    Args:
        password: The password to copy
        timeout_seconds: Fallback timeout if user doesn't press Enter
        wait_for_enter: If True, prompt user to press Enter to clear clipboard

    Returns True if successfully copied.
    """
    if not clipboard_available():
        return False

    if not copy_to_clipboard(password):
        return False

    print(f"\n  [OK] Password copied to clipboard.")
    print(f"       Paste it into VeraCrypt when prompted.")

    if wait_for_enter:
        print(f"       Press Enter when done to clear clipboard (auto-clears in {timeout_seconds}s).")
        # Use a simple blocking approach - user presses Enter when done
        import threading

        cleared = threading.Event()

        def auto_clear():
            if not cleared.wait(timeout_seconds):
                clear_clipboard()
                # Don't print - user may have moved on

        timer = threading.Thread(target=auto_clear, daemon=True)
        timer.start()

        try:
            input()  # Wait for Enter
            cleared.set()
            clear_clipboard()
            print("       [OK] Clipboard cleared")
            return True
        except (KeyboardInterrupt, EOFError):
            cleared.set()
            clear_clipboard()
            return True
    else:
        return True


# ===========================================================================
# On-Demand Secrets Handler (Per AGENT_ARCHITECTURE.md Section 10.3)
# ===========================================================================


def _check_yubikey_presence_for_cpw() -> tuple:
    """
    Check if a YubiKey with GPG capability is present.
    BUG-20251218-006: HARD GATE - must verify hardware key before any CPW operation.
    BUG-20251218-007 FIX: Add --no-tty to prevent hanging on repeated CPW calls.

    Returns:
        Tuple of (is_present: bool, error_message: str)
    """
    try:
        # Use Limits.GPG_DECRYPT_TIMEOUT from SSOT
        gpg_timeout = Limits.GPG_DECRYPT_TIMEOUT if Limits else 30
        result = subprocess.run(["gpg", "--no-tty", "--card-status"], capture_output=True, timeout=gpg_timeout)
        if result.returncode == 0:
            return True, ""
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")
            if "no card" in stderr.lower() or "card error" in stderr.lower():
                return False, "No YubiKey/smartcard detected"
            return False, f"GPG card status failed: {stderr[:100]}"
    except FileNotFoundError:
        return False, "GPG not installed or not in PATH"
    except subprocess.TimeoutExpired:
        return False, "GPG card status timed out (YubiKey may be unresponsive)"
    except Exception as e:
        return False, f"Error checking YubiKey: {e}"


class OnDemandSecretsHandler:
    """
    Handle on-demand secrets for manual GUI guidance.

    SECURITY: Secrets are NOT decrypted until user explicitly requests them.
    This minimizes plaintext lifetime and prevents clipboard leaks.

    BUG-20251218-006 FIX: For GPG modes (GPG_PW_ONLY, PW_GPG_KEYFILE),
    YubiKey presence is a HARD GATE before any CPW/CKF operation.

    Commands:
        CPW = Copy Password to clipboard (decrypt only now)
        CKF = Copy Keyfile path to clipboard (decrypt keyfile if GPG-encrypted)
        CDP = Copy Device/volume Path to clipboard (non-secret)
    """

    def __init__(
        self,
        volume_path: str,
        password_getter: callable = None,
        keyfile_getter: callable = None,
        clipboard_timeout: int = 120,
        security_mode: str = None,
        require_hardware_key: bool = False,
    ):
        """
        Initialize the handler.

        Args:
            volume_path: Path to VeraCrypt volume (non-secret)
            password_getter: Callable that returns password when invoked
            keyfile_getter: Callable that returns keyfile Path when invoked
            clipboard_timeout: Seconds before clipboard auto-clears
            security_mode: Security mode string (e.g., "GPG_PW_ONLY")
            require_hardware_key: If True, enforce YubiKey presence for CPW/CKF
        """
        self.volume_path = volume_path
        self._password_getter = password_getter
        self._keyfile_getter = keyfile_getter
        self._clipboard_timeout = clipboard_timeout
        self._password_copied = False
        self._keyfile_path = None
        self._security_mode = security_mode
        self._require_hardware_key = require_hardware_key

        # BUG-20251218-006: Auto-detect if hardware key required based on mode
        if security_mode:
            mode_upper = security_mode.upper()
            if "GPG" in mode_upper:
                self._require_hardware_key = True

    def handle_command(self, cmd: str) -> bool:
        """
        Handle a user command.

        Returns True if command was handled, False if not recognized.
        """
        cmd = cmd.strip().upper()

        if cmd == "CPW":
            return self._copy_password()
        elif cmd == "CKF":
            return self._copy_keyfile()
        elif cmd == "CDP":
            return self._copy_device_path()

        return False

    def _copy_password(self) -> bool:
        """
        Copy password to clipboard (decrypt on demand).

        BUG-20251218-006 FIX: For GPG modes, YubiKey presence is a HARD GATE.
        Password CANNOT be copied without validating hardware key first.
        """
        if not self._password_getter:
            print("  [!] No password available for this mode.")
            return True

        if not clipboard_available():
            print("  [!] Clipboard not available on this platform.")
            print("      On Linux: install xclip, xsel, or wl-clipboard")
            return True

        # BUG-20251218-006: HARD GATE - verify hardware key BEFORE any decryption
        if self._require_hardware_key:
            present, error_msg = _check_yubikey_presence_for_cpw()
            if not present:
                print("  [!] YubiKey REQUIRED for CPW in this security mode.")
                print(f"      {error_msg}")
                print("      Insert your YubiKey and try CPW again.")
                return True

        try:
            # SECURITY: Decrypt password ONLY NOW (after hardware key verified)
            password = self._password_getter()
            if not password:
                print("  [!] Password is empty or could not be retrieved.")
                return True

            # Use SSOT clipboard module if available
            if _CLIPBOARD_SSOT_AVAILABLE:
                try:
                    _clipboard_set_text(password, ttl_seconds=self._clipboard_timeout, label="password")
                    self._password_copied = True
                    print(f"  [OK] Password copied to clipboard.")
                    print(f"       Auto-clears in {self._clipboard_timeout} seconds.")
                except ClipboardError as e:
                    print(f"  [!] Clipboard error: {e.message}")
                    for method, error in e.methods_tried:
                        print(f"      - {method}: {error}")
                    print(f"      {e.remediation}")
            else:
                # Fallback to legacy copy
                if copy_to_clipboard(password):
                    self._password_copied = True
                    print(f"  [OK] Password copied to clipboard.")
                    print(f"       Auto-clears in {self._clipboard_timeout} seconds.")

                    # Start auto-clear timer
                    import threading

                    def clear_later():
                        import time

                        time.sleep(self._clipboard_timeout)
                        clear_clipboard()

                    timer = threading.Thread(target=clear_later, daemon=True)
                    timer.start()
                else:
                    print("  [!] Failed to copy password to clipboard.")
                    print("      Windows: Ensure clip.exe is available")
                    print("      macOS: pbcopy should be available by default")
                    print("      Linux: Install xclip or xsel")

            return True
        except Exception as e:
            print(f"  [!] Error retrieving password: {e}")
            return True

    def _copy_keyfile(self) -> bool:
        """Copy keyfile path to clipboard (decrypt on demand if GPG)."""
        if not self._keyfile_getter:
            print("  [!] No keyfile configured for this mode.")
            return True

        if not clipboard_available():
            print("  [!] Clipboard not available on this platform.")
            print("      On Linux: install xclip, xsel, or wl-clipboard")
            return True

        try:
            # SECURITY: Decrypt keyfile ONLY NOW
            keyfile_path = self._keyfile_getter()
            if not keyfile_path:
                print("  [!] Keyfile is empty or could not be retrieved.")
                return True

            self._keyfile_path = keyfile_path
            path_str = str(keyfile_path)

            # Use SSOT clipboard module if available
            if _CLIPBOARD_SSOT_AVAILABLE:
                try:
                    _clipboard_set_text(path_str, ttl_seconds=self._clipboard_timeout, label="keyfile_path")
                    print(f"  [OK] Keyfile path copied: {keyfile_path}")
                    print(f"       Auto-clears in {self._clipboard_timeout} seconds.")
                except ClipboardError as e:
                    print(f"  [!] Clipboard error: {e.message}")
                    for method, error in e.methods_tried:
                        print(f"      - {method}: {error}")
                    print(f"      {e.remediation}")
            else:
                if copy_to_clipboard(path_str):
                    print(f"  [OK] Keyfile path copied: {keyfile_path}")
                    print(f"       Auto-clears in {self._clipboard_timeout} seconds.")

                    import threading

                    def clear_later():
                        import time

                        time.sleep(self._clipboard_timeout)
                        clear_clipboard()

                    timer = threading.Thread(target=clear_later, daemon=True)
                    timer.start()
                else:
                    print("  [!] Failed to copy keyfile path to clipboard.")
                    print("      Windows: Ensure clip.exe is available")
                    print("      macOS: pbcopy should be available by default")
                    print("      Linux: Install xclip or xsel")

            return True
        except Exception as e:
            print(f"  [!] Error retrieving keyfile: {e}")
            return True

    def _copy_device_path(self) -> bool:
        """Copy volume/device path to clipboard (non-secret)."""
        if not clipboard_available():
            print("  [!] Clipboard not available on this platform.")
            print("      On Linux: install xclip, xsel, or wl-clipboard")
            return True

        # Use SSOT clipboard module if available (no TTL for non-secrets)
        if _CLIPBOARD_SSOT_AVAILABLE:
            try:
                _clipboard_set_text(self.volume_path, ttl_seconds=None, label="volume_path")
                print(f"  [OK] Volume path copied: {self.volume_path}")
            except ClipboardError as e:
                print(f"  [!] Clipboard error: {e.message}")
                print(f"      {e.remediation}")
        else:
            if copy_to_clipboard(self.volume_path):
                print(f"  [OK] Volume path copied: {self.volume_path}")
            else:
                print("  [!] Failed to copy volume path to clipboard.")

        return True

    def cleanup(self):
        """Clean up any decrypted secrets."""
        # Clear clipboard if we copied sensitive data (safely, only if unchanged)
        if self._password_copied:
            if _CLIPBOARD_SSOT_AVAILABLE:
                _clipboard_clear_if_ours()
            else:
                clear_clipboard()
            self._password_copied = False

        # Clean up temp keyfile if we created one
        if self._keyfile_path and hasattr(self._keyfile_path, "unlink"):
            try:
                from pathlib import Path

                kf = Path(self._keyfile_path)
                if kf.exists() and "tmp" in str(kf).lower():
                    kf.unlink()
            except:
                pass
        self._keyfile_path = None

    def clear_all(self):
        """Alias for cleanup() - clear all secrets from memory and clipboard."""
        self.cleanup()


# ===========================================================================
# CLI Capability Detection (Per AGENT_ARCHITECTURE.md Section 2.5)
# ===========================================================================

# Cache for CLI capabilities to avoid repeated subprocess calls
_cli_capabilities_cache: Optional[dict] = None

# KNOWN PLATFORM LIMITATIONS:
# Windows VeraCrypt CLI does NOT support backup-headers or restore-headers.
# This is documented fact. We use OS detection as pre-check to avoid even
# attempting CLI probing on platforms where it's known to be unsupported.
_WINDOWS_KNOWN_UNSUPPORTED = {"backup_headers", "restore_headers"}


def check_cli_capabilities(vc_exe: Optional[Path] = None) -> dict:
    """
    Detect VeraCrypt CLI capabilities by parsing help output.

    MANDATORY: Per AGENT_ARCHITECTURE.md Section 2.5, feature availability
    MUST be detected at runtime, not hardcoded.

    OPTIMIZATION: On Windows, header backup/restore is KNOWN to be unsupported
    by the CLI. We skip probing and immediately return False for those caps.

    Args:
        vc_exe: Path to VeraCrypt executable. If None, uses get_veracrypt_exe().

    Returns:
        Dict with capability flags:
        {
            'backup_headers': bool,  # CLI supports header backup
            'restore_headers': bool,  # CLI supports header restore
            'mount': bool,  # CLI supports mount
            'dismount': bool,  # CLI supports dismount/unmount
            'create': bool,  # CLI supports volume creation
            'help_parsed': bool,  # Whether help was successfully parsed
            'raw_help': str,  # Raw help output for debugging
        }

    Note:
        Windows VeraCrypt.exe may not support all CLI operations that
        Linux veracrypt does. This function detects what's actually available.

    OPTIMIZATION: On Windows, header backup/restore is KNOWN to be unsupported
    by the CLI. We skip probing for those specific capabilities and return
    False immediately, avoiding unnecessary subprocess calls.
    """
    global _cli_capabilities_cache

    if _cli_capabilities_cache is not None:
        return _cli_capabilities_cache

    if vc_exe is None:
        vc_exe = get_veracrypt_exe()

    if not vc_exe:
        return {
            "backup_headers": False,
            "restore_headers": False,
            "mount": False,
            "dismount": False,
            "create": False,
            "help_parsed": False,
            "raw_help": "VeraCrypt not found",
        }

    # PLATFORM PRE-CHECK: On Windows, we KNOW certain capabilities are unavailable
    # This avoids CLI probing for features we know don't exist.
    is_windows = os.name == "nt"

    # Initialize with known platform limitations
    capabilities = {
        "backup_headers": False,  # Will be updated from help parsing (non-Windows)
        "restore_headers": False,  # Will be updated from help parsing (non-Windows)
        "mount": False,
        "dismount": False,
        "create": False,
        "help_parsed": False,
        "raw_help": "",
    }

    # On Windows, header backup/restore are KNOWN unsupported - don't even probe
    if is_windows:
        capabilities["backup_headers"] = False
        capabilities["restore_headers"] = False
        # TODO 4: On Windows, assume mount/dismount/create work (all do)
        # Avoid help probing entirely to prevent potential GUI spawns
        capabilities["mount"] = True
        capabilities["dismount"] = True
        capabilities["create"] = True
        capabilities["help_parsed"] = True
        capabilities["raw_help"] = "Windows: Known capabilities (probe skipped to prevent GUI)"
        _cli_capabilities_cache = capabilities
        return capabilities

    # Non-Windows: Try to get help output
    prefix = veracrypt_flag_prefix()
    help_flags = [f"{prefix}help", f"{prefix}h", "-h", "--help", "/?"]

    # Use SSOT timeout for help command
    help_timeout = TIMEOUT_MOUNT  # Reuse mount timeout as reasonable default

    raw_help = ""
    for help_flag in help_flags:
        try:
            # TODO 4: Add CREATE_NO_WINDOW on Windows to prevent GUI popup during capability probing
            kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": help_timeout,
            }
            if is_windows:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run([str(vc_exe), help_flag], **kwargs)
            # VeraCrypt may return non-zero for help but still output usage
            output = result.stdout + result.stderr
            if output and len(output) > 50:  # Reasonable help output length
                raw_help = output.lower()
                break
        except Exception:
            continue

    # Parse capabilities from help output
    # Windows uses /flag, Unix uses --flag
    backup_patterns = ["backup-headers", "/backup", "--backup-headers", "backup headers"]
    restore_patterns = ["restore-headers", "/restore", "--restore-headers", "restore headers"]
    mount_patterns = ["/volume", "--mount", "mount a volume", "/m"]
    dismount_patterns = ["/dismount", "--dismount", "/d", "dismount", "unmount"]
    create_patterns = ["/create", "--create", "create a volume", "volume creation"]

    # Update capabilities from help parsing
    # BUT: On Windows, NEVER trust help output for backup/restore - it's known unsupported
    if not is_windows:
        capabilities["backup_headers"] = any(p in raw_help for p in backup_patterns)
        capabilities["restore_headers"] = any(p in raw_help for p in restore_patterns)
    # else: keep False as set above for Windows

    capabilities["mount"] = any(p in raw_help for p in mount_patterns)
    capabilities["dismount"] = any(p in raw_help for p in dismount_patterns)
    capabilities["create"] = any(p in raw_help for p in create_patterns)
    capabilities["help_parsed"] = len(raw_help) > 50
    capabilities["raw_help"] = raw_help[:500] if raw_help else "No help output"

    _cli_capabilities_cache = capabilities
    return capabilities


def can_export_header_via_cli() -> bool:
    """
    Check if VeraCrypt CLI supports header export.

    Returns:
        True if CLI supports backup-headers, False if GUI guidance required.
    """
    caps = check_cli_capabilities()
    return caps.get("backup_headers", False)


def can_restore_header_via_cli() -> bool:
    """
    Check if VeraCrypt CLI supports header restore.

    Returns:
        True if CLI supports restore-headers, False if GUI guidance required.
    """
    caps = check_cli_capabilities()
    return caps.get("restore_headers", False)


# ===========================================================================
# GUI Guidance Renderer (Per Task 1 requirements) - CANONICAL SSOT
# ===========================================================================


def render_vc_guide(
    title: str, steps: list, copy_values: dict = None, warnings: list = None, notes: list = None
) -> None:
    """
    Render a visually scannable VeraCrypt GUI guide.

    SSOT: This is the CANONICAL render_vc_guide implementation.
    Per AGENT_ARCHITECTURE.md Section 2.4, manual steps must be acknowledged
    with clear, actionable guidance. Uses ASCII-safe output for Windows admin consoles.

    Args:
        title: Guide title (displayed in header)
        steps: List of step dicts with keys:
            - 'text': Main step text (required)
            - 'substeps': List of sub-items (optional)
            - 'copy': Value to highlight for copying (optional)
        copy_values: Dict of {label: value} for copyable values shown upfront
        warnings: List of warning messages to show before steps (high visibility)
        notes: Optional list of additional notes to display at the end

    Example:
        render_vc_guide(
            "CREATE VERACRYPT VOLUME",
            [
                "Click 'Create Volume'",
                {"text": "Select your device:", "substeps": ["Path: E:"], "copy": "E:"},
            ],
            copy_values={"Password": "secret123", "Device": "E:"},
            warnings=["All data will be erased!"],
            notes=["Wait for format to complete."],
        )
    """
    # Use ASCII-safe characters for cross-platform compatibility
    # Windows elevated PowerShell often has broken UTF-8 rendering
    ARROW = "->"  # ASCII-safe arrow

    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

    # Warnings first (high visibility) - BEFORE other content
    if warnings:
        print("\n  [!] WARNINGS:")
        for warn in warnings:
            print(f"      - {warn}")

    # Print copyable values block - easy to scan and copy
    if copy_values:
        print("\n  " + "-" * 50)
        print("  VALUES TO COPY:")
        print("  " + "-" * 50)
        for label, value in copy_values.items():
            print(f"  COPY: {label}")
            print(f"        {value}")
        print("  " + "-" * 50)

    # Numbered steps
    print("\n  STEPS:")
    for i, step in enumerate(steps, 1):
        # Handle both string steps and dict steps
        if isinstance(step, str):
            print(f"\n  {i:2d}. {step}")
        elif isinstance(step, dict):
            text = step.get("text", "")
            print(f"\n  {i:2d}. {text}")

            # Highlight copyable value in step
            if "copy" in step:
                print(f"      COPY: {step['copy']}")

            # Sub-steps
            if "substeps" in step:
                for substep in step["substeps"]:
                    print(f"      {ARROW} {substep}")

    # Notes at the end
    if notes:
        print("\n  " + "-" * 50)
        print("  NOTES:")
        for note in notes:
            print(f"      - {note}")

    print("\n" + "=" * 70)


def render_header_export_gui_guide(
    volume_path: str, output_path: Path, password: str = None, keyfile_path: Path = None, security_mode: str = None
) -> bool:
    """
    Render complete GUI guidance for header export when CLI is unsupported.

    MANDATORY: Per AGENT_ARCHITECTURE.md Section 2.5, if CLI feature
    is unavailable, fall back to documented GUI guidance with complete steps.

    SECURITY: Password and keyfile are NOT displayed or copied until user
    explicitly requests them via CPW/CKF commands (on-demand secrets).

    BUG-20251218-006 FIX: For GPG modes, YubiKey presence is enforced
    BEFORE any CPW operation via the OnDemandSecretsHandler.

    Args:
        volume_path: Path to the VeraCrypt volume
        output_path: Where to save the header backup
        password: Volume password (getter function preferred for on-demand)
        keyfile_path: Path to keyfile if used
        security_mode: Security mode string (e.g., "GPG_PW_ONLY") for hardware key enforcement

    Returns:
        True if user confirms they completed the steps.
    """
    from core.platform import get_platform

    vc_exe = get_veracrypt_exe()
    system = get_platform()

    # Detect clipboard availability
    has_clipboard = clipboard_available()

    # Initialize on-demand secrets handler
    # Password is NOT decrypted until user types CPW
    # BUG-20251218-006: Pass security_mode for hardware key enforcement
    secrets_handler = OnDemandSecretsHandler(
        volume_path=volume_path,
        password_getter=lambda: password,  # Lazy - only called when CPW typed
        keyfile_getter=lambda: keyfile_path if keyfile_path else None,
        clipboard_timeout=120,
        security_mode=security_mode,  # Enforces YubiKey check for GPG modes
    )

    # Show quick-reference commands
    print("\n" + "=" * 70)
    print("  VERACRYPT MANUAL HEADER BACKUP")
    print("=" * 70)
    print("\n  ON-DEMAND COPY COMMANDS (type anytime):")
    print("    CPW  = Copy Password to clipboard")
    print("    CKF  = Copy Keyfile path to clipboard") if keyfile_path else None
    print("    CDP  = Copy Device/volume Path to clipboard")
    print("")
    print("  SECURITY: Secrets are NOT copied until you request them.")
    if security_mode and "GPG" in security_mode.upper():
        print("  NOTE: YubiKey required for CPW in this security mode.")
    print("=" * 70)

    copy_values = {
        "Volume Path": volume_path,
        "Save Backup To": str(output_path),
    }
    if keyfile_path:
        copy_values["Keyfile"] = str(keyfile_path)

    steps = [
        {
            "text": "STEP 1/6 — Open VeraCrypt GUI",
            "substeps": [
                "Launch VeraCrypt (do NOT need to mount volume)",
            ],
        },
        {
            "text": "STEP 2/6 — Access Header Backup",
            "substeps": [
                "Go to menu: Tools -> Backup Volume Header...",
            ],
        },
        {
            "text": "STEP 3/6 — Select Volume",
            "substeps": [
                "Click 'Select Device...' or 'Select File...'",
                f"Navigate to: {volume_path}",
                "Click OK",
                "(Type CDP to copy volume path to clipboard)",
            ],
        },
        {
            "text": "STEP 4/6 — Enter Credentials",
            "substeps": [
                "Enter your password (type CPW to copy to clipboard first)",
                (
                    f"Click 'Keyfiles...' and add keyfile (type CKF to copy path)"
                    if keyfile_path
                    else "No keyfile required"
                ),
            ],
        },
        {
            "text": "STEP 5/6 — Collect Entropy (IMPORTANT)",
            "substeps": [
                "Move your mouse randomly in the window",
                "This generates cryptographic randomness for the backup",
                "Continue until the progress bar fills completely",
            ],
        },
        {
            "text": "STEP 6/6 — Save Backup",
            "substeps": [
                f"Choose save location: {output_path}",
                "Click 'Save' to complete",
            ],
        },
    ]

    notes = [
        "SECURITY: Type CPW/CKF/CDP only when needed; secrets expire after 2 min",
        "Header backups are encrypted—safe to store but keep secure",
        "Mouse movement provides entropy for cryptographic operations",
    ]

    render_vc_guide("MANUAL VERACRYPT HEADER BACKUP", steps, copy_values, notes=notes)

    print("\n  [!] VeraCrypt CLI does not support header backup on this platform.")
    print("      You must complete this step using the VeraCrypt GUI.\n")

    # P1: Open VeraCrypt GUI ONCE per session only
    # Use module-level flag to prevent reopening if function is called again
    global _veracrypt_gui_opened_this_session

    if not _veracrypt_gui_opened_this_session and vc_exe:
        try:
            # On Windows: CREATE_NO_WINDOW prevents unexpected GUI popups from probes
            if "windows" in platform.system().lower():
                subprocess.Popen([str(vc_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([str(vc_exe)])
            print("  [OK] VeraCrypt GUI opened.\n")
            _veracrypt_gui_opened_this_session = True
        except Exception as e:
            print(f"  [!] Could not open VeraCrypt: {e}")
            print(f"      Please open VeraCrypt manually.\n")
    elif _veracrypt_gui_opened_this_session:
        print("  [i] VeraCrypt GUI already opened (single launch per session).\n")

    # Interactive loop with on-demand secret commands
    print("  Commands: CPW (password), CKF (keyfile), CDP (device path), YES (done), NO (abort)")
    while True:
        response = input("  > ").strip().upper()

        # Handle on-demand secret commands
        if response == "CPW":
            secrets_handler.handle_command("CPW")
            continue
        elif response == "CKF":
            secrets_handler.handle_command("CKF")
            continue
        elif response == "CDP":
            secrets_handler.handle_command("CDP")
            continue
        elif response == (UserInputs.YES if UserInputs is not None else "YES"):
            # Verify the backup file exists
            if output_path.exists():
                print(f"\n  [OK] Header backup verified: {output_path}")
                secrets_handler.clear_all()  # Clear any lingering secrets
                return True
            else:
                print(f"\n  [!] Backup file not found at: {output_path}")
                retry = input("      File not found. Try again? [yes/no]: ").strip().lower()
                if retry != "yes":
                    secrets_handler.clear_all()
                    return False
        elif response == "NO":
            secrets_handler.clear_all()
            return False
        else:
            print("  Commands: CPW (password), CKF (keyfile), CDP (device path), YES (done), NO (abort)")


def have_veracrypt() -> bool:
    """Check if VeraCrypt CLI is available."""
    # First check PATH
    if shutil.which("veracrypt"):
        return True

    # Fallback to SSOT standard installation paths
    if Paths is not None:
        try:
            vc_path = Paths.veracrypt_exe()
            if vc_path and vc_path.exists():
                return True
        except:
            pass

    return False


def get_veracrypt_exe() -> Optional[Path]:
    """
    Get path to VeraCrypt executable using SSOT.

    Returns:
        Path to VeraCrypt executable, or None if not found
    """
    # First check PATH
    vc_which = shutil.which("veracrypt")
    if vc_which:
        return Path(vc_which)

    # Fallback to SSOT standard installation paths
    if Paths is not None:
        try:
            vc_path = Paths.veracrypt_exe()
            if vc_path and vc_path.exists():
                return vc_path
        except:
            pass

    return None


def open_veracrypt_gui() -> bool:
    """
    Open VeraCrypt GUI application.

    Returns:
        True if GUI was launched successfully, False otherwise.
    """
    vc_exe = get_veracrypt_exe()
    if not vc_exe:
        return False

    try:
        # On Windows: use CREATE_NO_WINDOW to prevent extra window
        if platform.system().lower() == "windows":
            subprocess.Popen([str(vc_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen([str(vc_exe)])
        return True
    except Exception as e:
        print(f"  [!] Could not open VeraCrypt: {e}")
        return False


def export_header(
    volume_path: str,
    output_path: Path,
    password: str,
    keyfile_path: Optional[Path] = None,
    use_pim: bool = False,
    pim_value: int = 0,
    allow_gui_fallback: bool = True,
    security_mode: str = None,
) -> Tuple[bool, bool]:
    """
    Export VeraCrypt volume header to backup file.

    This creates a backup of the volume header that can be restored
    if the header becomes corrupted.

    BUG-20251218-006: security_mode is passed to GUI fallback for hardware key enforcement.

    CAPABILITY DETECTION (Per AGENT_ARCHITECTURE.md Section 2.5):
    - Checks if CLI supports header backup before attempting
    - Falls back to GUI guidance if CLI unsupported
    - Never silently fails

    SECURITY: On Linux, password is passed via stdin. On Windows,
              command line is used (VeraCrypt limitation).

    Args:
        volume_path: Path to VeraCrypt volume
        output_path: Where to save header backup
        password: Volume password
        keyfile_path: Optional keyfile path
        use_pim: Use PIM (Personal Iterations Multiplier)
        pim_value: PIM value if used
        allow_gui_fallback: If True, show GUI guidance when CLI unsupported

    Returns:
        Tuple of (success: bool, used_gui_guidance: bool)
        - success: True if header was backed up
        - used_gui_guidance: True if GUI guidance was shown instead of CLI

    Raises:
        VeraCryptError: Export failed
        CLICapabilityError: CLI doesn't support this operation and gui_fallback=False
    """
    # Get VeraCrypt executable path using SSOT
    vc_exe = get_veracrypt_exe()
    if not vc_exe:
        raise VeraCryptError("VeraCrypt not found in PATH or standard installation locations")

    # MANDATORY: Check CLI capability before attempting
    if not can_export_header_via_cli():
        if allow_gui_fallback:
            # Fall back to GUI guidance per AGENT_ARCHITECTURE.md Section 2.5
            # MUST pass credentials so user can authenticate in VeraCrypt GUI
            # BUG-20251218-006: Pass security_mode for hardware key enforcement
            success = render_header_export_gui_guide(
                volume_path, output_path, password=password, keyfile_path=keyfile_path, security_mode=security_mode
            )
            return (success, True)  # True = used GUI guidance
        else:
            raise CLICapabilityError(
                "VeraCrypt CLI does not support header backup on this platform. "
                "Use allow_gui_fallback=True or perform manually via VeraCrypt GUI: "
                "Tools -> Backup Volume Header"
            )

    is_win = is_windows()

    # Build platform-specific command
    # Windows uses forward-slash syntax, Unix uses double-dash
    if is_win:
        # Windows: VeraCrypt.exe /volume <path> /password <pw> /backup-headers /quit
        cmd = [str(vc_exe)]
        cmd.extend(["/volume", volume_path])
        cmd.extend(["/password", password])

        if keyfile_path:
            cmd.extend(["/keyfile", str(keyfile_path)])

        if use_pim and pim_value > 0:
            cmd.extend(["/pim", str(pim_value)])

        cmd.append("/backup-headers")
        cmd.append("/quit")  # Required on Windows to prevent GUI prompts

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_MOUNT)
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    else:
        # Unix: veracrypt --text --non-interactive --stdin --backup-headers <path>
        cmd = [str(vc_exe), "--text", "--non-interactive", "--stdin"]

        if keyfile_path:
            cmd.extend(["--keyfiles", str(keyfile_path)])

        if use_pim and pim_value > 0:
            cmd.extend(["--pim", str(pim_value)])

        cmd.extend(["--backup-headers", volume_path])

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input=password + "\n", timeout=TIMEOUT_MOUNT)
        returncode = proc.returncode

    if returncode != 0:
        # Parse error
        error_msg = stderr or stdout

        if "incorrect password" in error_msg.lower():
            raise InvalidCredentialsError("Invalid password or keyfile")
        elif "not found" in error_msg.lower():
            raise VeraCryptError(f"Volume not found: {volume_path}")
        else:
            # If CLI failed unexpectedly, offer GUI fallback
            if allow_gui_fallback:
                print(f"\n  [!] CLI header backup failed: {error_msg}")
                print("  Falling back to GUI guidance...\n")
                # MUST pass credentials so user can authenticate in VeraCrypt GUI
                # BUG-20251218-006: Pass security_mode for hardware key enforcement
                success = render_header_export_gui_guide(
                    volume_path, output_path, password=password, keyfile_path=keyfile_path, security_mode=security_mode
                )
                return (success, True)
            raise VeraCryptError(f"Header export failed: {error_msg}")

    # VeraCrypt writes backup to volume_path.header (or volume_path + "_backup" on some versions)
    # Check for both patterns
    backup_file = Path(volume_path + ".header")
    backup_file_alt = Path(volume_path + "_backup")

    if backup_file.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup_file), str(output_path))
        return (True, False)  # Success via CLI
    elif backup_file_alt.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup_file_alt), str(output_path))
        return (True, False)  # Success via CLI
    else:
        # On Windows, the backup may be saved to a different location
        # Fall back to GUI guidance
        if allow_gui_fallback:
            print(f"\n  [!] Header backup file not created at expected location.")
            print("  Falling back to GUI guidance...\n")
            # BUG-20251218-006: Pass security_mode for hardware key enforcement
            success = render_header_export_gui_guide(volume_path, output_path, security_mode=security_mode)
            return (success, True)
        raise VeraCryptError(f"Header backup file not created. Expected at: {backup_file}")


def restore_header(
    volume_path: str,
    header_backup_path: Path,
    password: str,
    keyfile_path: Optional[Path] = None,
    use_pim: bool = False,
    pim_value: int = 0,
) -> bool:
    """
    Restore VeraCrypt volume header from backup.

    Use this when volume header is corrupted but data is intact.

    SECURITY: On Linux, password is passed via stdin. On Windows,
              command line is used (VeraCrypt limitation).

    Args:
        volume_path: Path to VeraCrypt volume
        header_backup_path: Path to header backup file
        password: Volume password (must match backup)
        keyfile_path: Optional keyfile path
        use_pim: Use PIM
        pim_value: PIM value if used

    Returns:
        True on success

    Raises:
        VeraCryptError: Restore failed
    """
    # Get VeraCrypt executable path using SSOT
    vc_exe = get_veracrypt_exe()
    if not vc_exe:
        raise VeraCryptError("VeraCrypt not found in PATH or standard installation locations")

    if not header_backup_path.exists():
        raise VeraCryptError(f"Header backup not found: {header_backup_path}")

    is_windows = platform.system().lower() == "windows"

    # Build command
    cmd = [str(vc_exe), "--text"]

    if is_windows:
        cmd.extend(["--password", password])
    else:
        cmd.append("--stdin")
        cmd.append("--non-interactive")

    if keyfile_path:
        cmd.extend(["--keyfiles", str(keyfile_path)])

    if use_pim and pim_value > 0:
        cmd.extend(["--pim", str(pim_value)])

    # Restore command
    cmd.extend(["--restore-headers", str(header_backup_path), volume_path])

    # Run command
    if is_windows:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_MOUNT)
        returncode = result.returncode
        stderr = result.stderr
        stdout = result.stdout
    else:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input=password + "\n", timeout=TIMEOUT_MOUNT)
        returncode = proc.returncode

    if returncode != 0:
        error_msg = stderr or stdout

        if "incorrect password" in error_msg.lower():
            raise InvalidCredentialsError("Invalid password or keyfile")
        else:
            raise VeraCryptError(f"Header restore failed: {error_msg}")

    return True

    return True


def try_mount(
    volume_path: str,
    mount_point: str,
    password: str,
    keyfile_path: Optional[Path] = None,
    use_pim: bool = False,
    pim_value: int = 0,
    read_only: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Attempt to mount VeraCrypt volume.

    SECURITY: On Linux, password is passed via stdin to avoid process list exposure.
              On Windows, VeraCrypt does not support stdin - password is passed via
              command line argument which is a known limitation.

    Args:
        volume_path: Path to VeraCrypt volume
        mount_point: Where to mount (drive letter on Windows, path on Linux)
        password: Volume password
        keyfile_path: Optional keyfile path
        use_pim: Use PIM
        pim_value: PIM value if used
        read_only: Mount read-only

    Returns:
        (success: bool, error_message: Optional[str])

    Raises:
        VeraCryptError: Critical error (not credential issues)
        HeaderCorruptionError: Header is corrupted
        InvalidCredentialsError: Credentials are wrong
    """
    # Get VeraCrypt executable path using SSOT
    vc_exe = get_veracrypt_exe()
    if not vc_exe:
        raise VeraCryptError("VeraCrypt not found in PATH or standard installation locations")

    is_windows = platform.system().lower() == "windows"

    # Build command
    cmd = [str(vc_exe), "--text"]

    if is_windows:
        # Windows: Must use command line arg (no stdin support)
        # This is a known VeraCrypt limitation on Windows
        cmd.extend(["--password", password])
    else:
        # Linux/macOS: Use stdin for password (more secure)
        cmd.append("--stdin")
        cmd.append("--non-interactive")

    if keyfile_path:
        cmd.extend(["--keyfiles", str(keyfile_path)])

    if use_pim and pim_value > 0:
        cmd.extend(["--pim", str(pim_value)])

    if read_only:
        cmd.append("--mount-options=readonly")

    # Mount command
    cmd.extend([volume_path, mount_point])

    # Run command
    if is_windows:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_LONG)
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    else:
        # Linux: Feed password via stdin
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input=password + "\n", timeout=TIMEOUT_LONG)
        returncode = proc.returncode

    if returncode == 0:
        return True, None

    # Parse error
    error_msg = (stderr or stdout).lower()

    # Detect error type
    if any(
        x in error_msg for x in ["incorrect password", "wrong password", "invalid keyfile", "authentication failed"]
    ):
        raise InvalidCredentialsError("Invalid password or keyfile")

    elif any(
        x in error_msg
        for x in ["header damaged", "header corrupted", "invalid header", "header is corrupt", "crc check failed"]
    ):
        raise HeaderCorruptionError("Volume header is corrupted")

    elif "not found" in error_msg:
        raise VeraCryptError(f"Volume not found: {volume_path}")

    elif "already mounted" in error_msg:
        return True, "Already mounted"

    elif "mount point" in error_msg and "in use" in error_msg:
        raise VeraCryptError(f"Mount point already in use: {mount_point}")

    else:
        # Unknown error
        return False, result.stderr or result.stdout


def unmount(mount_point: str, force: bool = False) -> bool:
    """
    Unmount VeraCrypt volume.

    Args:
        mount_point: Mount point or volume path
        force: Force unmount even if in use

    Returns:
        True on success

    Raises:
        VeraCryptError: Unmount failed
    """
    # Get VeraCrypt executable path using SSOT
    vc_exe = get_veracrypt_exe()
    if not vc_exe:
        raise VeraCryptError("VeraCrypt not found in PATH or standard installation locations")

    cmd = [str(vc_exe), "--text", "--dismount", mount_point]

    if force:
        cmd.append("--force")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_MOUNT)

    if result.returncode != 0:
        error_msg = result.stderr or result.stdout

        if "not mounted" in error_msg.lower():
            return True  # Already unmounted

        raise VeraCryptError(f"Unmount failed: {error_msg}")

    return True


def get_mount_status(mount_point: str) -> bool:
    """
    Check if volume is mounted at given mount point.

    Returns:
        True if mounted, False otherwise
    """
    if not have_veracrypt():
        return False

    try:
        result = subprocess.run(
            ["veracrypt", "--text", "--list"],
            capture_output=True,
            text=True,
            timeout=Limits.GPG_CARD_STATUS_TIMEOUT,  # 10 second timeout
        )

        if result.returncode == 0:
            # Check if mount_point appears in output
            return mount_point in result.stdout

    except Exception:
        pass

    return False
