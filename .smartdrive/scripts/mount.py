#!/usr/bin/env python3
"""
SmartDrive mount script (MVP)

Updated: 2025-12-16 - Added module-level logger initialization

Single-file Python script to:
- Load or create config.json
- Decrypt an encrypted VeraCrypt keyfile via GPG + YubiKey
- Mount a VeraCrypt volume (device or container) on Windows/Linux/macOS
- Clean up the decrypted keyfile

Dependencies (runtime):
- Python 3
- gpg in PATH
- VeraCrypt:
    - Windows: VeraCrypt.exe installed or portable and discoverable
    - Linux/macOS: 'veracrypt' in PATH
"""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from getpass import getpass
from pathlib import Path

# =============================================================================
# Module-level logger - MUST be initialized at import time to avoid NameError
# =============================================================================
_mount_logger = logging.getLogger("smartdrive.mount")

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/mount.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/mount.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.constants import ConfigKeys, CryptoParams, Defaults, FileNames
    from core.limits import Limits
    from core.modes import SecurityMode
    from core.paths import Paths
    from core.platform import is_windows as _is_windows
    from core.platform import windows_refresh_explorer, windows_set_attributes

    CONFIG_FILENAME = FileNames.CONFIG_JSON
except ImportError:
    # Fallback for standalone operation
    CONFIG_FILENAME = "config.json"

    class Defaults:
        WINDOWS_MOUNT_LETTER = "V"


def get_ram_temp_dir():
    """Get a RAM-backed temp directory if available, else system temp."""
    if platform.system() == "Linux":
        ram_dir = Path("/dev/shm")
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    elif platform.system() == "Darwin":  # macOS
        ram_dir = Path("/tmp")
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    # Windows or fallback
    return Path(tempfile.gettempdir())


def secure_delete(file_path, passes=3):
    """Securely delete a file by overwriting with random data."""
    if not file_path.exists():
        return
    try:
        file_size = file_path.stat().st_size
        with open(file_path, "wb") as f:
            for _ in range(passes):
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
        os.unlink(file_path)
    except Exception as e:
        # Fallback to regular delete
        try:
            os.unlink(file_path)
        except:
            pass
        log(f"Warning: Could not securely delete {file_path}: {e}")


CONFIG_TEMPLATE = {
    # Schema version for compatibility
    "schema_version": 2,
    # Mode: "pw_only", "pw_keyfile", "pw_gpg_keyfile", "gpg_pw_only"
    "mode": "pw_gpg_keyfile",
    # Keyfile settings (for pw_keyfile/pw_gpg_keyfile modes)
    "encrypted_keyfile": f"../keys/{FileNames.KEYFILE_GPG}",
    # GPG password-only settings (for gpg_pw_only mode)
    "seed_gpg_path": f"../keys/{FileNames.SEED_GPG}",
    "kdf": CryptoParams.KDF_HKDF_SHA256,
    "salt_b64": "base64_encoded_salt",
    "hkdf_info": CryptoParams.HKDF_INFO_DEFAULT,
    "pw_encoding": CryptoParams.PW_ENCODING_DEFAULT,
    "windows": {
        # Use either a device path like:
        #   "\\Device\\Harddisk1\\Partition2"
        # NOTE: Harddisk numbers can change when plugging into different USB ports!
        # Use PowerShell 'Get-Disk | Format-Table' to find the correct number.
        "volume_path": "\\Device\\Harddisk1\\Partition2",
        "mount_letter": "V",
        # Optional override. If empty, script tries to auto-detect VeraCrypt.exe
        "veracrypt_path": "",
    },
    "unix": {
        # Device path: "/dev/sdX2"
        # or container: "/run/media/user/PAYLOAD/vault.hc"
        "volume_path": "/dev/sdX2",
        "mount_point": "~/veradrive",
    },
}


# Global GUI mode flag
_GUI_MODE = False


def set_gui_mode(gui_mode: bool) -> None:
    """Set the global GUI mode flag."""
    global _GUI_MODE
    _GUI_MODE = gui_mode


def log(msg: str) -> None:
    """Log a message, handling Unicode encoding issues."""
    if _GUI_MODE:
        return  # Suppress logging in GUI mode
    try:
        print(f"[SmartDrive] {msg}")
    except UnicodeEncodeError:
        # Fallback to ASCII-safe version
        safe_msg = msg.encode("ascii", "replace").decode("ascii")
        print(f"[SmartDrive] {safe_msg}")


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def run_cmd(args, *, check=True, capture_output=False, text=True):
    """Run a subprocess command with basic error handling."""
    try:
        result = subprocess.run(
            args,
            check=check,
            capture_output=capture_output,
            text=text,
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Command failed with exit code {e.returncode}: {' '.join(args)}\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}"
        )


def update_drive_icon(mounted: bool):
    """Update the drive icon based on mount state (no admin required)."""
    if not _is_windows():
        return

    try:
        # Launcher root is the drive root in deployed mode
        launcher_root = _project_root

        desktop_ini = launcher_root / "desktop.ini"

        icon_filename = FileNames.ICON_MOUNTED if mounted else FileNames.ICON_MAIN
        # Always reference icons in .smartdrive/static (relative path inside desktop.ini)
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

        # Rewrite desktop.ini deterministically (avoids mixed IconResource/IconFile states)
        with open(desktop_ini, "w", encoding="utf-8") as f:
            f.write(ini_content)

        # Required attributes: desktop.ini System+Hidden, drive root System
        windows_set_attributes(desktop_ini, hidden=True, system=True)
        windows_set_attributes(launcher_root, system=True)

        # Best-effort refresh (tree view caching may still require restart)
        windows_refresh_explorer(timeout_s=float(Limits.PROCESS_CHECK_TIMEOUT))
    except Exception as e:
        print(f"Could not update drive icon: {e}")


def load_or_init_config(script_root: Path) -> dict:
    """Load config.json or create a template if missing."""
    config_path = script_root / CONFIG_FILENAME
    if not config_path.exists():
        log(f"No {CONFIG_FILENAME} found. Creating template.")
        try:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(CONFIG_TEMPLATE, f, indent=2)
        except OSError as e:
            print(f"Failed to write {CONFIG_FILENAME}: {e}", file=sys.stderr)
            sys.exit(1)
        print(
            f"{CONFIG_FILENAME} has been created at:\n  {config_path}\n"
            "Please edit it to match your environment (volume paths, mount points), "
            "then run this script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to read/parse {CONFIG_FILENAME}: {e}", file=sys.stderr)
        sys.exit(1)

    return cfg


def resolve_encrypted_keyfile(script_root: Path, cfg: dict) -> Path | None:
    """
    Resolve path to keyfile using SSOT from Paths.
    Returns None if no keyfile configured (password-only mode).

    SSOT: Keys MUST be under .smartdrive/keys/, not <drive>:/keys/
    The launcher_root is derived from script_root (which is .smartdrive/)
    """
    mode = cfg.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

    # Check if mode requires a keyfile
    try:
        security_mode = SecurityMode(mode)
        if not security_mode.requires_keyfile:
            return None
    except ValueError:
        return None

    # SSOT: launcher_root = parent of .smartdrive/
    launcher_root = script_root.parent

    # Try GPG-encrypted keyfile first
    gpg_keyfile = Paths.keyfile_gpg(launcher_root)
    if gpg_keyfile.exists():
        _mount_logger.info(f"keys.resolve.keyfile: path={gpg_keyfile}, exists=True")
        return gpg_keyfile

    # Try plain keyfile
    plain_keyfile = Paths.keyfile_plain(launcher_root)
    if plain_keyfile.exists():
        _mount_logger.info(f"keys.resolve.keyfile: path={plain_keyfile}, exists=True")
        return plain_keyfile

    # Fallback to config-specified path (legacy support)
    rel = (cfg.get(ConfigKeys.ENCRYPTED_KEYFILE) or "").strip()
    if rel:
        # Handle legacy "../keys/..." paths by converting to SSOT
        if rel.startswith("../keys/"):
            rel = "keys/" + rel[8:]  # Convert "../keys/x" to "keys/x"
        enc_path = (script_root / rel).resolve()
        if enc_path.exists():
            _mount_logger.warning(f"keys.resolve.keyfile: legacy_path={enc_path} (should use .smartdrive/keys/)")
            return enc_path

    # If we get here, keyfile is required but not found
    expected_path = gpg_keyfile
    _mount_logger.error(f"keys.resolve.keyfile: path={expected_path}, exists=False - MISSING")
    raise RuntimeError(f"Keyfile not found: {expected_path}")


