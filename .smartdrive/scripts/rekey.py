#!/usr/bin/env python3
"""
SmartDrive rekey script

Change VeraCrypt volume password, keyfile, and/or security mode:
- Rotate keyfile when YubiKey is lost/compromised
- Change password
- Add keyfile to password-only volume
- Replace keyfile for different YubiKeys
- Change security mode (pw_only, pw_keyfile, pw_gpg_keyfile, gpg_pw_only)

This script:
1. Decrypts old keyfile using current YubiKey (if applicable)
2. Prompts for YubiKey(s) to encrypt the NEW keyfile to
3. Generates new random keyfile (optional)
4. Encrypts new keyfile to specified YubiKeys
5. Opens VeraCrypt GUI for manual credential change
6. VERIFIES new credentials work by test-mounting
7. Only if verified: replaces the encrypted keyfile
8. Backs up old encrypted keyfile as .old

Safety features:
- Automatic verification before committing changes
- Separate YubiKey selection for old vs new keyfile
- Rollback if verification fails
- Secure cleanup of temporary plaintext keyfiles

Dependencies (runtime):
- Python 3
- gpg in PATH
- VeraCrypt:
    - Windows: VeraCrypt.exe
    - Linux/macOS: 'veracrypt' in PATH
"""

import base64
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
from getpass import getpass
from pathlib import Path
from typing import TYPE_CHECKING

# ===========================================================================
# Core module imports (single source of truth)
# ===========================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/rekey.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/rekey.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.config import write_config_atomic
from core.constants import Branding, ConfigKeys, CryptoParams, FileNames, UserInputs
from core.limits import Limits
from core.modes import SECURITY_MODE_DISPLAY, SecurityMode
from core.paths import Paths
from core.version import VERSION

# SecretProvider for mode-aware credential access
try:
    from core.secrets import (
        SecretAccessError,
        SecretProvider,
        YubiKeyRequiredError,
        create_command_loop_prompt,
        run_command_loop,
    )

    _SECRET_PROVIDER_AVAILABLE = True
except ImportError:
    _SECRET_PROVIDER_AVAILABLE = False
    if TYPE_CHECKING:
        from core.secrets import SecretProvider
    else:
        SecretProvider = None  # type: ignore


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


def log(msg: str) -> None:
    print(f"[INFO] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[WARNING] {msg}")


def print_banner():
    """Print welcome banner."""
    print("\n" + "=" * 70)
    print("  +=============================================================+")
    print(f"  |           {Branding.PRODUCT_NAME} Credential Rotation v2.0                 |")
    print("  |   Change Password / Rotate YubiKey / Change Security Mode   |")
    print("  +=============================================================+")
    print("=" * 70)


def print_phase(num: int, total: int, title: str):
    """Print phase header."""
    print(f"\n{'-'*70}")
    print(f"  PHASE {num}/{total}: {title}")
    print(f"{'-'*70}\n")


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def verify_new_credentials_windows(vc_exe: Path, volume_path: str, password: str, keyfile: Path | None) -> bool:
    """Verify new credentials work by attempting a test mount.

    Returns:
        True if credentials work, False otherwise.
    """
    log("Verifying new credentials by test mounting...")

    # Find an unused drive letter for test mount
    import string

    used_drives = {
        d.split(":")[0] for d in subprocess.check_output("wmic logicaldisk get caption", text=True).split() if ":" in d
    }
    available_drive = None
    for letter in string.ascii_uppercase[::-1]:  # Start from Z and work backwards
        if letter not in used_drives:
            available_drive = f"{letter}:"
            break

    if not available_drive:
        error("No available drive letters for test mount")
        return False

    args = [
        str(vc_exe),
        "/volume",
        volume_path,
        "/letter",
        available_drive[0],
        "/password",
        password,
        "/quit",
        "/silent",
    ]

    if keyfile:
        args.extend(["/keyfile", str(keyfile)])

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=Limits.SUBPROCESS_DEFAULT_TIMEOUT)

        if result.returncode == 0:
            # Mount succeeded, now dismount
            log(f"✓ Test mount successful on {available_drive}")
            subprocess.run(
                [str(vc_exe), "/dismount", available_drive[0], "/quit", "/silent"],
                capture_output=True,
                timeout=Limits.GPG_CARD_STATUS_TIMEOUT,
            )
            return True
        else:
            error(f"Test mount failed: credentials don't work")
            return False
    except subprocess.TimeoutExpired:
        error("Test mount timed out")
        return False
    except Exception as e:
        error(f"Test mount error: {e}")
        return False


def verify_new_credentials_unix(volume_path: str, password: str, keyfile: Path | None) -> bool:
    """Verify new credentials work by attempting a test mount.

    Returns:
        True if credentials work, False otherwise.
    """
    log("Verifying new credentials by test mounting...")

    # Create temporary mount point
    import tempfile

    mount_point = Path(tempfile.mkdtemp(prefix="sd_verify_"))

    args = [
        "veracrypt",
        "--text",
        "--non-interactive",
        "--mount",
        volume_path,
        str(mount_point),
        "--password",
        password,
    ]

    if keyfile:
        args.extend(["--keyfiles", str(keyfile)])

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=Limits.SUBPROCESS_DEFAULT_TIMEOUT)

        if result.returncode == 0:
            # Mount succeeded, now dismount
            log(f"✓ Test mount successful at {mount_point}")
            subprocess.run(
                ["veracrypt", "--text", "--dismount", str(mount_point)],
                capture_output=True,
                timeout=Limits.GPG_CARD_STATUS_TIMEOUT,
            )
            mount_point.rmdir()
            return True
        else:
            error(f"Test mount failed: credentials don't work")
            mount_point.rmdir()
            return False
    except subprocess.TimeoutExpired:
        error("Test mount timed out")
        try:
            mount_point.rmdir()
        except:
            pass
        return False
    except Exception as e:
        error(f"Test mount error: {e}")
        try:
            mount_point.rmdir()
        except:
            pass
        return False


def run_cmd(args, *, check=True, capture_output=False, text=True, input_text=None):
    """Run a subprocess command with basic error handling."""
    try:
        result = subprocess.run(
            args,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input_text,
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Command failed with exit code {e.returncode}: {' '.join(args)}\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}"
        )


def get_config_path() -> Path:
    """
    Get the path to config.json using SSOT resolution.

    Returns:
        Path to config.json
    """
    script_dir = Path(__file__).resolve().parent

    # Try deployed location first: .smartdrive/config.json
    if script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
        return script_dir.parent / FileNames.CONFIG_JSON
    elif (script_dir.parent / Paths.SMARTDRIVE_DIR_NAME / FileNames.CONFIG_JSON).exists():
        return script_dir.parent / Paths.SMARTDRIVE_DIR_NAME / FileNames.CONFIG_JSON
    else:
        # Legacy fallback
        return Path(FileNames.CONFIG_JSON)


