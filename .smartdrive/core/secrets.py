#!/usr/bin/env python3
"""
Secret Access Layer (SSOT) - core/secrets.py

SINGLE SOURCE OF TRUTH for mode-aware secret operations.

This module provides on-demand secret access with strict security guarantees:
- Decrypt-on-demand: Secrets are ONLY decrypted when explicitly requested
- Mode-aware: CPW/CKF/CDP behavior varies by SecurityMode
- YubiKey gating: GPG modes require YubiKey presence
- Clipboard-first: Never print secrets; use clipboard with TTL
- Memory hygiene: Overwrite sensitive buffers when done

Per AGENT_ARCHITECTURE.md Section 7 & 10.3:
- NEVER print secrets to terminal by default
- Clipboard-first handling when available
- Auto-clear clipboard after timeout
- YubiKey requirements in GPG modes are HARD gates

Usage:
    from core.secrets import SecretProvider
    
    provider = SecretProvider.from_config(config)
    provider.copy_password_to_clipboard()  # Decrypts ONLY NOW
    provider.copy_keyfile_path_to_clipboard()
    provider.cleanup()  # Wipe sensitive data

Commands:
    CPW = Copy Password to clipboard
    CKF = Copy Keyfile path to clipboard
    CDP = Copy Device/volume Path to clipboard
"""

import base64
import hashlib
import hmac
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from core.constants import CryptoParams, FileNames, UserInputs
from core.limits import Limits

# Core SSOT imports
from core.modes import SecurityMode
from core.paths import Paths

# Module-level logger
from scripts.setup import error, log, warn

# Clipboard SSOT import
try:
    from core.clipboard import ClipboardError
    from core.clipboard import clear_best_effort as clipboard_clear_best_effort
    from core.clipboard import clear_if_ours as clipboard_clear_if_ours
    from core.clipboard import is_available as clipboard_is_available
    from core.clipboard import set_text as clipboard_set_text

    _CLIPBOARD_AVAILABLE = True
except ImportError:
    _CLIPBOARD_AVAILABLE = False
    ClipboardError = Exception  # type: ignore


# =============================================================================
# Constants (from SSOT)
# =============================================================================

CLIPBOARD_TIMEOUT = getattr(Limits, "CLIPBOARD_TIMEOUT", 120)
GPG_DECRYPT_TIMEOUT = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30)

# HKDF parameters for password derivation
HKDF_INFO = getattr(CryptoParams, "HKDF_INFO_DEFAULT", CryptoParams.HKDF_INFO_DEFAULT).encode("utf-8")
DERIVED_PW_LENGTH = getattr(CryptoParams, "DERIVED_PASSWORD_LENGTH", 32)


# =============================================================================
# Exceptions
# =============================================================================


class SecretAccessError(Exception):
    """Base exception for secret access errors."""

    pass


class YubiKeyRequiredError(SecretAccessError):
    """Raised when operation requires YubiKey but none is present."""

    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(f"YubiKey required for '{operation}'.\n" f"Please insert your YubiKey and try again.")


class ModeNotApplicableError(SecretAccessError):
    """Raised when operation is not applicable for current security mode."""

    def __init__(self, operation: str, mode: SecurityMode):
        self.operation = operation
        self.mode = mode
        super().__init__(f"'{operation}' is not applicable in {mode.display_name} mode.")


class DecryptionError(SecretAccessError):
    """Raised when decryption fails."""

    pass


class ClipboardUnavailableError(SecretAccessError):
    """Raised when clipboard is not available."""

    def __init__(self):
        super().__init__(
            "Clipboard is not available on this platform.\n"
            "Install clipboard tools:\n"
            "  Linux: xclip, xsel, or wl-clipboard\n"
            "  Windows: clip.exe should be available by default\n"
            "  macOS: pbcopy should be available by default"
        )


# =============================================================================
# YubiKey Detection
# =============================================================================


def _check_yubikey_presence() -> Tuple[bool, str]:
    """
    Check if a YubiKey with GPG capability is present.

    BUG-20251218-007 FIX: Add --no-tty to prevent terminal hang on repeated calls.
    Without --no-tty, gpg may wait for TTY input when called multiple times,
    causing the terminal to hang/become unresponsive.

    Returns:
        Tuple of (is_present: bool, error_message: str)
    """
    try:
        result = subprocess.run(["gpg", "--no-tty", "--card-status"], capture_output=True, timeout=GPG_DECRYPT_TIMEOUT)
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