def resolve_encrypted_seed(script_root: Path, cfg: dict) -> Path | None:
    """
    Resolve path to encrypted seed using SSOT from Paths.
    Returns None if not gpg_pw_only mode.

    SSOT: Seed MUST be under .smartdrive/keys/, not <drive>:/keys/
    """
    if cfg.get(ConfigKeys.MODE) != SecurityMode.GPG_PW_ONLY.value:
        return None

    # SSOT: launcher_root = parent of .smartdrive/
    launcher_root = script_root.parent

    # Primary path from Paths SSOT
    seed_path = Paths.seed_gpg(launcher_root)

    _mount_logger.info(f"keys.resolve.seed_gpg: path={seed_path}, exists={seed_path.exists()}")

    if seed_path.exists():
        return seed_path

    # Fallback to config-specified path (legacy support)
    rel = (cfg.get(ConfigKeys.SEED_GPG_PATH) or "").strip()
    if rel:
        # Handle legacy "../keys/..." paths by converting to SSOT
        if rel.startswith("../keys/"):
            rel = "keys/" + rel[8:]  # Convert "../keys/x" to "keys/x"
        legacy_path = (script_root / rel).resolve()
        if legacy_path.exists():
            _mount_logger.warning(f"keys.resolve.seed_gpg: legacy_path={legacy_path} (should use .smartdrive/keys/)")
            return legacy_path

    # Seed required but not found
    _mount_logger.error(f"keys.resolve.seed_gpg: expected={seed_path}, exists=False - MISSING")
    raise RuntimeError(f"Encrypted seed not found: {seed_path}")


def normalize_mount_inputs(config: dict, password: str | None = None) -> dict:
    """
    Normalize and validate mount inputs from config and user input.

    This is the SSOT boundary for mount input validation. All mount operations
    must pass through this function to ensure:
    - None values are converted to empty strings where appropriate
    - Required fields are present per security mode
    - Whitespace is trimmed consistently
    - No NoneType.strip() crashes can occur

    Args:
        config: Raw config dict (may contain None values)
        password: User-provided password (may be None)

    Returns:
        Normalized dict with validated inputs

    Raises:
        ValueError: If required inputs are missing for the configured mode

    Structured logging events:
        - mount.inputs.normalized
        - mount.inputs.invalid
    """
    mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

    # Normalize config sections (handle None values)
    cfg_win = config.get(ConfigKeys.WINDOWS) or {}
    cfg_unix = config.get(ConfigKeys.UNIX) or {}

    # Normalize string fields safely
    def safe_str(value) -> str:
        """Convert None to empty string, trim whitespace."""
        return (value or "").strip()

    normalized = {
        "mode": mode,
        "password": safe_str(password) if password is not None else None,
        "windows": {
            ConfigKeys.VOLUME_PATH: safe_str(cfg_win.get(ConfigKeys.VOLUME_PATH)),
            "mount_letter": safe_str(cfg_win.get(ConfigKeys.MOUNT_LETTER)).upper() or "V",
            "veracrypt_path": safe_str(cfg_win.get(ConfigKeys.VERACRYPT_PATH)),
        },
        "unix": {
            ConfigKeys.VOLUME_PATH: safe_str(cfg_unix.get(ConfigKeys.VOLUME_PATH)),
            "mount_point": safe_str(cfg_unix.get(ConfigKeys.MOUNT_POINT)) or "~/veradrive",
        },
        ConfigKeys.KEYFILE: safe_str(config.get(ConfigKeys.ENCRYPTED_KEYFILE)),
        "seed_gpg": safe_str(config.get(ConfigKeys.SEED_GPG_PATH)),
    }

    # Validate required fields per mode
    try:
        security_mode = SecurityMode(mode)
    except ValueError:
        _mount_logger.error(f"mount.inputs.invalid: field=mode, value={mode}, reason=unknown_mode")
        raise ValueError(f"Invalid security mode: {mode}")

    # Check password requirement
    if mode not in [SecurityMode.GPG_PW_ONLY.value]:
        if normalized["password"] is None or not normalized["password"]:
            _mount_logger.error(f"mount.inputs.invalid: field=password, reason=required_but_missing")
            raise ValueError(f"Password is required for mode '{mode}'")

    # Check keyfile requirement
    if security_mode.requires_keyfile:
        if not normalized[ConfigKeys.KEYFILE] and not normalized["seed_gpg"]:
            _mount_logger.error(f"mount.inputs.invalid: field=keyfile, reason=required_but_missing, mode={mode}")
            raise ValueError(f"Keyfile is required for mode '{mode}' but not configured")

    # Platform-specific validation (only for current platform)
    system = platform.system().lower()
    if system == "windows":
        if not normalized["windows"][ConfigKeys.VOLUME_PATH]:
            _mount_logger.error("mount.inputs.invalid: field=windows.volume_path, reason=missing")
            raise ValueError("windows.volume_path is required but missing/empty in config.json")
    elif system in ["linux", "darwin"]:
        if not normalized["unix"][ConfigKeys.VOLUME_PATH]:
            _mount_logger.error("mount.inputs.invalid: field=unix.volume_path, reason=missing")
            raise ValueError("unix.volume_path is required but missing/empty in config.json")

    # Log normalized inputs (no secrets)
    _mount_logger.info(
        f"mount.inputs.normalized: mode={mode}, "
        f"has_password={normalized['password'] is not None and bool(normalized['password'])}, "
        f"has_keyfile={bool(normalized[ConfigKeys.KEYFILE])}, "
        f"has_seed={bool(normalized['seed_gpg'])}"
    )

    return normalized


def is_gpg_encrypted(file_path: Path) -> bool:
    """Check if a file is GPG-encrypted (by extension or magic bytes)."""
    # Check extension
    if file_path.suffix.lower() in [".gpg", ".pgp", ".asc"]:
        return True

    # Check magic bytes (GPG binary format starts with specific bytes)
    try:
        with open(file_path, "rb") as f:
            header = f.read(2)
            # GPG packets start with 0x84, 0x85, 0x8c, 0xa3, etc. (old format)
            # or 0xc0-0xff (new format)
            if header and (header[0] >= 0x84 or header[0] >= 0xC0):
                return True
    except:
        pass

    return False