def load_config() -> dict:
    """
    Load config.json using SSOT path resolution.

    Searches for config in order:
    1. .smartdrive/config.json relative to script location (deployed mode)
    2. Current working directory (legacy fallback)

    Returns:
        Loaded config dict

    Raises:
        RuntimeError: If config not found or cannot be loaded
    """
    config_path = get_config_path()

    if not config_path.exists():
        # Build helpful error message
        script_dir = Path(__file__).resolve().parent
        searched_paths = []
        if script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
            searched_paths.append(str(script_dir.parent / FileNames.CONFIG_JSON))
        else:
            searched_paths.append(str(script_dir.parent / Paths.SMARTDRIVE_DIR_NAME / FileNames.CONFIG_JSON))
            searched_paths.append(str(Path.cwd() / FileNames.CONFIG_JSON))

        raise RuntimeError(
            f"{FileNames.CONFIG_JSON} not found.\n"
            f"  Searched locations:\n" + "\n".join(f"    - {p}" for p in searched_paths) + "\n"
            f"  Solution: Run this script from the drive root, or place it under\n"
            f"           {Paths.SMARTDRIVE_DIR_NAME}/{Paths.SCRIPTS_SUBDIR}/ on the drive."
        )

    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to read config.json: {e}")


def get_available_fingerprints() -> list[tuple[str, str]]:
    """Retrieve available GPG key fingerprints from the keyring."""
    try:
        result = run_cmd(
            ["gpg", "--list-keys", "--with-colons"],
            check=True,
            capture_output=True,
            text=True,
        )

        fingerprints = []
        current_fpr = None
        current_uid = None

        for line in result.stdout.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr":
                current_fpr = parts[9]
            elif parts[0] == "uid" and current_fpr:
                current_uid = parts[9]
                if current_fpr and current_uid:
                    fingerprints.append((current_fpr, current_uid))
                    current_fpr = None
                    current_uid = None

        return fingerprints
    except Exception:
        return []


def validate_fingerprint(fpr: str) -> str:
    """Validate and normalize a fingerprint string."""
    normalized = fpr.replace(" ", "").upper()

    if len(normalized) != 40:
        raise RuntimeError(f"Invalid fingerprint length: {len(normalized)} characters (expected 40)")

    if not all(c in "0123456789ABCDEF" for c in normalized):
        raise RuntimeError(f"Invalid fingerprint format: must contain only hex characters (0-9, A-F)")

    return normalized


def prompt_for_fingerprints(available_fprs: list[tuple[str, str]]) -> list[str]:
    """Prompt user for one or more YubiKey fingerprints."""
    fingerprints = []

    print("\n" + "=" * 60)
    print("YubiKey Selection for New Keyfile")
    print("=" * 60)
    print("Select YubiKey(s) that should be able to decrypt the new keyfile.")
    print("You can select multiple keys (e.g., main + backup).")
    print("=" * 60)

    while True:
        if available_fprs:
            print("\nAvailable fingerprints in your keyring:")
            for i, (fpr, uid) in enumerate(available_fprs, 1):
                formatted = " ".join([fpr[i : i + 4] for i in range(0, len(fpr), 4)])
                # Mark already selected
                selected_mark = "✓" if fpr in fingerprints else " "
                print(f"  [{i}] {formatted} {selected_mark}")
                print(f"      {uid}")
            print(f"  [0] Enter fingerprint manually")
            print(f"  [d] Done selecting")
            print()

            choice = input("Select fingerprint or 'd' when done: ").strip().lower()

            if choice == "d" or choice == "done":
                break
            elif choice == "" or choice == "0":
                fpr_input = input("Enter fingerprint (40 hex chars): ").strip()
            elif choice.isdigit() and 1 <= int(choice) <= len(available_fprs):
                fpr_input = available_fprs[int(choice) - 1][0]
                print(f"Selected: {fpr_input}")
            else:
                print("Invalid selection. Please try again.")
                continue
        else:
            fpr_input = input("Enter fingerprint (40 hex chars) or 'done': ").strip()
            if fpr_input.lower() in ["d", "done"]:
                break

        try:
            normalized = validate_fingerprint(fpr_input)
            if normalized in fingerprints:
                print("Already selected!")
                continue
            fingerprints.append(normalized)
            log(f"Added: {normalized}")
        except RuntimeError as e:
            error(str(e))
            continue

    if not fingerprints:
        raise RuntimeError("At least one YubiKey fingerprint is required!")

    return fingerprints


def prompt_for_security_mode(current_mode: str) -> str:
    """Prompt user to select a new security mode. Returns the selected mode."""
    print("\n" + "=" * 60)
    print("  SECURITY MODE SELECTION")
    print("=" * 60)
    print(f"\n  Current mode: {current_mode}")
    print(
        f"""
Choose your NEW security level:

  [1] Password Only
      Manual password entry only
      No keyfile, no YubiKey required
      
  [2] Password + Plain Keyfile
      Password + unencrypted keyfile
      Keyfile stored on {Branding.PRODUCT_NAME}
      
  [3] Password + Encrypted Keyfile (Recommended)
      Password + keyfile encrypted to YubiKey(s)
      Requires: Password + YubiKey + PIN
      
  [4] GPG Password-Only
      Password derived from GPG-encrypted seed
      Requires: YubiKey + PIN only
"""
    )

    mode_map = {
        "1": SecurityMode.PW_ONLY.value,
        "2": SecurityMode.PW_KEYFILE.value,
        "3": SecurityMode.PW_GPG_KEYFILE.value,
        "4": SecurityMode.GPG_PW_ONLY.value,
    }

    while True:
        choice = input("Select new security mode [1-4]: ").strip()
        if choice in mode_map:
            selected_mode = mode_map[choice]
            print(f"\n  ✓ Selected: {selected_mode}")
            return selected_mode
        print("Please enter 1, 2, 3, or 4.")


def generate_new_keyfile() -> bytes:
    """Generate a cryptographically random keyfile in memory."""
    log("Generating new random keyfile (64 bytes)...")
    return secrets.token_bytes(64)