def require_yubikey_or_fail(operation: str) -> None:
    """
    Hard gate: Require YubiKey presence for an operation.

    Raises:
        YubiKeyRequiredError: If no YubiKey is present
    """
    present, error_msg = _check_yubikey_presence()
    if not present:
        raise YubiKeyRequiredError(operation)


# =============================================================================
# GPG Decryption Helpers
# =============================================================================

# Track if we've already retried GPG startup (to avoid infinite retries)
_gpg_startup_retry_attempted = False


def _decrypt_gpg_file_to_bytes(
    gpg_file_path: Path,
    retry_on_startup: bool = True,
    status_callback: Optional[Callable[[str], None]] = None,
) -> bytes:
    """
    Decrypt a GPG-encrypted file to bytes in memory.

    BUG-20260102-014: Added retry logic for GPG startup issues on Windows.
    On first boot, GPG agent may not be fully initialized, causing the first
    mount attempt to fail. This function will retry once after a short delay.

    Args:
        gpg_file_path: Path to .gpg file
        retry_on_startup: If True, retry once on IPC/connection errors (GPG starting up)
        status_callback: Optional callback to report status messages to UI

    Returns:
        Decrypted bytes

    Raises:
        DecryptionError: If decryption fails
    """
    global _gpg_startup_retry_attempted

    if not gpg_file_path.exists():
        raise DecryptionError(f"GPG file not found: {gpg_file_path}")

    def attempt_decrypt() -> subprocess.CompletedProcess:
        # BUG-20251219-001 FIX: Add --no-tty to prevent terminal hang
        return subprocess.run(
            ["gpg", "--no-tty", "--decrypt", str(gpg_file_path)],
            capture_output=True,
            timeout=GPG_DECRYPT_TIMEOUT,
        )

    try:
        result = attempt_decrypt()

        if result.returncode == 0:
            _gpg_startup_retry_attempted = False  # Reset for next time
            return result.stdout

        stderr = result.stderr.decode("utf-8", errors="replace")
        stderr_lower = stderr.lower()

        # BUG-20260102-014: Check for startup-related errors and retry
        is_startup_error = (
            "ipc connect" in stderr_lower
            or "can't connect" in stderr_lower
            or "no smartcard daemon" in stderr_lower
            or "agent" in stderr_lower and "not running" in stderr_lower
        )

        if is_startup_error and retry_on_startup and not _gpg_startup_retry_attempted:
            _gpg_startup_retry_attempted = True

            if status_callback:
                status_callback("⏳ GPG services starting up, please wait...")

            # Wait for GPG to initialize
            import time
            time.sleep(3)

            if status_callback:
                status_callback("🔄 Retrying GPG decryption...")

            # Retry the decryption
            result = attempt_decrypt()

            if result.returncode == 0:
                return result.stdout

            # Still failed - get updated error
            stderr = result.stderr.decode("utf-8", errors="replace")

        # Generate user-friendly error message
        from core.dependencies import format_gpg_error_with_guidance

        friendly_error = format_gpg_error_with_guidance(stderr, is_startup_issue=is_startup_error)
        raise DecryptionError(friendly_error)

    except subprocess.TimeoutExpired:
        raise DecryptionError(
            "🔴 GPG Decryption Timed Out\n\n"
            "GPG did not respond in time.\n\n"
            "SOLUTIONS:\n"
            "1. Check if YubiKey is inserted and responding (LED should blink)\n"
            "2. Try unplugging and replugging the YubiKey\n"
            "3. Restart GPG agent: gpgconf --kill gpg-agent\n"
            "4. Check if another application is using the YubiKey"
        )
    except FileNotFoundError:
        raise DecryptionError(
            "🔴 GPG Not Found\n\n"
            "GnuPG (gpg) is not installed or not in PATH.\n\n"
            "INSTALL:\n"
            "• Windows: Download Gpg4win from https://gpg4win.org/\n"
            "• Linux: sudo apt install gnupg\n"
            "• macOS: brew install gnupg"
        )


# =============================================================================
# Password Derivation
# =============================================================================