def load_keyfile(keyfile_path: Path) -> bytes:
    """
    Load keyfile - either decrypt GPG-encrypted or read plain file.
    Returns keyfile bytes.
    """
    if is_gpg_encrypted(keyfile_path):
        log(f"Decrypting GPG-encrypted keyfile: {keyfile_path.name}")
        log("(YubiKey PIN/touch may be required)")
        # BUG-20251219-001 FIX: Use --no-tty and timeout to prevent terminal hang
        gpg_timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30) if Limits else 30
        try:
            result = subprocess.run(
                ["gpg", "--no-tty", "--yes", "--decrypt", str(keyfile_path)],
                check=True,
                capture_output=True,
                text=False,
                timeout=gpg_timeout,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            log(f"GPG decryption timed out for keyfile: {keyfile_path.name}")
            raise RuntimeError(f"GPG decryption timed out (check YubiKey)")
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else "Unknown error"
            stderr_lower = stderr_text.lower()

            # Provide user-friendly error messages based on common GPG errors
            if "no pinentry" in stderr_lower or "pinentry" in stderr_lower:
                if _GUI_MODE:
                    error_msg = (
                        "GPG PIN ENTRY MISSING\n\n"
                        "GPG cannot prompt for your YubiKey PIN.\n"
                        "This usually means the GPG agent is not running properly.\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Start Kleopatra (GUI for GPG):\n"
                        "   - Launch Kleopatra from Start Menu\n"
                        "   - This will start the GPG agent with PIN entry\n\n"
                        "2. Or restart GPG agent:\n"
                        "   gpg-connect-agent /bye\n\n"
                        "3. Or restart your computer\n"
                        "   (GPG agent should start on login)\n\n"
                        "After starting the agent, try mounting again."
                    )
                else:
                    error_msg = (
                        "\n" + "=" * 70 + "\n"
                        "GPG PIN ENTRY MISSING\n" + "=" * 70 + "\n\n"
                        "GPG cannot prompt for your YubiKey PIN.\n"
                        "This usually means the GPG agent is not running properly.\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Start Kleopatra (GUI for GPG):\n"
                        "   - Launch Kleopatra from Start Menu\n"
                        "   - This will start the GPG agent with PIN entry\n\n"
                        "2. Or restart GPG agent:\n"
                        "   gpg-connect-agent /bye\n\n"
                        "3. Or restart your computer\n"
                        "   (GPG agent should start on login)\n\n"
                        "After starting the agent, try mounting again.\n" + "=" * 70
                    )
            elif (
                "card not present" in stderr_lower
                or "no reader found" in stderr_lower
                or "card removed" in stderr_lower
            ):
                if _GUI_MODE:
                    error_msg = (
                        "YUBIKEY NOT DETECTED\n\n"
                        "Your YubiKey is not detected during decryption.\n"
                        "This could be because:\n\n"
                        "1. YubiKey is not inserted\n"
                        "2. YubiKey was removed after starting GPG agent\n"
                        "3. YubiKey driver issues\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Insert your YubiKey if not already inserted\n\n"
                        "2. Restart Kleopatra or GPG agent:\n"
                        "   - Close Kleopatra completely\n"
                        "   - Re-insert YubiKey\n"
                        "   - Re-open Kleopatra\n\n"
                        "3. Or restart GPG agent:\n"
                        "   gpg-connect-agent killagent /bye\n"
                        "   gpg-connect-agent /bye\n\n"
                        "4. Check YubiKey with GPG directly:\n"
                        "   gpg --card-status\n\n"
                        "After fixing the issue, try mounting again."
                    )
                else:
                    error_msg = (
                        "\n" + "=" * 70 + "\n"
                        "YUBIKEY NOT DETECTED\n" + "=" * 70 + "\n\n"
                        "Your YubiKey is not detected during decryption.\n"
                        "This could be because:\n\n"
                        "1. YubiKey is not inserted\n"
                        "2. YubiKey was removed after starting GPG agent\n"
                        "3. YubiKey driver issues\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Insert your YubiKey if not already inserted\n\n"
                        "2. Restart Kleopatra or GPG agent:\n"
                        "   - Close Kleopatra completely\n"
                        "   - Re-insert YubiKey\n"
                        "   - Re-open Kleopatra\n\n"
                        "3. Or restart GPG agent:\n"
                        "   gpg-connect-agent killagent /bye\n"
                        "   gpg-connect-agent /bye\n\n"
                        "4. Check YubiKey with GPG directly:\n"
                        "   gpg --card-status\n\n"
                        "After fixing the issue, try mounting again.\n" + "=" * 70
                    )
            elif "bad signature" in stderr_lower or "signature verification failed" in stderr_lower:
                if _GUI_MODE:
                    error_msg = (
                        "GPG SIGNATURE VERIFICATION FAILED\n\n"
                        "The encrypted keyfile may be corrupted or tampered with.\n"
                        "This could also indicate YubiKey communication issues.\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Verify your YubiKey is properly inserted and functioning\n\n"
                        "2. Try re-encrypting the keyfile:\n"
                        "   - Use the rekey.py script to create a new encrypted keyfile\n\n"
                        "3. Check the keyfile integrity:\n"
                        f"   gpg --verify {FileNames.KEYFILE_GPG}\n\n"
                        "If the problem persists, the keyfile may be corrupted."
                    )
                else:
                    error_msg = (
                        "\n" + "=" * 70 + "\n"
                        "GPG SIGNATURE VERIFICATION FAILED\n" + "=" * 70 + "\n\n"
                        "The encrypted keyfile may be corrupted or tampered with.\n"
                        "This could also indicate YubiKey communication issues.\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Verify your YubiKey is properly inserted and functioning\n\n"
                        "2. Try re-encrypting the keyfile:\n"
                        "   - Use the rekey.py script to create a new encrypted keyfile\n\n"
                        "3. Check the keyfile integrity:\n"
                        f"   gpg --verify {FileNames.KEYFILE_GPG}\n\n"
                        "If the problem persists, the keyfile may be corrupted.\n" + "=" * 70
                    )
            elif "decryption failed" in stderr_lower or "no secret key" in stderr_lower:
                if _GUI_MODE:
                    error_msg = (
                        "GPG DECRYPTION FAILED\n\n"
                        "GPG could not decrypt the keyfile.\n"
                        "This usually means:\n\n"
                        "1. Wrong YubiKey (different key than used for encryption)\n"
                        "2. YubiKey PIN changed or forgotten\n"
                        "3. GPG keyring corrupted\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Ensure you're using the same YubiKey used to encrypt the file\n\n"
                        "2. Try a different YubiKey if you have multiple\n\n"
                        "3. Reset YubiKey PIN if forgotten (CAUTION: this may lock the key)\n\n"
                        "4. Re-encrypt the keyfile with current YubiKey:\n"
                        "   python rekey.py\n\n"
                        "If you cannot decrypt, you may need to recreate the volume."
                    )
                else:
                    error_msg = (
                        "\n" + "=" * 70 + "\n"
                        "GPG DECRYPTION FAILED\n" + "=" * 70 + "\n\n"
                        "GPG could not decrypt the keyfile.\n"
                        "This usually means:\n\n"
                        "1. Wrong YubiKey (different key than used for encryption)\n"
                        "2. YubiKey PIN changed or forgotten\n"
                        "3. GPG keyring corrupted\n\n"
                        "SOLUTIONS:\n\n"
                        "1. Ensure you're using the same YubiKey used to encrypt the file\n\n"
                        "2. Try a different YubiKey if you have multiple\n\n"
                        "3. Reset YubiKey PIN if forgotten (CAUTION: this may lock the key)\n\n"
                        "4. Re-encrypt the keyfile with current YubiKey:\n"
                        "   python rekey.py\n\n"
                        "If you cannot decrypt, you may need to recreate the volume.\n" + "=" * 70
                    )
            else:
                # Generic GPG error
                if _GUI_MODE:
                    error_msg = (
                        "GPG DECRYPTION ERROR\n\n"
                        f"GPG failed to decrypt the keyfile with an unexpected error:\n"
                        f"{stderr_text}\n\n"
                        "COMMON CAUSES:\n\n"
                        "1. GPG agent not running - Start Kleopatra\n"
                        "2. YubiKey not inserted or not detected\n"
                        "3. YubiKey PIN required but not prompted\n"
                        "4. Wrong YubiKey or corrupted keyfile\n\n"
                        "TROUBLESHOOTING:\n\n"
                        "1. Start Kleopatra and ensure YubiKey is detected\n"
                        "2. Run: gpg --card-status\n"
                        "3. Try: gpg-connect-agent /bye\n"
                        "4. If issues persist, run rekey.py to re-encrypt\n\n"
                        "After fixing the issue, try mounting again."
                    )
                else:
                    error_msg = (
                        "\n" + "=" * 70 + "\n"
                        "GPG DECRYPTION ERROR\n" + "=" * 70 + "\n\n"
                        f"GPG failed to decrypt the keyfile with an unexpected error:\n"
                        f"{stderr_text}\n\n"
                        "COMMON CAUSES:\n\n"
                        "1. GPG agent not running - Start Kleopatra\n"
                        "2. YubiKey not inserted or not detected\n"
                        "3. YubiKey PIN required but not prompted\n"
                        "4. Wrong YubiKey or corrupted keyfile\n\n"
                        "TROUBLESHOOTING:\n\n"
                        "1. Start Kleopatra and ensure YubiKey is detected\n"
                        "2. Run: gpg --card-status\n"
                        "3. Try: gpg-connect-agent /bye\n"
                        "4. If issues persist, run rekey.py to re-encrypt\n\n"
                        "After fixing the issue, try mounting again.\n" + "=" * 70
                    )

            raise RuntimeError(error_msg)
    else:
        log(f"Loading plain keyfile: {keyfile_path.name}")
        with open(keyfile_path, "rb") as f:
            return f.read()


def find_veracrypt_windows(script_root: Path, cfg: dict) -> Path:
    """
    Try to find VeraCrypt.exe on Windows:
    1) Config override
    2) Local copy next to this script
    3) Typical install locations
    4) PATH
    """
    cfg_win = cfg.get(ConfigKeys.WINDOWS) or {}
    override = cfg_win.get(ConfigKeys.VERACRYPT_PATH, "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise RuntimeError(f"veracrypt_path in config.json points to non-existent file: {override}")

    # Use Paths.veracrypt_exe() for standard locations
    try:
        vc_exe = Paths.veracrypt_exe()
        if vc_exe.is_file():
            return vc_exe
    except (RuntimeError, NameError):
        pass  # Fall through to manual search

    # Additional local candidates
    candidates = [
        script_root / Paths.VERACRYPT_EXE_NAME,
        script_root.parent / Paths.VERACRYPT_EXE_NAME,
    ]
    for c in candidates:
        if c.is_file():
            return c

    raise RuntimeError(
        "Could not find VeraCrypt.exe. " "Set 'windows.veracrypt_path' in config.json or install VeraCrypt."
    )


def check_gpg_yubikey_readiness() -> None:
    """
    Check that GPG agent is running and YubiKey is available.
    Provides clear error messages with actionable solutions.
    """
    import time

    log("Checking GPG and YubiKey readiness...")

    # Check 1: GPG agent process
    agent_running = False
    try:
        if platform.system().lower() == "windows":
            # On Windows, check for gpg-agent.exe process
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq gpg-agent.exe", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=Limits.PROCESS_CHECK_TIMEOUT,
            )
            agent_running = result.returncode == 0 and result.stdout and "gpg-agent.exe" in result.stdout
        else:
            # On Unix, check for gpg-agent process
            result = subprocess.run(
                ["pgrep", "-f", "gpg-agent"], capture_output=True, timeout=Limits.PROCESS_CHECK_TIMEOUT
            )
            agent_running = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass

    if not agent_running:
        log("GPG agent not running, attempting to start it...")
        try:
            # Try to start the GPG agent
            result = subprocess.run(
                ["gpg-connect-agent", "/bye"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=Limits.GPG_AGENT_START_TIMEOUT,
            )
            if result.returncode == 0:
                log("GPG agent started successfully ✓")
                # Wait a moment for it to initialize
                time.sleep(2)
                # Re-check if agent is now running
                try:
                    if platform.system().lower() == "windows":
                        result = subprocess.run(
                            ["tasklist", "/FI", "IMAGENAME eq gpg-agent.exe", "/NH"],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="ignore",
                            timeout=Limits.PROCESS_CHECK_TIMEOUT,
                        )
                        agent_running = result.returncode == 0 and result.stdout and "gpg-agent.exe" in result.stdout
                    else:
                        result = subprocess.run(
                            ["pgrep", "-f", "gpg-agent"], capture_output=True, timeout=Limits.PROCESS_CHECK_TIMEOUT
                        )
                        agent_running = result.returncode == 0
                except:
                    pass
                if agent_running:
                    log("GPG agent is now running ✓")
                else:
                    log("Failed to verify GPG agent started")
            else:
                log("Failed to start GPG agent")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            log("Could not start GPG agent automatically")

        # If still not running, show error
        if not agent_running:
            if _GUI_MODE:
                error_msg = (
                    "GPG AGENT NOT RUNNING\n\n"
                    "The GPG agent (gpg-agent.exe) is not running.\n"
                    "This is required to communicate with your YubiKey.\n\n"
                    "The script attempted to start it automatically but failed.\n\n"
                    "SOLUTIONS:\n\n"
                    "1. Start Kleopatra (GUI for GPG):\n"
                    "   - Launch Kleopatra from Start Menu\n"
                    "   - This will start the GPG agent automatically\n\n"
                    "2. Or start GPG agent manually:\n"
                    "   gpg-connect-agent /bye\n\n"
                    "3. Or restart your computer\n"
                    "   (GPG agent should start on login)\n\n"
                    "After starting the agent, try mounting again."
                )
            else:
                error_msg = (
                    "\n" + "=" * 70 + "\n"
                    "GPG AGENT NOT RUNNING\n" + "=" * 70 + "\n\n"
                    "The GPG agent (gpg-agent.exe) is not running.\n"
                    "This is required to communicate with your YubiKey.\n\n"
                    "The script attempted to start it automatically but failed.\n\n"
                    "SOLUTIONS:\n\n"
                    "1. Start Kleopatra (GUI for GPG):\n"
                    "   - Launch Kleopatra from Start Menu\n"
                    "   - This will start the GPG agent automatically\n\n"
                    "2. Or start GPG agent manually:\n"
                    "   gpg-connect-agent /bye\n\n"
                    "3. Or restart your computer\n"
                    "   (GPG agent should start on login)\n\n"
                    "After starting the agent, try mounting again.\n" + "=" * 70
                )
            raise RuntimeError(error_msg)

    # Check 2: YubiKey detected by GPG
    log("GPG agent is running ✓")
    log("Checking for YubiKey...")

    try:
        # Try to list smartcards - this will fail if no YubiKey or agent issues
        # BUG-20251218-007: --no-tty prevents gpg from waiting on TTY input
        result = subprocess.run(
            ["gpg", "--no-tty", "--card-status"],
            capture_output=True,
            text=True,
            timeout=Limits.GPG_CARD_STATUS_TIMEOUT,  # Give it time to prompt for PIN if needed
            encoding="utf-8",
            errors="ignore",  # Ignore decoding errors
        )

        if result.returncode == 0:
            # Check if output contains YubiKey/OpenPGP card info
            output_lower = (result.stdout or "").lower()
            if any(keyword in output_lower for keyword in ["yubikey", "openpgp", "card", "serial"]):
                log("YubiKey detected ✓")
                return
            else:
                # gpg --card-status succeeded but no card detected
                pass
        else:
            # gpg --card-status failed
            stderr_lower = (result.stderr or "").lower()
            if "no reader found" in stderr_lower or "card not present" in stderr_lower:
                pass  # Will be caught below
            elif "operation cancelled" in stderr_lower or "pin" in stderr_lower:
                # This might be expected - card is there but needs PIN
                log("YubiKey detected (PIN required) ✓")
                return
            else:
                # Other error
                pass

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, UnicodeDecodeError, Exception):
        # Command timed out, failed, or had encoding issues - likely GPG agent not ready
        pass

    # If we get here, YubiKey is not detected
    if _GUI_MODE:
        error_msg = (
            "YUBIKEY NOT DETECTED\n\n"
            "Your YubiKey is not detected by GPG.\n"
            "This could be because:\n\n"
            "1. YubiKey is not inserted\n"
            "2. YubiKey driver issues\n"
            "3. GPG agent was restarted after inserting YubiKey\n\n"
            "SOLUTIONS:\n\n"
            "1. Insert your YubiKey if not already inserted\n\n"
            "2. Restart Kleopatra or GPG agent:\n"
            "   - Close Kleopatra completely\n"
            "   - Re-insert YubiKey\n"
            "   - Re-open Kleopatra\n\n"
            "3. Or restart GPG agent:\n"
            "   gpg-connect-agent killagent /bye\n"
            "   gpg-connect-agent /bye\n\n"
            "4. Check YubiKey with GPG directly:\n"
            "   gpg --card-status\n\n"
            "After fixing the issue, try mounting again."
        )
    else:
        error_msg = (
            "\n" + "=" * 70 + "\n"
            "YUBIKEY NOT DETECTED\n" + "=" * 70 + "\n\n"
            "Your YubiKey is not detected by GPG.\n"
            "This could be because:\n\n"
            "1. YubiKey is not inserted\n"
            "2. YubiKey driver issues\n"
            "3. GPG agent was restarted after inserting YubiKey\n\n"
            "SOLUTIONS:\n\n"
            "1. Insert your YubiKey if not already inserted\n\n"
            "2. Restart Kleopatra or GPG agent:\n"
            "   - Close Kleopatra completely\n"
            "   - Re-insert YubiKey\n"
            "   - Re-open Kleopatra\n\n"
            "3. Or restart GPG agent:\n"
            "   gpg-connect-agent killagent /bye\n"
            "   gpg-connect-agent /bye\n\n"
            "4. Check YubiKey with GPG directly:\n"
            "   gpg --card-status\n\n"
            "After fixing the issue, try mounting again.\n" + "=" * 70
        )
    raise RuntimeError(error_msg)


def load_keyfile(keyfile_path: Path) -> bytes:
    """
    Load keyfile data, decrypting if GPG-encrypted.
    Returns the plaintext keyfile bytes.
    """
    if is_gpg_encrypted(keyfile_path):
        log(f"Decrypting GPG-encrypted keyfile: {keyfile_path}")

        # Create temporary file in RAM-backed directory for security
        ram_temp_dir = get_ram_temp_dir()
        tmp_path = ram_temp_dir / f"smartdrive_keyfile_{os.urandom(8).hex()}.bin"

        try:
            # Decrypt using GPG
            args = [
                "gpg",
                "--decrypt",
                "--yes",  # Overwrite output if exists
                "--output",
                str(tmp_path),
                str(keyfile_path),
            ]
            # Decrypt using GPG
            args = [
                "gpg",
                "--decrypt",
                "--yes",  # Overwrite output if exists
                "--output",
                str(tmp_path),
                str(keyfile_path),
            ]

            log("Insert YubiKey and enter PIN when prompted...")

            # Run GPG with a timeout to prevent hanging
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=Limits.VERACRYPT_MOUNT_TIMEOUT  # 60 second timeout
                )

                if result.returncode != 0:
                    # Clean up temp file securely
                    secure_delete(tmp_path)

                    # Provide helpful error message
                    stderr = result.stderr.lower()
                    if "no secret key" in stderr or "key not found" in stderr:
                        error_msg = (
                            "\n" + "=" * 70 + "\n"
                            "GPG DECRYPTION FAILED: No matching private key\n" + "=" * 70 + "\n\n"
                            "The keyfile is encrypted to a GPG key that's not available.\n\n"
                            "This could mean:\n"
                            "1. Wrong YubiKey inserted (need the one used during setup)\n"
                            "2. YubiKey keys were not properly imported\n"
                            "3. Using a different YubiKey than during setup\n\n"
                            "SOLUTIONS:\n\n"
                            "1. Insert the correct YubiKey\n"
                            "2. Check available GPG keys: gpg --list-secret-keys\n"
                            "3. If this is a backup YubiKey, ensure it has the right subkeys\n\n"
                            "For help with key management, see the setup documentation.\n" + "=" * 70
                        )
                    elif "bad passphrase" in stderr or "pin" in stderr:
                        error_msg = (
                            "\n" + "=" * 70 + "\n"
                            "GPG DECRYPTION FAILED: Incorrect PIN\n" + "=" * 70 + "\n\n"
                            "The YubiKey PIN you entered was incorrect.\n\n"
                            "Note: YubiKeys have a limited number of PIN attempts\n"
                            "(usually 3) before locking. If locked, you may need\n"
                            "to reset the PIN using the PUK or factory reset.\n\n"
                            "Try again with the correct PIN.\n" + "=" * 70
                        )
                    elif "card not present" in stderr or "no reader" in stderr:
                        error_msg = (
                            "\n" + "=" * 70 + "\n"
                            "GPG DECRYPTION FAILED: YubiKey not detected\n" + "=" * 70 + "\n\n"
                            "Your YubiKey is not detected during decryption.\n\n"
                            "This could happen if:\n"
                            "1. YubiKey was removed during decryption\n"
                            "2. YubiKey connection was interrupted\n"
                            "3. GPG agent lost connection to the YubiKey\n\n"
                            "SOLUTIONS:\n\n"
                            "1. Ensure YubiKey remains inserted\n"
                            "2. Try restarting Kleopatra or the GPG agent\n"
                            "3. Re-run: gpg-connect-agent /bye\n\n"
                            "Then try mounting again.\n" + "=" * 70
                        )
                    else:
                        error_msg = (
                            f"GPG decryption failed: {result.stderr}\n"
                            f"Exit code: {result.returncode}\n\n"
                            "Check that your YubiKey is properly configured and inserted."
                        )

                    raise RuntimeError(error_msg)

            except subprocess.TimeoutExpired:
                # Clean up temp file securely
                secure_delete(tmp_path)

                error_msg = (
                    "\n" + "=" * 70 + "\n"
                    "GPG DECRYPTION TIMED OUT\n" + "=" * 70 + "\n\n"
                    "The GPG decryption process timed out, likely because:\n\n"
                    "1. You cancelled the operation (Ctrl+C)\n"
                    "2. GPG is waiting for PIN input but not prompting properly\n"
                    "3. GPG agent is not running or unresponsive\n\n"
                    "SOLUTIONS:\n\n"
                    "1. Ensure Kleopatra is running\n"
                    "2. Try: gpg-connect-agent /bye\n"
                    "3. Check YubiKey status: gpg --card-status\n\n"
                    "Then try mounting again.\n" + "=" * 70
                )
                raise RuntimeError(error_msg)

            # Read decrypted data
            with open(tmp_path, "rb") as f:
                data = f.read()

            # Clean up temp file securely
            secure_delete(tmp_path)

            log(f"✓ Keyfile decrypted successfully ({len(data)} bytes)")
            return data

        except Exception as e:
            # Clean up temp file securely
            secure_delete(tmp_path)
            raise
    else:
        # Plain keyfile - just read it
        log(f"Loading plain keyfile: {keyfile_path}")
        try:
            with open(keyfile_path, "rb") as f:
                data = f.read()
            log(f"✓ Keyfile loaded ({len(data)} bytes)")
            return data
        except Exception as e:
            raise RuntimeError(f"Failed to read keyfile {keyfile_path}: {e}")