def encrypt_keyfile_to_yubikeys(keyfile_data: bytes, fingerprints: list[str], output_path: Path) -> None:
    """Encrypt keyfile to multiple YubiKey GPG keys."""
    log(f"Encrypting new keyfile to {len(fingerprints)} YubiKey(s)...")

    # Build GPG command with multiple recipients
    args = ["gpg", "--encrypt", "--armor"]
    for fpr in fingerprints:
        args.extend(["--recipient", fpr])
    args.extend(["--output", str(output_path)])

    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(input=keyfile_data)

        if proc.returncode != 0:
            raise RuntimeError(f"GPG encryption failed: {stderr.decode()}")

        log(f"✓ New encrypted keyfile created: {output_path}")
    except Exception as e:
        raise RuntimeError(f"Failed to encrypt keyfile: {e}")


# =============================================================================
# SecretProvider Integration
# =============================================================================


def create_secret_provider(config: dict, smartdrive_dir: Path = None) -> "SecretProvider | None":
    """
    Create a SecretProvider instance from config for mode-aware credential access.

    This ensures credentials are decrypted consistently with the security mode,
    enforcing YubiKey requirements for GPG modes.

    Args:
        config: Loaded config.json dict
        smartdrive_dir: Path to .smartdrive directory (for relative path resolution)

    Returns:
        SecretProvider instance, or None if not available
    """
    if not _SECRET_PROVIDER_AVAILABLE or SecretProvider is None:
        return None

    try:
        return SecretProvider.from_config(config, smartdrive_dir)
    except Exception as e:
        warn(f"Could not create SecretProvider: {e}")
        return None


def decrypt_keyfile_via_provider(provider: "SecretProvider") -> tuple[bytes, Path]:
    """
    Decrypt keyfile using SecretProvider (enforces YubiKey requirements).

    This integrates with SecretProvider to ensure mode-aware decryption:
    - PW_GPG_KEYFILE: Requires YubiKey, decrypts to RAM temp
    - Provides consistent error handling and security guarantees

    Args:
        provider: Configured SecretProvider instance

    Returns:
        Tuple of (keyfile_bytes, temp_keyfile_path)

    Raises:
        RuntimeError: If decryption fails or mode not supported
    """
    if provider.security_mode not in (SecurityMode.PW_GPG_KEYFILE, SecurityMode.PW_KEYFILE):
        raise RuntimeError(f"Current mode ({provider.security_mode.value}) does not use keyfile")

    if provider.security_mode == SecurityMode.PW_GPG_KEYFILE:
        # Use SecretProvider's built-in GPG decryption (enforces YubiKey)
        try:
            temp_keyfile_path = provider._decrypt_keyfile_to_temp()
            keyfile_bytes = temp_keyfile_path.read_bytes()
            return keyfile_bytes, temp_keyfile_path
        except YubiKeyRequiredError as e:
            raise RuntimeError(f"YubiKey required: {e}")
        except SecretAccessError as e:
            raise RuntimeError(f"Keyfile decryption failed: {e}")

    elif provider.security_mode == SecurityMode.PW_KEYFILE:
        # Plain keyfile - just read it
        if provider.keyfile_plain_path and provider.keyfile_plain_path.exists():
            keyfile_bytes = provider.keyfile_plain_path.read_bytes()
            # Write to temp for consistency
            temp_path = write_temp_keyfile(keyfile_bytes)
            return keyfile_bytes, temp_path
        else:
            raise RuntimeError(f"Keyfile not found: {provider.keyfile_plain_path}")

    raise RuntimeError(f"Unsupported mode for keyfile decryption: {provider.security_mode}")


def derive_password_via_provider(provider: "SecretProvider") -> str:
    """
    Derive password using SecretProvider for GPG_PW_ONLY mode.

    This ensures the password is derived using the correct KDF parameters
    from config, with YubiKey enforcement.

    Args:
        provider: Configured SecretProvider instance (must be GPG_PW_ONLY mode)

    Returns:
        Derived password string

    Raises:
        RuntimeError: If derivation fails or mode not GPG_PW_ONLY
    """
    if provider.security_mode != SecurityMode.GPG_PW_ONLY:
        raise RuntimeError(f"Password derivation requires GPG_PW_ONLY mode, got: {provider.security_mode.value}")

    try:
        # Use SecretProvider's internal derivation (enforces YubiKey)
        return provider._derive_password_gpg_pw_only()
    except YubiKeyRequiredError as e:
        raise RuntimeError(f"YubiKey required for password derivation: {e}")
    except SecretAccessError as e:
        raise RuntimeError(f"Password derivation failed: {e}")


def decrypt_old_keyfile(enc_keyfile_path: Path) -> bytes:
    """Decrypt existing encrypted keyfile to memory."""
    if not enc_keyfile_path.exists():
        raise RuntimeError(f"Old encrypted keyfile not found: {enc_keyfile_path}")

    log(f"Decrypting old keyfile: {enc_keyfile_path}")
    # BUG-20251219-001 FIX: Use --no-tty and timeout to prevent terminal hang
    gpg_timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30) if Limits else 30
    try:
        result = subprocess.run(
            ["gpg", "--no-tty", "--yes", "--decrypt", str(enc_keyfile_path)],
            check=True,
            capture_output=True,
            timeout=gpg_timeout,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError("GPG decryption timed out (check YubiKey)")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to decrypt old keyfile: {e.stderr.decode()}")


def write_temp_keyfile(keyfile_data: bytes) -> Path:
    """Write keyfile data to temporary file in RAM-backed directory."""
    ram_temp_dir = get_ram_temp_dir()
    tmp_path = ram_temp_dir / f"sd_rekey_{os.urandom(8).hex()}.bin"

    try:
        with tmp_path.open("wb") as f:
            f.write(keyfile_data)
            f.flush()
            os.fsync(f.fileno())
        return tmp_path
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except:
            pass
        raise


def secure_delete_file(path: Path) -> None:
    """Securely delete a file by overwriting before removal."""
    if not path or not path.exists():
        return

    try:
        file_size = path.stat().st_size

        if file_size > 0:
            with path.open("r+b") as f:
                f.write(b"\x00" * file_size)
                f.flush()
                os.fsync(f.fileno())
                f.seek(0)
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())

        if os.name != "nt" and have("shred"):
            subprocess.run(["shred", "-u", "-n", "1", str(path)], check=False, capture_output=True)
        else:
            path.unlink(missing_ok=True)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except:
            pass