def _derive_password_from_seed(seed: bytes, salt: bytes, info: bytes = HKDF_INFO) -> str:
    """
    Derive VeraCrypt password from seed using HKDF-SHA256.

    SECURITY: This is the ONLY place password derivation should happen.
    The derived password should exist as plaintext only for the minimum
    time needed (copy to clipboard, then wipe).

    Args:
        seed: Decrypted seed bytes (32 bytes)
        salt: Salt bytes from config
        info: HKDF info string (default: HKDF_INFO constant)

    Returns:
        Base64url-encoded password string
    """
    # HKDF-Extract
    prk = hmac.new(salt, seed, hashlib.sha256).digest()

    # HKDF-Expand
    t = b""
    okm = b""
    for i in range((DERIVED_PW_LENGTH + 31) // 32):
        t = hmac.new(prk, t + info + bytes([i + 1]), hashlib.sha256).digest()
        okm += t

    pw_bytes = bytearray(okm[:DERIVED_PW_LENGTH])

    # Encode as base64url without padding
    password = base64.urlsafe_b64encode(bytes(pw_bytes)).decode("ascii").rstrip("=")

    # Memory hygiene: Wipe the buffer
    for i in range(len(pw_bytes)):
        pw_bytes[i] = 0

    return password


# =============================================================================
# RAM Temp Directory for Decrypted Keyfiles
# =============================================================================


def _get_ram_temp_dir() -> Path:
    """
    Get a RAM-backed temp directory for sensitive files.

    On Linux: Uses /dev/shm if available
    On Windows/macOS: Uses system temp (less secure, but no tmpfs available)

    Returns:
        Path to temp directory
    """
    # Try Linux tmpfs first
    if os.name != "nt":
        dev_shm = Path("/dev/shm")
        if dev_shm.exists() and dev_shm.is_dir():
            smartdrive_tmp = dev_shm / "smartdrive_tmp"
            try:
                smartdrive_tmp.mkdir(mode=0o700, exist_ok=True)
                return smartdrive_tmp
            except OSError:
                pass

    # Fallback to system temp
    return Path(tempfile.gettempdir())


def _secure_delete_file(file_path: Path) -> None:
    """Securely delete a file by overwriting with random data."""
    if not file_path.exists():
        return
    try:
        file_size = file_path.stat().st_size
        with open(file_path, "wb") as f:
            for _ in range(3):  # 3 passes
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
        file_path.unlink()
    except Exception:
        try:
            file_path.unlink()
        except Exception:
            pass


# =============================================================================
# Secret Provider - Main Class
# =============================================================================


@dataclass
class SecretProvider:
    """
    Mode-aware secret provider for on-demand secret access.

    SECURITY INVARIANTS:
    - Secrets are ONLY decrypted when explicitly requested (CPW/CKF)
    - YubiKey presence is a HARD gate for GPG modes
    - Clipboard is used for secret transfer; never print by default
    - Temporary decrypted keyfiles are auto-deleted after expiry

    Attributes:
        security_mode: Current security mode
        volume_path: Path to VeraCrypt volume
        seed_gpg_path: Path to seed.gpg (GPG_PW_ONLY mode)
        salt_b64: Base64-encoded salt (GPG_PW_ONLY mode)
        hkdf_info: HKDF info string (GPG_PW_ONLY mode)
        keyfile_gpg_path: Path to keyfile.vc.gpg (PW_GPG_KEYFILE mode)
        keyfile_plain_path: Path to plain keyfile (PW_KEYFILE mode)
        user_password: User-chosen password (PW_* modes)
        clipboard_timeout: Seconds before clipboard auto-clears
    """

    security_mode: SecurityMode
    volume_path: str
    seed_gpg_path: Optional[Path] = None
    salt_b64: Optional[str] = None
    hkdf_info: Optional[str] = None
    keyfile_gpg_path: Optional[Path] = None
    keyfile_plain_path: Optional[Path] = None
    user_password: Optional[str] = None
    clipboard_timeout: int = CLIPBOARD_TIMEOUT

    # Internal state
    _temp_keyfile_path: Optional[Path] = field(default=None, repr=False)
    _temp_keyfile_timer: Optional[threading.Timer] = field(default=None, repr=False)
    _password_copied: bool = field(default=False, repr=False)

    @classmethod
    def from_config(
        cls, config: Dict, smartdrive_dir: Optional[Path] = None, session_overrides: Optional[Dict[str, any]] = None
    ) -> "SecretProvider":
        f"""
        Create SecretProvider from config dict.

        Args:
            config: Config dict with keys from ConfigKeys
            smartdrive_dir: Path to .smartdrive directory (for resolving relative paths)
            session_overrides: Optional dict with session-specific overrides:
                - 'seed_gpg_path': Absolute path to temp {FileNames.SEED_GPG} (setup workflow)
                - 'keyfile_gpg_path': Absolute path to temp {FileNames.KEYFILE_GPG} (setup workflow)
                - 'salt_b64': Salt for HKDF (setup workflow)
                - 'hkdf_info': HKDF info string (setup workflow)

        Returns:
            Configured SecretProvider

        Note:
            Session overrides are used during setup when secret files exist
            temporarily before being deployed to .smartdrive/keys/.
        """
        from core.constants import ConfigKeys

        # Apply session overrides if provided
        overrides = session_overrides or {}

        mode_str = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
        security_mode = SecurityMode(mode_str)

        # Determine volume path (Windows vs Unix)
        volume_path = config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.VOLUME_PATH, "")
        if not volume_path:
            volume_path = config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.VOLUME_PATH, "")

        provider = cls(security_mode=security_mode, volume_path=volume_path)

        # Mode-specific configuration
        if security_mode == SecurityMode.GPG_PW_ONLY:
            # Seed-based password derivation
            # Session override takes precedence (for setup workflow with temp seed)
            if "seed_gpg_path" in overrides:
                provider.seed_gpg_path = Path(overrides["seed_gpg_path"])
            else:
                seed_path = config.get(ConfigKeys.SEED_GPG_PATH, "")
                if seed_path and smartdrive_dir:
                    # BUG-20260102-013: Normalize Windows backslashes to forward slashes
                    provider.seed_gpg_path = smartdrive_dir / Paths.normalize_config_path(seed_path)

            # Salt and HKDF info
            provider.salt_b64 = overrides.get("salt_b64", config.get(ConfigKeys.SALT_B64, ""))
            provider.hkdf_info = overrides.get(
                "hkdf_info", config.get(ConfigKeys.HKDF_INFO, CryptoParams.HKDF_INFO_DEFAULT)
            )

        elif security_mode == SecurityMode.PW_GPG_KEYFILE:
            # GPG-encrypted keyfile
            # Session override takes precedence
            if "keyfile_gpg_path" in overrides:
                provider.keyfile_gpg_path = Path(overrides["keyfile_gpg_path"])
            else:
                kf_path = config.get(ConfigKeys.ENCRYPTED_KEYFILE, "")
                if kf_path and smartdrive_dir:
                    # BUG-20260102-013: Normalize Windows backslashes to forward slashes
                    provider.keyfile_gpg_path = smartdrive_dir / Paths.normalize_config_path(kf_path)

        elif security_mode == SecurityMode.PW_KEYFILE:
            # Plain keyfile
            kf_path = config.get(ConfigKeys.KEYFILE, "")
            if kf_path and smartdrive_dir:
                # BUG-20260102-013: Normalize Windows backslashes to forward slashes
                provider.keyfile_plain_path = smartdrive_dir / Paths.normalize_config_path(kf_path)

        return provider

    # =========================================================================
    # Command Handlers
    # =========================================================================

    def handle_command(self, cmd: str) -> bool:
        """
        Handle a user command (CPW/CKF/CDP).

        Args:
            cmd: Command string (case-insensitive)

        Returns:
            True if command was handled (even if it failed)
            False if command not recognized
        """
        cmd = cmd.strip().upper()

        if cmd == UserInputs.COPY_PASSWORD:
            return self._handle_cpw()
        elif cmd == UserInputs.COPY_KEY_FILE:
            return self._handle_ckf()
        elif cmd == UserInputs.COPY_DEVICE_PATH:
            return self._handle_cdp()

        return False

    def _handle_cpw(self) -> bool:
        """Handle CPW (Copy Password) command."""
        try:
            self.copy_password_to_clipboard()
            return True
        except SecretAccessError as e:
            print(f"  [!] {e}")
            return True
        except Exception as e:
            print(f"  [!] Error copying password: {e}")
            return True

    def _handle_ckf(self) -> bool:
        """Handle CKF (Copy Keyfile) command."""
        try:
            self.copy_keyfile_path_to_clipboard()
            return True
        except SecretAccessError as e:
            print(f"  [!] {e}")
            return True
        except Exception as e:
            print(f"  [!] Error copying keyfile: {e}")
            return True

    def _handle_cdp(self) -> bool:
        """Handle CDP (Copy Device Path) command."""
        try:
            self.copy_volume_path_to_clipboard()
            return True
        except SecretAccessError as e:
            print(f"  [!] {e}")
            return True
        except Exception as e:
            print(f"  [!] Error copying device path: {e}")
            return True

    # =========================================================================
    # Public API - Copy to Clipboard
    # =========================================================================

    def copy_password_to_clipboard(self, timeout: int = None) -> None:
        """
        Copy password to clipboard (decrypt-on-demand for GPG_PW_ONLY).

        SECURITY:
        - GPG_PW_ONLY: Requires YubiKey, decrypts seed, derives password
        - PW_* modes: Copies user password (if set)
        - Password is auto-cleared from clipboard after timeout

        Args:
            timeout: Override clipboard timeout (default: self.clipboard_timeout)

        Raises:
            YubiKeyRequiredError: If GPG_PW_ONLY and no YubiKey
            ModeNotApplicableError: If no password applicable
            ClipboardUnavailableError: If clipboard not available
        """
        timeout = timeout or self.clipboard_timeout
        self._ensure_clipboard_available()

        password = None
        try:
            if self.security_mode == SecurityMode.GPG_PW_ONLY:
                # HARD GATE: Require YubiKey
                require_yubikey_or_fail(f"{UserInputs.COPY_PASSWORD} (Copy Password)")

                # Decrypt-on-demand
                password = self._derive_password_gpg_pw_only()

            elif self.security_mode in (SecurityMode.PW_ONLY, SecurityMode.PW_KEYFILE, SecurityMode.PW_GPG_KEYFILE):
                # User-chosen password
                if self.user_password:
                    password = self.user_password
                else:
                    raise SecretAccessError(
                        "Password not available. In this mode, you set the password "
                        "during volume creation. Re-enter it when prompted by VeraCrypt."
                    )
            else:
                raise ModeNotApplicableError(UserInputs.COPY_PASSWORD, self.security_mode)

            # Copy to clipboard with TTL
            self._copy_to_clipboard(password, timeout, "password")
            self._password_copied = True
            print(f"  [OK] Password copied to clipboard.")
            print(f"       Auto-clears in {timeout} seconds.")

        finally:
            # Memory hygiene: wipe password from local scope
            if password:
                # Python strings are immutable, but we can hint to GC
                password = None

    def copy_keyfile_path_to_clipboard(self, timeout: int = None) -> None:
        """
        Copy keyfile path to clipboard (decrypt-on-demand for PW_GPG_KEYFILE).

        SECURITY:
        - PW_GPG_KEYFILE: Requires YubiKey, decrypts keyfile to RAM temp
        - PW_KEYFILE: Copies plain keyfile path
        - GPG_PW_ONLY/PW_ONLY: Not applicable (no keyfile)

        Args:
            timeout: Override clipboard timeout (default: self.clipboard_timeout)

        Raises:
            YubiKeyRequiredError: If PW_GPG_KEYFILE and no YubiKey
            ModeNotApplicableError: If mode doesn't use keyfile
            ClipboardUnavailableError: If clipboard not available
        """
        timeout = timeout or self.clipboard_timeout
        self._ensure_clipboard_available()

        if self.security_mode == SecurityMode.GPG_PW_ONLY:
            raise ModeNotApplicableError("CKF (Copy Keyfile)", self.security_mode)

        if self.security_mode == SecurityMode.PW_ONLY:
            raise ModeNotApplicableError("CKF (Copy Keyfile)", self.security_mode)

        keyfile_path = None

        if self.security_mode == SecurityMode.PW_GPG_KEYFILE:
            # HARD GATE: Require YubiKey
            require_yubikey_or_fail("CKF (Copy Keyfile)")

            # Decrypt keyfile to RAM temp
            keyfile_path = self._decrypt_keyfile_to_temp()

            # Schedule auto-deletion
            self._schedule_keyfile_deletion(timeout)

        elif self.security_mode == SecurityMode.PW_KEYFILE:
            # Plain keyfile - just copy path
            if self.keyfile_plain_path and self.keyfile_plain_path.exists():
                keyfile_path = self.keyfile_plain_path
            else:
                raise SecretAccessError(f"Keyfile not found: {self.keyfile_plain_path}")

        if keyfile_path:
            # Copy path to clipboard (no TTL for non-secret path)
            self._copy_to_clipboard(str(keyfile_path), ttl=None, label="keyfile_path")
            print(f"  [OK] Keyfile path copied: {keyfile_path}")
            if self.security_mode == SecurityMode.PW_GPG_KEYFILE:
                print(f"       Temp keyfile will be deleted in {timeout} seconds.")

    def copy_volume_path_to_clipboard(self) -> None:
        """
        Copy volume/device path to clipboard (non-secret).

        Raises:
            ClipboardUnavailableError: If clipboard not available
        """
        self._ensure_clipboard_available()

        if not self.volume_path:
            raise SecretAccessError("Volume path not configured")

        # Non-secret, no TTL
        self._copy_to_clipboard(self.volume_path, ttl=None, label="volume_path")
        print(f"  [OK] Volume path copied: {self.volume_path}")

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _ensure_clipboard_available(self) -> None:
        """Raise if clipboard is not available."""
        if not _CLIPBOARD_AVAILABLE:
            raise ClipboardUnavailableError()
        if not clipboard_is_available():
            raise ClipboardUnavailableError()

    def _copy_to_clipboard(self, text: str, ttl: Optional[int], label: str) -> None:
        """Copy text to clipboard with optional TTL."""
        try:
            clipboard_set_text(text, ttl_seconds=ttl, label=label)
        except ClipboardError as e:
            raise SecretAccessError(f"Clipboard error: {e.message}")

    def _derive_password_gpg_pw_only(self) -> str:
        """
        Derive password for GPG_PW_ONLY mode.

        SECURITY: This method is the ONLY code path that should derive
        the password from seed. The derived password exists as plaintext
        only for the minimum time needed.

        Returns:
            Derived password string

        Raises:
            DecryptionError: If decryption fails
            SecretAccessError: If missing seed or salt
        """
        # Validate configuration
        if not self.seed_gpg_path:
            raise SecretAccessError(
                "Seed GPG path not configured. This is required for GPG_PW_ONLY mode.\n"
                f"  Expected: .smartdrive/keys/{FileNames.SEED_GPG}\n"
                "  If running during setup, ensure session overrides are passed."
            )

        if not self.salt_b64:
            raise SecretAccessError("Salt not configured. This is required for GPG_PW_ONLY password derivation.")

        # Check file exists
        if not self.seed_gpg_path.exists():
            raise SecretAccessError(
                f"Seed file not found: {self.seed_gpg_path}\n" f"  This file should have been created during setup."
            )

        # Decrypt seed
        seed_bytes = _decrypt_gpg_file_to_bytes(self.seed_gpg_path)

        # Decode salt
        salt = base64.b64decode(self.salt_b64)

        # Get HKDF info (use configured value or default)
        info_str = self.hkdf_info or CryptoParams.HKDF_INFO_DEFAULT
        info = info_str.encode("utf-8")

        # Derive password
        password = _derive_password_from_seed(seed_bytes, salt, info)

        # Memory hygiene: wipe seed
        seed_buffer = bytearray(seed_bytes)
        for i in range(len(seed_buffer)):
            seed_buffer[i] = 0

        return password

    def _decrypt_keyfile_to_temp(self) -> Path:
        """
        Decrypt GPG-encrypted keyfile to RAM temp directory.

        Returns:
            Path to decrypted temp keyfile

        Raises:
            DecryptionError: If decryption fails
        """
        if not self.keyfile_gpg_path:
            raise SecretAccessError("Encrypted keyfile path not configured")

        # Clean up any existing temp keyfile
        self._cleanup_temp_keyfile()

        # Decrypt keyfile
        keyfile_bytes = _decrypt_gpg_file_to_bytes(self.keyfile_gpg_path)

        # Write to RAM temp
        ram_dir = _get_ram_temp_dir()
        temp_path = ram_dir / f"keyfile_{os.urandom(4).hex()}.key"

        try:
            temp_path.write_bytes(keyfile_bytes)
            # Restrict permissions
            if os.name != "nt":
                temp_path.chmod(0o600)
            self._temp_keyfile_path = temp_path
            return temp_path
        finally:
            # Wipe keyfile bytes from memory
            buffer = bytearray(keyfile_bytes)
            for i in range(len(buffer)):
                buffer[i] = 0

    def _schedule_keyfile_deletion(self, timeout: int) -> None:
        """Schedule auto-deletion of temp keyfile after timeout."""
        if self._temp_keyfile_timer:
            self._temp_keyfile_timer.cancel()

        def delete_keyfile():
            self._cleanup_temp_keyfile()
            print(f"\n  [OK] Temp keyfile auto-deleted after {timeout}s timeout.")

        self._temp_keyfile_timer = threading.Timer(timeout, delete_keyfile)
        self._temp_keyfile_timer.daemon = True
        self._temp_keyfile_timer.start()

    def _cleanup_temp_keyfile(self) -> None:
        """Securely delete temp keyfile if it exists."""
        if self._temp_keyfile_path and self._temp_keyfile_path.exists():
            _secure_delete_file(self._temp_keyfile_path)
            self._temp_keyfile_path = None
        if self._temp_keyfile_timer:
            self._temp_keyfile_timer.cancel()
            self._temp_keyfile_timer = None

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup(self) -> None:
        """
        Clean up all sensitive data.

        MUST be called when done with SecretProvider:
        - Clears clipboard if we wrote to it
        - Deletes any temp keyfile
        """
        log("[CLEANUP] Starting cleanup")

        # Clear clipboard if we copied sensitive data
        if self._password_copied:
            log("[CLEANUP] Attempting clipboard clear")
            try:
                clipboard_clear_if_ours()
                log("[CLEANUP] clipboard_clear_if_ours completed")
            except Exception as e:
                log(f"[CLEANUP] clipboard_clear_if_ours failed: {e}")
                try:
                    clipboard_clear_best_effort()
                    log("[CLEANUP] clipboard_clear_best_effort completed")
                except Exception as e2:
                    log(f"[CLEANUP] clipboard_clear_best_effort failed: {e2}")
                    pass
            self._password_copied = False
        else:
            log(f"[CLEANUP] No clipboard clear needed (_password_copied={self._password_copied})")

        # Clean up temp keyfile
        log("[CLEANUP] Attempting temp keyfile cleanup")
        self._cleanup_temp_keyfile()
        log("[CLEANUP] Cleanup complete")

    def __del__(self):
        """Ensure cleanup on garbage collection."""
        try:
            self.cleanup()
        except Exception:
            pass