def ensure_dependencies(script_root: Path, cfg: dict, keyfile_path: Path | None) -> Path | None:
    """Check that required tools are available. Return VeraCrypt path on Windows."""
    # GPG only needed if we have a GPG-encrypted keyfile
    if keyfile_path and is_gpg_encrypted(keyfile_path):
        if not have("gpg"):
            raise RuntimeError("gpg not found in PATH. Please install GnuPG/Gpg4win.")

        # Check GPG agent and YubiKey availability
        check_gpg_yubikey_readiness()

    system = platform.system().lower()
    if "windows" in system:
        vc_path = find_veracrypt_windows(script_root, cfg)
        return vc_path
    else:
        if not have("veracrypt"):
            raise RuntimeError("veracrypt not found in PATH. Please install VeraCrypt.")
        return None


def create_temp_keyfile_secure(keyfile_data: bytes) -> Path:
    """
    Create a temporary keyfile, preferably in RAM-based filesystem.
    On Linux: tries /dev/shm (RAM-only)
    On Windows: uses regular temp with best-effort security
    Returns path to temp keyfile.
    """
    if os.name == "nt":
        # Windows: no native ramdisk, use regular temp
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="sd_key_", suffix=".bin")
        tmp = Path(tmp_path)

        try:
            # Write keyfile data
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(keyfile_data)
                f.flush()
                os.fsync(f.fileno())

            log(f"✓ Keyfile created in temp: {tmp.name}")
            return tmp
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except:
                pass
            raise
    else:
        # Unix: prefer RAM-based filesystem
        ramdisk_paths = [
            Path("/dev/shm"),  # Linux tmpfs (RAM-based)
            Path("/tmp"),  # Fallback
        ]

        for ramdisk in ramdisk_paths:
            if ramdisk.exists() and ramdisk.is_dir():
                try:
                    tmp_fd, tmp_path = tempfile.mkstemp(prefix="sd_key_", suffix=".bin", dir=str(ramdisk))
                    tmp = Path(tmp_path)

                    # Set restrictive permissions immediately (before writing)
                    os.chmod(tmp, 0o600)  # rw------- (owner only)

                    with os.fdopen(tmp_fd, "wb") as f:
                        f.write(keyfile_data)
                        f.flush()
                        os.fsync(f.fileno())

                    if ramdisk == Path("/dev/shm"):
                        log(f"✓ Keyfile created in RAM: {tmp.name}")
                    else:
                        log(f"✓ Keyfile created in temp: {tmp.name}")
                    return tmp
                except Exception:
                    continue

        raise RuntimeError("Failed to create temporary keyfile")