def change_veracrypt_credentials_windows(
    vc_exe: Path,
    volume_path: str,
    old_keyfile: Path | None,
    new_keyfile: Path | None,
    secret_provider: "SecretProvider" = None,
) -> bool:
    """Change VeraCrypt volume credentials on Windows using GUI.

    SECURITY (per AGENT_ARCHITECTURE.md):
    - Secrets NOT printed to terminal
    - CPW/CKF/CDP commands for on-demand credential access
    - GPG_PW_ONLY mode enforces YubiKey via SecretProvider

    Args:
        vc_exe: Path to VeraCrypt executable
        volume_path: Path to volume
        old_keyfile: Path to old keyfile (or None)
        new_keyfile: Path to new keyfile (or None)
        secret_provider: SecretProvider for mode-aware credential access

    Returns:
        True if credential change was successful, False otherwise.
    """
    print("\n" + "=" * 70)
    print("  VERACRYPT GUI - CREDENTIAL CHANGE")
    print("=" * 70)
    print("\nVeraCrypt GUI will open. Follow these steps carefully:\n")
    print("  1. In the menu, click 'Volumes' → 'Change Volume Password...'")
    print("")
    print("  2. In the top section, click 'Select Device...'")
    print(f"     Select: {volume_path}")
    print("")
    print("  ─── CURRENT CREDENTIALS (top half) ───")
    print("  3. Enter your CURRENT password")
    if old_keyfile:
        print("  4. Click 'Keyfiles...' button (top section)")
        print("     → Click 'Add Files...'")
        print(f"     → Navigate to: {old_keyfile}")
        print("     → Click 'OK'")
    else:
        print("  4. Leave 'Use keyfiles' unchecked (no current keyfile)")
    print("")
    print("  ─── NEW CREDENTIALS (bottom half) ───")
    print("  5. Enter your NEW password (or same password if only changing keyfile)")
    print("  6. Confirm the NEW password")
    if new_keyfile:
        print("  7. Click 'Keyfiles...' button (bottom section)")
        print("     → Click 'Add Files...'")
        print(f"     → Navigate to: {new_keyfile}")
        print("     → Click 'OK'")
    else:
        print("  7. Leave 'Use keyfiles' unchecked (no new keyfile)")
    print("")
    print("  8. Click 'OK' to apply the changes")
    print("  9. Wait for 'Password changed successfully' message")
    print("")
    print("=" * 70)

    # Print command reference for on-demand secret access
    if secret_provider:
        print("\n  " + "=" * 60)
        print("  ON-DEMAND COPY COMMANDS:")
        if secret_provider.security_mode == SecurityMode.GPG_PW_ONLY:
            print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard (GPG-derived)")
        else:
            print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard")
        if old_keyfile:
            print(f"    {UserInputs.COPY_KEY_FILE}  = Copy Keyfile path to clipboard")
        print(f"    {UserInputs.COPY_DEVICE_PATH} = Copy Volume path to clipboard")
        print("")
        print("  SECURITY: Secrets are NOT printed. Use commands to copy.")
        print("  " + "=" * 60)

    input("\nPress Enter to open VeraCrypt GUI...")

    # Open VeraCrypt GUI
    try:
        # On Windows: CREATE_NO_WINDOW prevents unexpected GUI popups from probes
        if "windows" in platform.system().lower():
            subprocess.Popen([str(vc_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen([str(vc_exe)])
        print("\n✓ VeraCrypt GUI opened.")
        print("  Complete the credential change, then return here.")
        print("")

        # Command loop for on-demand secret access
        if secret_provider:
            print(
                f"  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.COPY_KEY_FILE} (keyfile), {UserInputs.COPY_DEVICE_PATH} (device), {UserInputs.YES} (success), {UserInputs.NO} (failed)"
            )
        else:
            print(f"  Type {UserInputs.YES} when finished, or {UserInputs.NO} if failed")

        # Ask if credential change was successful (with command loop)
        while True:
            response = input("\n> ").strip().upper()

            # Handle CPW/CKF/CDP commands (NON-BLOCKING)
            if secret_provider and response in (
                UserInputs.COPY_PASSWORD,
                UserInputs.COPY_KEY_FILE,
                UserInputs.COPY_DEVICE_PATH,
            ):
                secret_provider.handle_command(response)
                continue

            # Handle completion
            if response == UserInputs.YES:
                log("✓ Credential change confirmed successful")
                return True
            elif response == UserInputs.NO:
                warn("Credential change reported as failed - will rollback")
                return False
            else:
                if secret_provider:
                    print(
                        f"  Commands: {UserInputs.COPY_PASSWORD}/{UserInputs.COPY_KEY_FILE}/{UserInputs.COPY_DEVICE_PATH}/{UserInputs.YES}/{UserInputs.NO}"
                    )
                else:
                    print(f"  Please type exactly '{UserInputs.YES}' or '{UserInputs.NO}'")
    except Exception as e:
        raise RuntimeError(f"Failed to open VeraCrypt: {e}")


def change_veracrypt_credentials_unix(
    volume_path: str, old_keyfile: Path | None, new_keyfile: Path | None, secret_provider: "SecretProvider" = None
) -> bool:
    """Change VeraCrypt volume credentials on Unix using GUI.

    SECURITY (per AGENT_ARCHITECTURE.md):
    - Secrets NOT printed to terminal
    - CPW/CKF/CDP commands for on-demand credential access
    - GPG_PW_ONLY mode enforces YubiKey via SecretProvider

    Args:
        volume_path: Path to volume
        old_keyfile: Path to old keyfile (or None)
        new_keyfile: Path to new keyfile (or None)
        secret_provider: SecretProvider for mode-aware credential access

    Returns:
        True if credential change was successful, False otherwise.
    """
    print("\n" + "=" * 70)
    print("  VERACRYPT GUI - CREDENTIAL CHANGE")
    print("=" * 70)
    print("\nOpen VeraCrypt and follow these steps carefully:\n")
    print("  1. In the menu, click 'Volumes' → 'Change Volume Password...'")
    print("")
    print("  2. In the top section, click 'Select Device...'")
    print(f"     Select: {volume_path}")
    print("")
    print("  ─── CURRENT CREDENTIALS (top half) ───")
    print("  3. Enter your CURRENT password")
    if old_keyfile:
        print("  4. Click 'Keyfiles...' button (top section)")
        print("     → Click 'Add Files...'")
        print(f"     → Navigate to: {old_keyfile}")
        print("     → Click 'OK'")
    else:
        print("  4. Leave 'Use keyfiles' unchecked (no current keyfile)")
    print("")
    print("  ─── NEW CREDENTIALS (bottom half) ───")
    print("  5. Enter your NEW password (or same password if only changing keyfile)")
    print("  6. Confirm the NEW password")
    if new_keyfile:
        print("  7. Click 'Keyfiles...' button (bottom section)")
        print("     → Click 'Add Files...'")
        print(f"     → Navigate to: {new_keyfile}")
        print("     → Click 'OK'")
    else:
        print("  7. Leave 'Use keyfiles' unchecked (no new keyfile)")
    print("")
    print("  8. Click 'OK' to apply the changes")
    print("  9. Wait for 'Password changed successfully' message")
    print("")
    print("=" * 70)

    # Print command reference for on-demand secret access
    if secret_provider:
        print("\n  " + "=" * 60)
        print("  ON-DEMAND COPY COMMANDS:")
        if secret_provider.security_mode == SecurityMode.GPG_PW_ONLY:
            print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard (GPG-derived)")
        else:
            print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard")
        if old_keyfile:
            print(f"    {UserInputs.COPY_KEY_FILE}  = Copy Keyfile path to clipboard")
        print(f"    {UserInputs.COPY_DEVICE_PATH} = Copy Volume path to clipboard")
        print("")
        print("  SECURITY: Secrets are NOT printed. Use commands to copy.")
        print("  " + "=" * 60)

    # Command loop for on-demand secret access
    if secret_provider:
        print(
            f"\n  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.COPY_KEY_FILE} (keyfile), {UserInputs.COPY_DEVICE_PATH} (device), {UserInputs.YES} (success), {UserInputs.NO} (failed)"
        )
    else:
        print(f"\n  Type {UserInputs.YES} when finished, or {UserInputs.NO} if failed")

    # Ask if credential change was successful (with command loop)
    while True:
        response = input("\n> ").strip().upper()

        # Handle CPW/CKF/CDP commands (NON-BLOCKING)
        if secret_provider and response in (
            UserInputs.COPY_PASSWORD,
            UserInputs.COPY_KEY_FILE,
            UserInputs.COPY_DEVICE_PATH,
        ):
            secret_provider.handle_command(response)
            continue

        # Handle completion
        if response == UserInputs.YES:
            log("✓ Credential change confirmed successful")
            return True
        elif response == UserInputs.NO:
            warn("Credential change reported as failed - will rollback")
            return False
        else:
            if secret_provider:
                print(
                    f"  Commands: {UserInputs.COPY_PASSWORD}/{UserInputs.COPY_KEY_FILE}/{UserInputs.COPY_DEVICE_PATH}/{UserInputs.YES}/{UserInputs.NO}"
                )
            else:
                print(f"  Please type exactly '{UserInputs.YES}' or '{UserInputs.NO}'")


def main() -> None:
    print_banner()

    # Check dependencies
    if not have("gpg"):
        error("gpg not found in PATH. Please install GnuPG.")
        sys.exit(1)

    # Load config
    try:
        cfg = load_config()
    except RuntimeError as e:
        error(str(e))
        sys.exit(1)

    # Determine platform
    system = platform.system().lower()

    if "windows" in system:
        # Use Paths.veracrypt_exe() for centralized path resolution
        try:
            vc_exe = Paths.veracrypt_exe()
            if not vc_exe.exists():
                raise RuntimeError("VeraCrypt not found")
        except (RuntimeError, NameError):
            # Fallback: check PATH
            vc_which = shutil.which(Paths.VERACRYPT_EXE_NAME)
            if vc_which:
                vc_exe = Path(vc_which)
            else:
                error("VeraCrypt.exe not found. Please install VeraCrypt.")
                sys.exit(1)

        volume_path = (cfg.get(ConfigKeys.WINDOWS) or {}).get(ConfigKeys.VOLUME_PATH, "").strip()
    else:
        if not have("veracrypt"):
            error("veracrypt not found in PATH. Please install VeraCrypt.")
            sys.exit(1)
        vc_exe = None
        volume_path = (cfg.get(ConfigKeys.UNIX) or {}).get(ConfigKeys.VOLUME_PATH, "").strip()

    if not volume_path:
        error("volume_path not configured in config.json")
        sys.exit(1)

    print(f"\n  Target Volume: {volume_path}")

    # ==========================================================================
    # Create SecretProvider for mode-aware credential access
    # ==========================================================================
    config_path = get_config_path()
    smartdrive_dir = config_path.parent if config_path.exists() else None
    secret_provider = create_secret_provider(cfg, smartdrive_dir)
    current_mode = cfg.get("mode", SecurityMode.PW_ONLY.value)

    if secret_provider:
        log(f"SecretProvider initialized for mode: {current_mode}")
    else:
        warn("SecretProvider not available - using legacy credential handling")

    # ==========================================================================
    # PHASE 1: Current Credentials
    # ==========================================================================

    print_phase(1, 4, "CURRENT CREDENTIALS")

    print("First, let's identify your current volume credentials.\n")

    # Determine keyfile usage from mode rather than asking
    mode_uses_keyfile = current_mode in (SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value)

    if mode_uses_keyfile:
        print(f"  Current mode ({current_mode}) uses a keyfile.")
        use_old_keyfile = True
    else:
        print(f"  Current mode ({current_mode}) does not use a keyfile.")
        use_old_keyfile = input("  Override: Does this volume currently use a keyfile? (y/n): ").strip().lower() == "y"

    old_keyfile_data = None
    old_keyfile_temp = None

    if use_old_keyfile:
        old_encrypted = Path(cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, f"{Paths.KEYS_SUBDIR}/{FileNames.KEYFILE_GPG}"))
        if not old_encrypted.is_absolute():
            old_encrypted = (Path.cwd() / old_encrypted).resolve()

        print(f"\n  Encrypted keyfile: {old_encrypted}")
        print("\n  ⚠️  Insert the YubiKey that can decrypt this keyfile.")
        input("  Press Enter when ready...")

        try:
            # Use SecretProvider if available (enforces YubiKey requirements)
            if secret_provider and current_mode == SecurityMode.PW_GPG_KEYFILE.value:
                log("Decrypting keyfile via SecretProvider (YubiKey enforced)...")
                old_keyfile_data, old_keyfile_temp = decrypt_keyfile_via_provider(secret_provider)
                log(f"✓ Old keyfile decrypted to: {old_keyfile_temp}")
            else:
                # Fallback to direct GPG decryption
                old_keyfile_data = decrypt_old_keyfile(old_encrypted)
                old_keyfile_temp = write_temp_keyfile(old_keyfile_data)
                log(f"✓ Old keyfile decrypted to: {old_keyfile_temp}")
        except RuntimeError as e:
            error(str(e))
            if secret_provider:
                secret_provider.cleanup()
            sys.exit(1)
    else:
        log("Volume uses password-only authentication")

    # ==========================================================================
    # PHASE 1.5: Security Mode Selection
    # ==========================================================================

    print_phase(1, 5, "MODE SELECTION")

    print(f"Current security mode: {current_mode}")
    print("\nYou can change the security mode as part of this rekey operation.")
    print("This will update both the volume credentials AND the security configuration.\n")

    change_mode = input("Change security mode? (y/n): ").strip().lower() == "y"
    new_mode = current_mode

    if change_mode:
        try:
            new_mode = prompt_for_security_mode(current_mode)
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            if secret_provider:
                secret_provider.cleanup()
            sys.exit(0)
    else:
        print(f"  ✓ Keeping current mode: {current_mode}")

    # ==========================================================================
    # PHASE 2: New Credentials
    # ==========================================================================

    print_phase(2, 5, "NEW CREDENTIALS")

    print(f"Configuring credentials for mode: {new_mode}\n")

    # Determine what credentials are needed based on the new mode
    use_new_keyfile = False
    needs_gpg_setup = False

    if new_mode == SecurityMode.PW_ONLY.value:
        print("  Mode: Password-only")
        print("  No keyfile will be used - password only authentication.")

    elif new_mode == SecurityMode.PW_KEYFILE.value:
        print("  Mode: Password + Plain Keyfile")
        print("  A plain (unencrypted) keyfile will be generated.")
        use_new_keyfile = True

    elif new_mode == SecurityMode.PW_GPG_KEYFILE.value:
        print("  Mode: Password + Encrypted Keyfile")
        print("  A keyfile encrypted to YubiKey(s) will be generated.")
        use_new_keyfile = True

    elif new_mode == SecurityMode.GPG_PW_ONLY.value:
        print("  Mode: GPG Password-Only")
        print("  A random seed will be encrypted to generate passwords automatically.")
        needs_gpg_setup = True

    new_keyfile_data = None
    new_keyfile_temp = None
    new_encrypted_path = None
    new_fingerprints = None
    gpg_seed_data = None
    gpg_fingerprints = None

    if use_new_keyfile:
        print("\n  Select YubiKey(s) for the NEW encrypted keyfile.")
        print("  These keys will be able to decrypt and mount the volume.\n")

        # Get YubiKey fingerprints for NEW keyfile
        available_fprs = get_available_fingerprints()
        try:
            new_fingerprints = prompt_for_fingerprints(available_fprs)
        except RuntimeError as e:
            error(str(e))
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            sys.exit(1)

        # Generate new keyfile
        new_keyfile_data = generate_new_keyfile()
        new_keyfile_temp = write_temp_keyfile(new_keyfile_data)

        # Encrypt to YubiKeys - use same location as configured encrypted_keyfile
        configured_keyfile = Path(cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, f"{Paths.KEYS_SUBDIR}/{FileNames.KEYFILE_GPG}"))
        if not configured_keyfile.is_absolute():
            configured_keyfile = (Path.cwd() / configured_keyfile).resolve()

        # Create .new file in same directory
        new_encrypted_path = configured_keyfile.with_suffix(configured_keyfile.suffix + ".new")
        new_encrypted_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            encrypt_keyfile_to_yubikeys(new_keyfile_data, new_fingerprints, new_encrypted_path)
        except RuntimeError as e:
            error(str(e))
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            sys.exit(1)

    elif needs_gpg_setup:
        print("\n  Select YubiKey(s) to encrypt the password seed to.")
        print("  These keys will be able to generate the volume password.\n")

        # Get YubiKey fingerprints for GPG seed
        available_fprs = get_available_fingerprints()
        try:
            gpg_fingerprints = prompt_for_fingerprints(available_fprs)
        except RuntimeError as e:
            error(str(e))
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            sys.exit(1)

        # Generate random seed for password derivation
        gpg_seed_data = secrets.token_bytes(32)  # 256-bit seed

        # Encrypt seed to YubiKeys - use configured seed GPG path if available
        seed_path = Path(cfg.get(ConfigKeys.SEED_GPG_PATH, f"{Paths.KEYS_SUBDIR}/{FileNames.SEED_GPG}"))
        if not seed_path.is_absolute():
            seed_path = (Path.cwd() / seed_path).resolve()

        seed_new_path = seed_path.with_suffix(seed_path.suffix + ".new")
        seed_new_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            encrypt_keyfile_to_yubikeys(gpg_seed_data, gpg_fingerprints, seed_new_path)
        except RuntimeError as e:
            error(str(e))
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            sys.exit(1)

    else:
        log("New credentials will use password-only (no keyfile)")

    # ==========================================================================
    # PHASE 3: Review & Confirm
    # ==========================================================================

    print_phase(3, 5, "REVIEW & CONFIRM")

    print("Review the changes:\n")
    print(f"  Volume:           {volume_path}")
    print(f"  Current mode:     {current_mode}")
    print(f"  New mode:         {new_mode}")
    print(f"  Mode changed:     {'Yes' if new_mode != current_mode else 'No'}")
    print("")

    if new_mode == SecurityMode.PW_ONLY.value:
        print("  New setup:        Password-only authentication")
    elif new_mode == SecurityMode.PW_KEYFILE.value:
        print("  New setup:        Password + plain keyfile")
    elif new_mode == SecurityMode.PW_GPG_KEYFILE.value:
        print("  New setup:        Password + encrypted keyfile")
        print(f"  Keyfile encrypted to: {len(new_fingerprints)} YubiKey(s)")
    elif new_mode == SecurityMode.GPG_PW_ONLY.value:
        print("  New setup:        GPG-derived password (YubiKey + PIN only)")
        print(f"  Seed encrypted to: {len(gpg_fingerprints)} YubiKey(s)")

    print("")
    print(f"  Current keyfile:  {'Yes' if use_old_keyfile else 'No'}")
    if use_old_keyfile and old_keyfile_temp:
        print(f"                    {old_keyfile_temp}")

    if use_new_keyfile:
        print(f"  New keyfile:      Yes (newly generated)")
        print(f"                    {new_keyfile_temp}")
    elif needs_gpg_setup:
        print("  New seed:         Yes (newly generated for password derivation)")
    else:
        print("  New keyfile:      No")

    print("")
    if new_mode != SecurityMode.GPG_PW_ONLY.value:
        print("  Password will be entered in VeraCrypt GUI.")
        print("  ⚠️  Make sure you remember your NEW password!")
    else:
        print("  Password will be auto-generated from GPG seed.")
        print("  ⚠️  Make sure your YubiKey is available for verification!")

    print("")
    print("!" * 70)
    print("  ⚠️  If verification fails, your original configuration stays safe.")
    print("!" * 70)

    # Confirmation loop
    while True:
        print(f"\n  Type '{UserInputs.YES}' to proceed with credential change")
        print(f"  Type '{UserInputs.CANCEL}' to abort (no changes will be made)")
        confirm = input("\n> ").strip().upper()

        if confirm == UserInputs.YES:
            break
        elif confirm == UserInputs.CANCEL:
            log("Operation cancelled by user.")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            if "seed_new_path" in locals() and seed_new_path.exists():
                seed_new_path.unlink()
            print("\n✓ Cancelled. No changes were made.")
            sys.exit(0)
        else:
            print(f"  Invalid input. Please type exactly '{UserInputs.YES}' or '{UserInputs.CANCEL}'.")

    # ==========================================================================
    # PHASE 4: Execute & Verify
    # ==========================================================================

    print_phase(4, 5, "EXECUTE & VERIFY")

    print("[Step 1/3] Opening VeraCrypt GUI for credential change...\n")

    try:
        if "windows" in system:
            success = change_veracrypt_credentials_windows(
                vc_exe, volume_path, old_keyfile_temp, new_keyfile_temp, secret_provider
            )
        else:
            success = change_veracrypt_credentials_unix(
                volume_path, old_keyfile_temp, new_keyfile_temp, secret_provider
            )

        if not success:
            error("Credential change failed - cleaning up temporary files")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            if "seed_new_path" in locals() and seed_new_path.exists():
                seed_new_path.unlink()
            print("\n✓ Rollback complete. No changes were made to your encrypted files.")
            sys.exit(1)
    except RuntimeError as e:
        error(str(e))
        if old_keyfile_temp:
            secure_delete_file(old_keyfile_temp)
        if new_keyfile_temp:
            secure_delete_file(new_keyfile_temp)
        if new_encrypted_path and new_encrypted_path.exists():
            new_encrypted_path.unlink()
        if "seed_new_path" in locals() and seed_new_path.exists():
            seed_new_path.unlink()
        sys.exit(1)

    # Step 2: VERIFY new credentials work before committing
    print("\n" + "─" * 70)
    print("[Step 2/3] VERIFYING NEW CREDENTIALS")
    print("─" * 70)
    print("\nTo ensure the credential change worked, we'll test-mount the volume.")

    if new_mode == SecurityMode.GPG_PW_ONLY.value:
        print("Generating password from GPG seed for verification...\n")
        print("  ⚠️  Insert the YubiKey that can decrypt the new seed.")
        input("  Press Enter when ready...")

        # For GPG_PW_ONLY, derive password using SecretProvider-compatible logic
        # Create a temporary SecretProvider with the new seed path and parameters
        try:
            # Generate new salt for this session
            salt = secrets.token_bytes(16)
            salt_b64 = base64.b64encode(salt).decode("ascii")

            if _SECRET_PROVIDER_AVAILABLE and SecretProvider is not None:
                # Create temporary provider with new seed
                temp_provider = SecretProvider(
                    security_mode=SecurityMode.GPG_PW_ONLY,
                    volume_path=volume_path,
                    seed_gpg_path=seed_new_path,
                    salt_b64=salt_b64,
                    hkdf_info=CryptoParams.HKDF_INFO_DEFAULT,
                )
                try:
                    new_password = derive_password_via_provider(temp_provider)
                    log("✓ Password derived via SecretProvider (YubiKey enforced)")
                except RuntimeError as e:
                    error(str(e))
                    raise
                finally:
                    temp_provider.cleanup()
            else:
                # Fallback: Manual HKDF derivation (legacy)
                import hashlib
                import hmac

                log("Using legacy password derivation (SecretProvider not available)")

                # Decrypt seed from new encrypted file
                gpg_timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30)
                result = subprocess.run(
                    ["gpg", "--no-tty", "--yes", "--decrypt", str(seed_new_path)],
                    check=True,
                    capture_output=True,
                    timeout=gpg_timeout,
                )
                seed_bytes = result.stdout

                # Derive password using HKDF-SHA256
                hkdf = hmac.new(seed_bytes, salt, hashlib.sha256)
                password_bytes = hkdf.digest()[:32]
                new_password = base64.b64encode(password_bytes).decode("utf-8").rstrip("=")

                # Wipe seed from memory
                seed_bytes = None

                log("✓ Password generated from GPG seed")

        except subprocess.TimeoutExpired:
            error("GPG decryption timed out - check YubiKey")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            if seed_new_path.exists():
                seed_new_path.unlink()
            sys.exit(1)
        except Exception as e:
            error(f"Password derivation failed: {e}")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            if seed_new_path.exists():
                seed_new_path.unlink()
            sys.exit(1)
    else:
        # Non-GPG_PW_ONLY modes: prompt for password with command loop support
        print("Enter the NEW password you just set in VeraCrypt.\n")

        if secret_provider and secret_provider.security_mode in (
            SecurityMode.PW_ONLY,
            SecurityMode.PW_KEYFILE,
            SecurityMode.PW_GPG_KEYFILE,
        ):
            # Use SecretProvider's stored password if available (user should have set it in config)
            # Otherwise, provide CPW command to copy password
            print(f"  Commands: {UserInputs.COPY_PASSWORD} (copy password), or press Enter to input manually")

            while True:
                response = input("  > ").strip().upper()

                if response == UserInputs.COPY_PASSWORD:
                    secret_provider.handle_command(response)
                    print("  Password copied to clipboard. Press Enter to use it for verification.")
                    continue
                elif response == "":
                    # Manual entry
                    new_password = getpass("Enter NEW password: ")
                    break
                else:
                    print(f"  Type {UserInputs.COPY_PASSWORD} to copy, or press Enter to input manually")
        else:
            # Fallback: direct password entry
            new_password = getpass("Enter NEW password: ")

    try:
        if "windows" in system:
            verified = verify_new_credentials_windows(vc_exe, volume_path, new_password, new_keyfile_temp)
        else:
            verified = verify_new_credentials_unix(volume_path, new_password, new_keyfile_temp)

        if not verified:
            print("\n" + "!" * 70)
            error("VERIFICATION FAILED!")
            print("!" * 70)
            print("\nThe volume could NOT be mounted with the new credentials.")
            print("Your encrypted keyfile has NOT been replaced.\n")
            print("Possible causes:")
            print("  • Wrong password entered for verification")
            print("  • Volume header change failed in GUI")
            print("  • Wrong keyfile was selected in GUI")
            print("\n✓ Your original encrypted files are safe and unchanged.")

            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            if "seed_new_path" in locals() and seed_new_path.exists():
                seed_new_path.unlink()
            sys.exit(1)

        log("✓ New credentials verified successfully!")

    except Exception as e:
        error(f"Verification error: {e}")
        if old_keyfile_temp:
            secure_delete_file(old_keyfile_temp)
        if new_keyfile_temp:
            secure_delete_file(new_keyfile_temp)
        if new_encrypted_path and new_encrypted_path.exists():
            new_encrypted_path.unlink()
        if "seed_new_path" in locals() and seed_new_path.exists():
            seed_new_path.unlink()
        sys.exit(1)

    # Step 3: Cleanup and finalize
    print("\n" + "─" * 70)
    print("[Step 3/3] FINALIZING")
    print("─" * 70 + "\n")

    if old_keyfile_temp:
        secure_delete_file(old_keyfile_temp)
        log("✓ Old temporary keyfile securely deleted")
    if new_keyfile_temp:
        secure_delete_file(new_keyfile_temp)
        log("✓ New temporary keyfile securely deleted")

    if new_encrypted_path:
        # Move new encrypted keyfile to final location (same as config)
        configured_keyfile = Path(cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, f"{Paths.KEYS_SUBDIR}/{FileNames.KEYFILE_GPG}"))
        if not configured_keyfile.is_absolute():
            configured_keyfile = (Path.cwd() / configured_keyfile).resolve()

        final_path = configured_keyfile
        if final_path.exists():
            backup_path = final_path.with_suffix(final_path.suffix + ".old")
            log(f"Backing up old encrypted keyfile to: {backup_path.name}")
            # Remove old backup if it exists
            if backup_path.exists():
                backup_path.unlink()
            final_path.rename(backup_path)

        new_encrypted_path.rename(final_path)
        log(f"✓ New encrypted keyfile saved: {final_path.name}")

    if "seed_new_path" in locals() and seed_new_path.exists():
        # Move new encrypted seed to final location
        seed_path = Path(cfg.get(ConfigKeys.SEED_GPG_PATH, f"{Paths.KEYS_SUBDIR}/{FileNames.SEED_GPG}"))
        if not seed_path.is_absolute():
            seed_path = (Path.cwd() / seed_path).resolve()

        final_seed_path = seed_path
        if final_seed_path.exists():
            backup_seed_path = final_seed_path.with_suffix(final_seed_path.suffix + ".old")
            log(f"Backing up old encrypted seed to: {backup_seed_path.name}")
            if backup_seed_path.exists():
                backup_seed_path.unlink()
            final_seed_path.rename(backup_seed_path)

        seed_new_path.rename(final_seed_path)
        log(f"✓ New encrypted seed saved: {final_seed_path.name}")

    # Update config.json with new mode and settings
    try:
        from datetime import datetime

        config_path = get_config_path()
        if config_path.exists():
            with open(config_path, "r") as f:
                cfg_update = json.load(f)

            # Update mode
            cfg_update["mode"] = new_mode

            # Update mode-specific settings
            if new_mode == SecurityMode.GPG_PW_ONLY.value:
                cfg_update[ConfigKeys.SEED_GPG_PATH] = Path(
                    cfg.get(ConfigKeys.SEED_GPG_PATH, f"{Paths.KEYS_SUBDIR}/{FileNames.SEED_GPG}")
                )
                cfg_update[ConfigKeys.KDF] = CryptoParams.KDF_HKDF_SHA256
                # salt_b64 is set during GPG_PW_ONLY verification phase
                cfg_update[ConfigKeys.SALT_B64] = salt_b64
                cfg_update[ConfigKeys.HKDF_INFO] = CryptoParams.HKDF_INFO_DEFAULT
                cfg_update[ConfigKeys.PW_ENCODING] = CryptoParams.PW_ENCODING_DEFAULT
                # Remove keyfile settings if they exist
                cfg_update.pop(ConfigKeys.ENCRYPTED_KEYFILE, None)
            elif new_mode in [SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value]:
                cfg_update[ConfigKeys.ENCRYPTED_KEYFILE] = Path(
                    cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, f"{Paths.KEYS_SUBDIR}/{FileNames.KEYFILE_GPG}")
                )
                # Remove GPG password-only settings
                cfg_update.pop(ConfigKeys.SEED_GPG_PATH, None)
                cfg_update.pop(ConfigKeys.KDF, None)
                cfg_update.pop(ConfigKeys.SALT_B64, None)
                cfg_update.pop(ConfigKeys.HKDF_INFO, None)
                cfg_update.pop(ConfigKeys.PW_ENCODING, None)
            else:  # pw_only
                # Remove all keyfile and GPG settings
                cfg_update.pop(ConfigKeys.ENCRYPTED_KEYFILE, None)
                cfg_update.pop(ConfigKeys.SEED_GPG_PATH, None)
                cfg_update.pop(ConfigKeys.KDF, None)
                cfg_update.pop(ConfigKeys.SALT_B64, None)
                cfg_update.pop(ConfigKeys.HKDF_INFO, None)
                cfg_update.pop(ConfigKeys.PW_ENCODING, None)

            cfg_update[ConfigKeys.LAST_PASSWORD_CHANGE] = datetime.now().strftime("%Y-%m-%d")

            write_config_atomic(config_path, cfg_update)
            log("✓ Updated config.json with new mode and settings (atomic write)")
    except Exception as e:
        warn(f"Could not update config.json: {e}")

    # Clean up SecretProvider
    if secret_provider:
        secret_provider.cleanup()
        log("✓ SecretProvider cleanup complete")

    # Success message
    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║                    ✓ SUCCESS!                                 ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70)

    if new_mode != current_mode:
        print(f"\nSecurity mode changed: {current_mode} → {new_mode}")

    print("\nCredentials have been changed and verified successfully!\n")

    if use_new_keyfile:
        configured_keyfile = Path(cfg.get(ConfigKeys.ENCRYPTED_KEYFILE, f"{Paths.KEYS_SUBDIR}/{FileNames.KEYFILE_GPG}"))
        if not configured_keyfile.is_absolute():
            configured_keyfile = (Path.cwd() / configured_keyfile).resolve()
        print(f"  New encrypted keyfile: {configured_keyfile}")
        print(f"  Backup of old keyfile: {configured_keyfile.with_suffix(configured_keyfile.suffix + '.old')}")
        print("\n  💡 Test mount.py before deleting the .old backup!")

    if needs_gpg_setup:
        seed_path = Path(cfg.get(ConfigKeys.SEED_GPG_PATH, f"{Paths.KEYS_SUBDIR}/{FileNames.SEED_GPG}"))
        if not seed_path.is_absolute():
            seed_path = (Path.cwd() / seed_path).resolve()
        print(f"  New encrypted seed: {seed_path}")
        print(f"  Backup of old seed: {seed_path.with_suffix(seed_path.suffix + '.old')}")
        print("\n  💡 Test mount.py before deleting the .old backup!")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error("\nAborted by user.")
        sys.exit(1)