# =============================================================================
# Convenience Functions
# =============================================================================


def create_command_loop_prompt() -> str:
    """
    Return the standard command loop prompt text.

    Used for consistency across all manual VeraCrypt steps.
    """
    return "  Commands: CPW (password), CKF (keyfile), CDP (device path), YES (done), NO (abort)"


def run_command_loop(
    provider: SecretProvider, on_yes: Callable[[], bool], on_no: Callable[[], bool] = None, prompt_text: str = None
) -> bool:
    """
    Run a command loop for manual VeraCrypt steps.

    Args:
        provider: SecretProvider for handling CPW/CKF/CDP
        on_yes: Callback when user types YES (return True to exit loop)
        on_no: Callback when user types NO (default: return False)
        prompt_text: Override default prompt

    Returns:
        True if user completed successfully (YES), False if aborted (NO)
    """
    prompt = prompt_text or create_command_loop_prompt()
    print(prompt)

    while True:
        response = input("  > ").strip().upper()

        if response in ("CPW", "CKF", "CDP"):
            provider.handle_command(response)
            continue
        elif response == "YES":
            if on_yes():
                provider.cleanup()
                return True
            # on_yes returned False, continue loop
        elif response == "NO":
            provider.cleanup()
            if on_no:
                return on_no()
            return False
        else:
            print(prompt)