def cleanup_temp_keyfile(path: Path) -> None:
    """Secure cleanup: overwrite keyfile contents before deletion."""
    if not path or not path.exists():
        return

    try:
        # Get file size
        file_size = path.stat().st_size

        if file_size > 0:
            # Overwrite file contents multiple times
            with path.open("r+b") as f:
                # Pass 1: Overwrite with zeros
                f.write(b"\x00" * file_size)
                f.flush()
                os.fsync(f.fileno())

                # Pass 2: Overwrite with random data
                f.seek(0)
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())

        # Use shred if available (Unix)
        if os.name != "nt" and have("shred"):
            subprocess.run(["shred", "-u", "-n", "1", str(path)], check=False, capture_output=True)
            log("✓ Keyfile securely erased (shred)")
        else:
            # Delete the file
            path.unlink(missing_ok=True)
            log("✓ Keyfile cleaned up")

    except Exception as e:
        # Best effort - don't fail the whole operation
        log(f"⚠ Warning: Keyfile cleanup may be incomplete: {e}")
        try:
            path.unlink(missing_ok=True)
        except:
            pass


def validate_volume_path_windows(volume_path: str) -> None:
    """Validate that volume path is not a critical system location."""
    dangerous_patterns = [
        ("C:", "System drive C:"),
        ("C:\\", "System drive C:"),
        ("\\\\DEVICE\\\\HARDDISK0", "Harddisk0 (usually system disk)"),
    ]

    # Normalize path for comparison
    normalized = (volume_path or "").strip().upper().replace("\\\\", "\\")

    # Check for dangerous patterns
    for pattern, description in dangerous_patterns:
        pattern_normalized = pattern.upper().replace("\\\\", "\\")
        if normalized.startswith(pattern_normalized):
            raise RuntimeError(
                f"\n{'='*60}\n"
                f"SAFETY CHECK FAILED!\n"
                f"{'='*60}\n"
                f"Volume path appears to target: {description}\n"
                f"Configured path: {volume_path}\n\n"
                f"This could destroy your operating system!\n\n"
                f"External drives are usually Harddisk1 or higher.\n"
                f"Use 'Get-Disk' in PowerShell to identify your external drive.\n"
                f"Look for disks marked as 'USB' or 'Removable'.\n"
                f"{'='*60}"
            )

    log(f"✓ Safety check passed for: {volume_path}")


def validate_volume_path_unix(volume_path: str) -> None:
    """Validate that volume path is not a critical system location."""
    dangerous_patterns = [
        ("/dev/sda", "First disk (usually system disk)"),
        ("/dev/nvme0n1", "First NVMe drive (usually system disk)"),
        ("/dev/vda", "First virtual disk (usually system disk)"),
        ("/", "Root filesystem"),
        ("/boot", "Boot partition"),
        ("/home", "Home directory"),
        ("/usr", "System directory"),
        ("/var", "System directory"),
    ]

    normalized = (volume_path or "").strip().lower()

    # Check for exact matches or subdirectories/partitions
    for pattern, description in dangerous_patterns:
        if normalized == pattern or normalized.startswith(pattern + "p") or normalized.startswith(pattern + "/"):
            raise RuntimeError(
                f"\n{'='*60}\n"
                f"SAFETY CHECK FAILED!\n"
                f"{'='*60}\n"
                f"Volume path appears to target: {description}\n"
                f"Configured path: {volume_path}\n\n"
                f"This could destroy your operating system or data!\n\n"
                f"External drives are usually /dev/sdb or higher.\n"
                f"Use 'lsblk' to identify your external drive.\n"
                f"Look for removable or USB devices.\n"
                f"{'='*60}"
            )

    log(f"✓ Safety check passed for: {volume_path}")


def resolve_volume_path_windows(config_volume_path: str, script_path: Path) -> str:
    """
    Resolve the volume path for mounting on Windows.

    Key insight: The mount script runs from the USB drive's launcher partition.
    The VeraCrypt volume is partition 2 of the SAME disk.
    Device paths like \\Device\\Harddisk1\\Partition2 change based on USB port.

    Resolution strategy:
    1. Detect which disk the script is running from (by drive letter)
    2. Find partition 2 of that same disk
    3. Return a usable path for VeraCrypt CLI

    Args:
        config_volume_path: The path from config (may be device path or special marker)
        script_path: Path to the mount.py script

    Returns:
        Resolved volume path usable by VeraCrypt CLI
    """
    # If config has a simple drive letter like "E:", just validate and return
    if len(config_volume_path) <= 3 and config_volume_path[0].isalpha():
        letter = config_volume_path.rstrip(":").upper()
        if Path(f"{letter}:\\").exists():
            log(f"Volume path is already a drive letter: {letter}:")
            return f"{letter}:"

    # Auto-resolve: Find the payload partition on the same disk as the script
    script_drive = script_path.drive  # e.g., "F:"
    if not script_drive:
        log(f"Cannot determine script drive from: {script_path}")
        return config_volume_path  # Fallback to config value

    script_letter = script_drive.rstrip(":").upper()
    log(f"Script running from drive {script_letter}:, auto-resolving volume...")

    try:
        # Find which disk the script's drive letter is on
        ps_script = f"""
        $partition = Get-Partition -DriveLetter '{script_letter}' -ErrorAction Stop
        $diskNumber = $partition.DiskNumber
        
        # Find partition 2 on the same disk (the VeraCrypt payload partition)
        $payloadPartition = Get-Partition -DiskNumber $diskNumber -PartitionNumber 2 -ErrorAction SilentlyContinue
        
        if ($payloadPartition) {{
            # Check if it has a drive letter
            if ($payloadPartition.DriveLetter) {{
                Write-Output "LETTER:$($payloadPartition.DriveLetter)"
            }} else {{
                # Get Volume GUID as fallback
                $volume = Get-Volume -Partition $payloadPartition -ErrorAction SilentlyContinue
                if ($volume -and $volume.UniqueId) {{
                    Write-Output "GUID:$($volume.UniqueId)"
                }} else {{
                    # Use device path format VeraCrypt understands
                    Write-Output "DEVICE:\\Device\\Harddisk$($diskNumber)\\Partition2"
                }}
            }}
        }} else {{
            Write-Output "ERROR:No partition 2 found on disk $diskNumber"
        }}
        """

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=15
        )

        output = result.stdout.strip()
        if output.startswith("LETTER:"):
            resolved = output.replace("LETTER:", "").strip() + ":"
            log(f"✓ Resolved to drive letter: {resolved}")
            return resolved
        elif output.startswith("GUID:"):
            resolved = output.replace("GUID:", "").strip()
            log(f"✓ Resolved to volume GUID: {resolved[:30]}...")
            return resolved
        elif output.startswith("DEVICE:"):
            resolved = output.replace("DEVICE:", "").strip()
            log(f"✓ Resolved to device path: {resolved}")
            return resolved
        elif output.startswith("ERROR:"):
            error_msg = output.replace("ERROR:", "").strip()
            log(f"⚠ Resolution error: {error_msg}")
            log(f"Falling back to config value: {config_volume_path}")
            return config_volume_path
        else:
            log(f"⚠ Unexpected PowerShell output: {output}")
            return config_volume_path

    except subprocess.TimeoutExpired:
        log(f"⚠ Volume resolution timed out, using config value: {config_volume_path}")
        return config_volume_path
    except Exception as e:
        log(f"⚠ Volume resolution failed ({e}), using config value: {config_volume_path}")
        return config_volume_path


def mount_veracrypt_windows(vc_exe: Path, cfg: dict, tmp_keys: list[Path] | None, password: str) -> None:
    cfg_win = cfg.get(ConfigKeys.WINDOWS) or {}
    volume_path = (cfg_win.get(ConfigKeys.VOLUME_PATH) or "").strip()
    if not volume_path:
        raise RuntimeError("windows.volume_path is missing/empty in config.json")

    # Auto-resolve volume path based on script location
    # This handles USB drives moving between ports (device path changes)
    script_path = Path(__file__).resolve()
    volume_path = resolve_volume_path_windows(volume_path, script_path)

    # Safety check: prevent mounting system drives
    validate_volume_path_windows(volume_path)

    mount_letter = (cfg_win.get(ConfigKeys.MOUNT_LETTER) or "").strip().upper() or "V"

    # Check if drive letter is already in use
    if Path(f"{mount_letter}:\\").exists():
        raise RuntimeError(
            f"Drive letter {mount_letter}: is already in use.\n"
            f"Please choose a different letter in config.json or unmount the existing drive."
        )

    log(f"Mounting VeraCrypt volume on Windows as drive {mount_letter}:")
    log(f"  Volume path: {volume_path}")
    if tmp_keys and len(tmp_keys) > 0:
        log(f"  Using keyfiles: {len(tmp_keys)}")
    else:
        log(f"  Using keyfile: no (password only)")

    args = [
        str(vc_exe),
        "/volume",
        volume_path,
        "/letter",
        mount_letter,
        "/password",
        password if password is not None else "",
        "/quit",
        "/silent",
    ]

    # Add keyfiles if provided
    if tmp_keys and len(tmp_keys) > 0:
        for tmp_key in tmp_keys:
            args.extend(["/keyfile", str(tmp_key)])

    try:
        # In GUI mode, capture all output to prevent VeraCrypt GUI from opening
        if _GUI_MODE:
            run_cmd(args, check=True, capture_output=True)
        else:
            run_cmd(args, check=True)
        log(f"Mounted successfully as {mount_letter}:")

        # Update drive icon to mounted state
        update_drive_icon(True)

        # Set custom drive icon on mounted VeraCrypt volume
        try:
            mount_path = f"{mount_letter}:\\"

            # Detect if running from dev environment or deployed drive
            script_path = Path(__file__)
            logo_src = None

            # Priority order for icon resolution (VeraCrypt volume):
            # 1. LOGO_drive.ico (distinct VeraCrypt volume icon)
            # 2. LOGO_mounted.ico (fallback for mounted state)
            # 3. LOGO_main.ico (ultimate fallback)
            # First in .smartdrive/static/, then ROOT/static/

            if "VeraCrypt_Yubikey_2FA" in str(script_path):
                # Dev environment
                dev_root = script_path.parent.parent
                # Try .smartdrive/static/ first
                candidates = [
                    dev_root / ".smartdrive" / "static" / "LOGO_drive.ico",
                    dev_root / "static" / "LOGO_drive.ico",
                    dev_root / ".smartdrive" / "static" / "LOGO_mounted.ico",
                    dev_root / "static" / "LOGO_mounted.ico",
                    dev_root / ".smartdrive" / "static" / "LOGO_main.ico",
                    dev_root / "static" / "LOGO_main.ico",
                ]
                for candidate in candidates:
                    if candidate.exists():
                        logo_src = candidate
                        break
            else:
                # Deployed: .smartdrive/scripts/mount.py -> .smartdrive -> ROOT
                launcher_root = script_path.parent.parent.parent
                # Try distinct VeraCrypt icons first, then fallbacks
                candidates = [
                    launcher_root / ".smartdrive" / "static" / "LOGO_drive.ico",
                    launcher_root / "static" / "LOGO_drive.ico",
                    launcher_root / ".smartdrive" / "static" / "LOGO_mounted.ico",
                    launcher_root / "static" / "LOGO_mounted.ico",
                    launcher_root / ".smartdrive" / "static" / "LOGO_main.ico",
                    launcher_root / "static" / "LOGO_main.ico",
                ]
                for candidate in candidates:
                    if candidate.exists():
                        logo_src = candidate
                        break

            if not logo_src or not logo_src.exists():
                log("Logo file not found in static folder, skipping icon update")
            else:
                logo_dst = Path(mount_path) / "drive_icon.ico"
                shutil.copy(logo_src, logo_dst)

                desktop_ini = Path(mount_path) / "desktop.ini"
                desktop_content = """[ViewState]
Mode=
Vid=
FolderType=Generic

[.ShellClassInfo]
IconResource=drive_icon.ico,0
"""
                with open(desktop_ini, "w") as f:
                    f.write(desktop_content)

                subprocess.run(["attrib", "+h", "+s", str(desktop_ini)], check=True)

                # Refresh Windows Explorer
                try:
                    subprocess.run(
                        ["ie4uinit.exe", "-show"],
                        check=False,
                        capture_output=True,
                        timeout=Limits.GPG_CARD_STATUS_TIMEOUT,
                    )
                    log("✓ Drive icon updated and refreshed")
                except Exception as e:
                    log(f"⚠ Icon refresh failed: {e}")
                    log("✓ Drive icon updated (restart Explorer to see changes)")

        except (PermissionError, OSError, FileNotFoundError) as e:
            log("⚠ Could not update drive icon (missing logo file or permission issue)")
            # Continue anyway - icon update is cosmetic

    except RuntimeError as e:
        # Build keyfile info for error message
        keyfile_info = "(none - password only)"
        if tmp_keys and len(tmp_keys) > 0:
            keyfile_info = ", ".join(str(k) for k in tmp_keys)

        # Provide helpful troubleshooting
        error_msg = (
            f"VeraCrypt mount failed.\n\n"
            f"Common causes:\n"
            f"1. Wrong volume path: {volume_path}\n"
            f"   Volume paths can change when you plug the drive into different USB ports!\n"
            f"   Try these alternatives in config.json:\n"
            f"   - Raw disk: \\\\.\\PhysicalDrive1\n"
            f"   - Partition: \\\\.\\Harddisk1Partition2 (no backslash between)\n"
            f"   - Drive letter: E:\\\\\n"
            f"   - Container file: E:\\\\vault.hc\n\n"
            f"2. Wrong password or keyfile mismatch\n"
            f"   - Verify password is correct\n"
            f"   - Ensure volume was created with this exact keyfile\n\n"
            f"3. Partition is not a VeraCrypt volume\n"
            f"   - Create volume first using VeraCrypt GUI\n\n"
            f"4. Check your device with PowerShell:\n"
            f"   Get-Disk | Format-Table\n"
            f"   Get-Partition | Format-Table\n\n"
            f"5. Try mounting manually in VeraCrypt GUI:\n"
            f"   - Open VeraCrypt GUI\n"
            f"   - Select volume: {volume_path}\n"
            f"   - Mount letter: {mount_letter}\n"
            f"   - Keyfile: {keyfile_info}\n"
            f"   - Enter password when prompted\n"
            f"   - This will show the exact error if the path is wrong\n\n"
            f"Try mounting manually to see exact error:\n"
            f'  "{vc_exe}" /v {volume_path} /l {mount_letter}'
        )
        raise RuntimeError(error_msg) from e


def mount_veracrypt_unix(cfg: dict, tmp_keys: list[Path] | None, password: str) -> None:
    cfg_unix = cfg.get(ConfigKeys.UNIX) or {}
    volume_path = (cfg_unix.get(ConfigKeys.VOLUME_PATH) or "").strip()
    if not volume_path:
        raise RuntimeError("unix.volume_path is missing/empty in config.json")

    # Safety check: prevent mounting system drives
    validate_volume_path_unix(volume_path)

    mount_point_raw = (cfg_unix.get(ConfigKeys.MOUNT_POINT) or "").strip() or "~/veradrive"
    mount_point = Path(os.path.expanduser(mount_point_raw))
    mount_point.mkdir(parents=True, exist_ok=True)

    log(f"Mounting VeraCrypt volume on Unix at {mount_point}:")
    base_cmd = [
        "veracrypt",
        "--text",
        "--non-interactive",
        "--mount",
        volume_path,
        str(mount_point),
    ]

    # Add keyfiles if provided
    if tmp_keys and len(tmp_keys) > 0:
        for tmp_key in tmp_keys:
            base_cmd.extend(["--keyfiles", str(tmp_key)])

    if password:
        # Avoid putting password on command line; feed via stdin
        base_cmd.append("--stdin")
        proc = subprocess.Popen(
            base_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input=password + "\n")
        if proc.returncode != 0:
            raise RuntimeError(
                f"VeraCrypt mount failed (exit {proc.returncode}).\n" f"stdout: {stdout}\n" f"stderr: {stderr}"
            )
    else:
        run_cmd(base_cmd, check=True)

    log(f"Mounted successfully at {mount_point}")


def check_and_offer_dependency_installation(script_root: Path, cfg: dict, keyfile_path: Path | None) -> None:
    """
    Check for required dependencies and offer installation if missing.
    This provides a user-friendly way to install missing tools.
    """
    missing_tools = []
    recommendations = []

    # Check Python (should always be available since we're running)
    if not have("python") and not have("python3"):
        missing_tools.append("Python")
        recommendations.append("Python is required but missing. Please install Python 3.7+ from python.org")

    # Check VeraCrypt
    system = platform.system().lower()
    if "windows" in system:
        vc_found = False
        try:
            find_veracrypt_windows(script_root, cfg)
            vc_found = True
        except RuntimeError:
            pass

        if not vc_found:
            missing_tools.append("VeraCrypt")
            recommendations.append(
                "VeraCrypt is required for encryption.\n"
                "  Download: https://www.veracrypt.fr/en/Downloads.html\n"
                "  Install the portable or full version."
            )
    else:
        if not have("veracrypt"):
            missing_tools.append("VeraCrypt")
            recommendations.append(
                "VeraCrypt is required for encryption.\n"
                "  Ubuntu/Debian: sudo apt install veracrypt\n"
                "  Fedora: sudo dnf install veracrypt\n"
                "  macOS: brew install --cask veracrypt"
            )

    # Check GPG if needed
    needs_gpg = (keyfile_path and is_gpg_encrypted(keyfile_path)) or cfg.get(
        ConfigKeys.MODE
    ) == SecurityMode.GPG_PW_ONLY.value
    if needs_gpg:
        if not have("gpg"):
            missing_tools.append("GnuPG")
            if system == "windows":
                recommendations.append(
                    "GnuPG (Gpg4win) is required for YubiKey support.\n"
                    "  Download: https://gpg4win.org/download.html\n"
                    "  Install Gpg4win, then start Kleopatra to initialize."
                )
            else:
                recommendations.append(
                    "GnuPG is required for YubiKey support.\n"
                    "  Ubuntu/Debian: sudo apt install gnupg\n"
                    "  Fedora: sudo dnf install gnupg\n"
                    "  macOS: brew install gnupg"
                )

    # If any tools are missing, show installation guide
    if missing_tools:
        print("\n" + "=" * 70)
        print("MISSING DEPENDENCIES DETECTED")
        print("=" * 70)
        print(f"\nThe following required tools are not installed: {', '.join(missing_tools)}")
        print("\nINSTALLATION INSTRUCTIONS:")
        print("-" * 40)

        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. {rec}")

        print(f"\n{'='*70}")
        print("After installing the missing tools, run this script again.")
        print("=" * 70)

        # Ask if user wants to continue anyway (might work if tools are in non-standard locations)
        try:
            choice = input("\nTry to continue anyway? [y/N]: ").strip().lower()
            if choice != "y":
                print("Exiting. Please install the required tools and try again.")
                sys.exit(1)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(1)

    # If GPG is needed, give a quick status check
    needs_gpg = (keyfile_path and is_gpg_encrypted(keyfile_path)) or cfg.get(
        ConfigKeys.MODE
    ) == SecurityMode.GPG_PW_ONLY.value
    if needs_gpg and have("gpg"):
        print("\nNote: YubiKey mode detected.")
        print("Make sure your YubiKey is inserted and Kleopatra is running.")
        print("If mounting fails, the script will provide specific guidance.")


def main(
    password: str = None, keyfile_paths: list[str] = None, gui_mode: bool = False, config_path: Path = None
) -> None:
    # Set global GUI mode
    set_gui_mode(gui_mode)

    # Determine script_root for config loading
    # Priority: explicit --config > inferred from __file__
    if config_path:
        # Config is at .smartdrive/config.json, so script_root should be .smartdrive/
        script_root = config_path.parent
        log(f"Using explicit config: {config_path}")
    else:
        # Fallback: infer from script location
        # If in .smartdrive/scripts/, config is at .smartdrive/config.json
        script_dir = Path(__file__).resolve().parent
        if script_dir.parent.name == ".smartdrive":
            script_root = script_dir.parent  # .smartdrive/
        else:
            # Development or legacy - check both locations
            if (script_dir.parent / ".smartdrive" / "config.json").exists():
                script_root = script_dir.parent / ".smartdrive"
            else:
                script_root = script_dir  # Legacy: scripts/config.json

    cfg = load_or_init_config(script_root)

    # BUG-20251219-006: Enforce post-recovery rekey policy
    # Check if rekey is required after a recovery event
    post_recovery = cfg.get("post_recovery", {})
    if post_recovery.get("rekey_required") and not post_recovery.get("rekey_completed"):
        recovery_time = post_recovery.get("recovery_completed_at", "unknown")
        print("\n" + "=" * 70)
        print("  ⚠️  POST-RECOVERY REKEY REQUIRED")
        print("=" * 70)
        print(f"\n  A recovery was performed at: {recovery_time}")
        print("  You MUST change your credentials before mounting.")
        print("\n  This is a SECURITY REQUIREMENT:")
        print("    - Your recovery phrase was exposed during recovery")
        print("    - Anyone with that phrase could access this volume")
        print("    - Run 'python rekey.py' to change credentials")
        print("\n" + "-" * 70)

        # Check policy mode (configurable)
        policy = cfg.get("post_recovery_policy", "mandatory_rekey")

        if policy == "mandatory_rekey":
            print("  BLOCKED: Mount is not allowed until rekey completes.")
            print("-" * 70 + "\n")
            if gui_mode:
                raise RuntimeError("Post-recovery rekey required before mount")
            sys.exit(1)
        elif policy == "warn_grace":
            # Allow mount with warning
            print("  WARNING: Proceeding without rekey is a security risk!")
            print("-" * 70)
            if not gui_mode:
                confirm = input("\n  Type 'INSECURE' to mount anyway: ").strip()
                if confirm != "INSECURE":
                    print("  Mount aborted.")
                    sys.exit(1)
            log("WARNING: Mounting with pending rekey - SECURITY RISK")

    # Check for required dependencies and offer installation
    resolved_keyfile = resolve_encrypted_keyfile(script_root, cfg)
    if keyfile_paths and len(keyfile_paths) > 0:
        # Use first keyfile for dependency resolution, but we'll use all later
        resolved_keyfile = Path(keyfile_paths[0])
    seed_path = resolve_encrypted_seed(script_root, cfg)
    check_and_offer_dependency_installation(script_root, cfg, resolved_keyfile)

    try:
        vc_path_windows = ensure_dependencies(script_root, cfg, resolved_keyfile)
    except RuntimeError as e:
        if gui_mode:
            raise e  # Re-raise for GUI to handle
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Determine mount mode - prioritize config setting over auto-detection
    mode = cfg.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

    # Convert mode string to SecurityMode enum for convenient property access
    try:
        security_mode = SecurityMode.from_config(mode)
    except ValueError:
        # Fallback to PW_ONLY if invalid mode
        security_mode = SecurityMode.PW_ONLY

    # Determine if keyfile should be used based on mode
    use_keyfile = security_mode.requires_keyfile

    if mode == SecurityMode.GPG_PW_ONLY.value:
        log("Mode: GPG password-only (YubiKey + PIN only)")
    elif mode == SecurityMode.PW_ONLY.value:
        log("Mode: Password-only (no keyfile configured)")
    elif mode == SecurityMode.PW_KEYFILE.value and resolved_keyfile and not is_gpg_encrypted(resolved_keyfile):
        log("Mode: Plain keyfile")
    elif mode == SecurityMode.PW_GPG_KEYFILE.value and resolved_keyfile and is_gpg_encrypted(resolved_keyfile):
        log("Mode: GPG-encrypted keyfile (YubiKey/GPG key required)")
    else:
        # Fallback auto-detection for backward compatibility
        if resolved_keyfile is None:
            log("Mode: Password-only (no keyfile configured)")
        elif is_gpg_encrypted(resolved_keyfile):
            log("Mode: GPG-encrypted keyfile (YubiKey/GPG key required)")
        else:
            log("Mode: Plain keyfile")

    # Get VeraCrypt password
    if mode == SecurityMode.GPG_PW_ONLY.value:
        # Derive password from GPG-encrypted seed
        if not seed_path:
            raise RuntimeError("GPG password-only mode requires encrypted seed")

        import base64

        from crypto_utils import derive_veracrypt_password, gpg_decrypt_bytes

        log("Decrypting seed with GPG...")
        seed = gpg_decrypt_bytes(seed_path)

        salt_b64 = cfg.get("salt_b64", "")
        if not salt_b64:
            raise RuntimeError("Missing salt in config for GPG password-only mode")
        salt = base64.b64decode(salt_b64)

        password = derive_veracrypt_password(seed, salt)
        log("✓ Password derived from seed")

        # Wipe seed from memory
        seed = bytearray(len(seed))
        for i in range(len(seed)):
            seed[i] = 0

    elif password is None:
        # Interactive mode
        try:
            password = getpass("Enter VeraCrypt password (leave empty if none): ")
        except (KeyboardInterrupt, EOFError):
            if gui_mode:
                raise KeyboardInterrupt("Password input cancelled")
            print("\nAborted by user.", file=sys.stderr)
            sys.exit(1)
    else:
        # Non-interactive mode (GUI provided password)
        log("Using provided password (non-interactive mode)")

    keyfile_data_list: list[bytes] = []
    tmp_keys: list[Path] = []

    try:
        # Handle keyfiles if provided via command line
        if keyfile_paths and len(keyfile_paths) > 0:
            for keyfile_path in keyfile_paths:
                keyfile_path_obj = Path(keyfile_path)
                if keyfile_path_obj.exists():
                    # Load keyfile (decrypt if GPG-encrypted, or read plain)
                    keyfile_data: bytes = load_keyfile(keyfile_path_obj)
                    keyfile_data_list.append(keyfile_data)

                    # Create temporary file for each keyfile
                    tmp_key: Path = create_temp_keyfile_secure(keyfile_data)
                    tmp_keys.append(tmp_key)
                else:
                    log(f"Warning: Keyfile not found: {keyfile_path}")
        # Handle keyfile if configured and mode requires it (legacy config-based)
        elif use_keyfile and resolved_keyfile:
            # Step 1: Load keyfile (decrypt if GPG-encrypted, or read plain)
            keyfile_data: bytes = load_keyfile(resolved_keyfile)
            keyfile_data_list.append(keyfile_data)

            # Step 2: Create temporary file (preferably in RAM)
            tmp_key: Path = create_temp_keyfile_secure(keyfile_data)
            tmp_keys.append(tmp_key)

        # Step 4: Mount the volume
        system = platform.system().lower()
        if "windows" in system:
            if vc_path_windows is None:
                raise RuntimeError("Internal error: VeraCrypt path not resolved on Windows.")
            mount_veracrypt_windows(vc_path_windows, cfg, tmp_keys if tmp_keys else None, password)
        else:
            mount_veracrypt_unix(cfg, tmp_keys if tmp_keys else None, password)

    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Cleanup in reverse order
        for tmp_key in tmp_keys:
            cleanup_temp_keyfile(tmp_key)
        for keyfile_data in keyfile_data_list:
            if keyfile_data:
                keyfile_data = b"\x00" * len(keyfile_data)
                del keyfile_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mount SmartDrive encrypted volume")
    parser.add_argument("--password", "-p", help="VeraCrypt password (for non-interactive mode)")
    parser.add_argument("--keyfile", "-k", action="append", default=[], help="Path to keyfile (can be repeated)")
    parser.add_argument("--gui", action="store_true", help="GUI mode (suppress interactive prompts)")
    parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", help="Absolute path to config.json (propagated from caller)"
    )

    args = parser.parse_args()

    # If --config provided, change script_root to config's parent directory
    # This enables "run from anywhere" - config path is the source of truth
    global_config_path = None
    if args.config:
        global_config_path = Path(args.config).resolve()
        if not global_config_path.exists():
            print(f"[ERROR] Config file not found: {global_config_path}", file=sys.stderr)
            sys.exit(1)

    try:
        main(password=args.password, keyfile_paths=args.keyfile, gui_mode=args.gui, config_path=global_config_path)
    except KeyboardInterrupt:
        print("\nAborted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        if args.gui:
            raise  # Re-raise for GUI to handle
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
