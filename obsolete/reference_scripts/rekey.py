#!/usr/bin/env python3
"""
SmartDrive rekey script

Change VeraCrypt volume password and/or keyfile:
- Rotate keyfile when YubiKey is lost/compromised
- Change password
- Add keyfile to password-only volume
- Replace keyfile for different YubiKeys

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


def log(msg: str) -> None:
    print(f"[SmartDrive] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[WARNING] {msg}")


def print_banner():
    """Print welcome banner."""
    print("\n" + "="*70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║           SmartDrive Credential Rotation v1.0                 ║")
    print("  ║   Change Password / Rotate YubiKey / Add Keyfile Protection   ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("="*70)


def print_phase(num: int, total: int, title: str):
    """Print phase header."""
    print(f"\n{'─'*70}")
    print(f"  PHASE {num}/{total}: {title}")
    print(f"{'─'*70}\n")


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def verify_new_credentials_windows(
    vc_exe: Path,
    volume_path: str,
    password: str,
    keyfile: Path | None
) -> bool:
    """Verify new credentials work by attempting a test mount.
    
    Returns:
        True if credentials work, False otherwise.
    """
    log("Verifying new credentials by test mounting...")
    
    # Find an unused drive letter for test mount
    import string
    used_drives = {d.split(':')[0] for d in subprocess.check_output('wmic logicaldisk get caption', text=True).split() if ':' in d}
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
        "/volume", volume_path,
        "/letter", available_drive[0],
        "/password", password,
        "/quit",
        "/silent"
    ]
    
    if keyfile:
        args.extend(["/keyfile", str(keyfile)])
    
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # Mount succeeded, now dismount
            log(f"✓ Test mount successful on {available_drive}")
            subprocess.run([
                str(vc_exe),
                "/dismount", available_drive[0],
                "/quit",
                "/silent"
            ], capture_output=True, timeout=10)
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


def verify_new_credentials_unix(
    volume_path: str,
    password: str,
    keyfile: Path | None
) -> bool:
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
        "--password", password
    ]
    
    if keyfile:
        args.extend(["--keyfiles", str(keyfile)])
    
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # Mount succeeded, now dismount
            log(f"✓ Test mount successful at {mount_point}")
            subprocess.run([
                "veracrypt",
                "--text",
                "--dismount",
                str(mount_point)
            ], capture_output=True, timeout=10)
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


def load_config() -> dict:
    """Load config.json from current directory."""
    config_path = Path("config.json")
    if not config_path.exists():
        raise RuntimeError(
            "config.json not found. Run this script from the same directory as mount.py"
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
        raise RuntimeError(
            f"Invalid fingerprint length: {len(normalized)} characters (expected 40)"
        )
    
    if not all(c in "0123456789ABCDEF" for c in normalized):
        raise RuntimeError(
            f"Invalid fingerprint format: must contain only hex characters (0-9, A-F)"
        )
    
    return normalized


def prompt_for_fingerprints(available_fprs: list[tuple[str, str]]) -> list[str]:
    """Prompt user for one or more YubiKey fingerprints."""
    fingerprints = []
    
    print("\n" + "="*60)
    print("YubiKey Selection for New Keyfile")
    print("="*60)
    print("Select YubiKey(s) that should be able to decrypt the new keyfile.")
    print("You can select multiple keys (e.g., main + backup).")
    print("="*60)
    
    while True:
        if available_fprs:
            print("\nAvailable fingerprints in your keyring:")
            for i, (fpr, uid) in enumerate(available_fprs, 1):
                formatted = " ".join([fpr[i:i+4] for i in range(0, len(fpr), 4)])
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


def decrypt_old_keyfile(enc_keyfile_path: Path) -> bytes:
    """Decrypt existing encrypted keyfile to memory."""
    if not enc_keyfile_path.exists():
        raise RuntimeError(f"Old encrypted keyfile not found: {enc_keyfile_path}")
    
    log(f"Decrypting old keyfile: {enc_keyfile_path}")
    try:
        result = subprocess.run(
            ["gpg", "--yes", "--decrypt", str(enc_keyfile_path)],
            check=True,
            capture_output=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to decrypt old keyfile: {e.stderr.decode()}")


def write_temp_keyfile(keyfile_data: bytes) -> Path:
    """Write keyfile data to temporary file."""
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="sd_rekey_", suffix=".bin")
    tmp = Path(tmp_path)
    
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(keyfile_data)
            f.flush()
            os.fsync(f.fileno())
        return tmp
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
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
            with path.open('r+b') as f:
                f.write(b'\x00' * file_size)
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
    new_keyfile: Path | None
) -> bool:
    """Change VeraCrypt volume credentials on Windows using GUI.
    
    Returns:
        True if credential change was successful, False otherwise.
    """
    print("\n" + "="*70)
    print("  VERACRYPT GUI - CREDENTIAL CHANGE")
    print("="*70)
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
    print("="*70)
    
    input("\nPress Enter to open VeraCrypt GUI...")
    
    # Open VeraCrypt GUI
    try:
        subprocess.Popen([str(vc_exe)], shell=True)
        print("\n✓ VeraCrypt GUI opened.")
        print("  Complete the credential change, then return here.")
        input("\nPress Enter when you've finished in VeraCrypt...")
        
        # Ask if credential change was successful
        while True:
            print("\n  Did the credential change succeed?")
            print("  Type 'YES' if you saw 'Password changed successfully'")
            print("  Type 'NO' if there was an error or you cancelled")
            response = input("\n> ").strip().upper()
            if response == "YES":
                log("✓ Credential change confirmed successful")
                return True
            elif response == "NO":
                warn("Credential change reported as failed - will rollback")
                return False
            else:
                print("  Please type exactly 'YES' or 'NO'")
    except Exception as e:
        raise RuntimeError(f"Failed to open VeraCrypt: {e}")


def change_veracrypt_credentials_unix(
    volume_path: str,
    old_keyfile: Path | None,
    new_keyfile: Path | None
) -> bool:
    """Change VeraCrypt volume credentials on Unix using GUI.
    
    Returns:
        True if credential change was successful, False otherwise.
    """
    print("\n" + "="*70)
    print("  VERACRYPT GUI - CREDENTIAL CHANGE")
    print("="*70)
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
    print("="*70)
    
    input("\nPress Enter when you've finished in VeraCrypt...")
    
    # Ask if credential change was successful
    while True:
        print("\n  Did the credential change succeed?")
        print("  Type 'YES' if you saw 'Password changed successfully'")
        print("  Type 'NO' if there was an error or you cancelled")
        response = input("\n> ").strip().upper()
        if response == "YES":
            log("✓ Credential change confirmed successful")
            return True
        elif response == "NO":
            warn("Credential change reported as failed - will rollback")
            return False
        else:
            print("  Please type exactly 'YES' or 'NO'")


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
        if not have("VeraCrypt.exe"):
            veracrypt_paths = [
                Path(r"C:\Program Files\VeraCrypt\VeraCrypt.exe"),
                Path(r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"),
            ]
            vc_exe = None
            for p in veracrypt_paths:
                if p.exists():
                    vc_exe = p
                    break
            if not vc_exe:
                error("VeraCrypt.exe not found. Please install VeraCrypt.")
                sys.exit(1)
        else:
            vc_exe = Path(shutil.which("VeraCrypt.exe"))
        
        volume_path = cfg.get("windows", {}).get("volume_path", "").strip()
    else:
        if not have("veracrypt"):
            error("veracrypt not found in PATH. Please install VeraCrypt.")
            sys.exit(1)
        vc_exe = None
        volume_path = cfg.get("unix", {}).get("volume_path", "").strip()
    
    if not volume_path:
        error("volume_path not configured in config.json")
        sys.exit(1)
    
    print(f"\n  Target Volume: {volume_path}")
    
    # ==========================================================================
    # PHASE 1: Current Credentials
    # ==========================================================================
    
    print_phase(1, 4, "CURRENT CREDENTIALS")
    
    print("First, let's identify your current volume credentials.\n")
    
    use_old_keyfile = input("Does this volume currently use a keyfile? (y/n): ").strip().lower() == "y"
    old_keyfile_data = None
    old_keyfile_temp = None
    
    if use_old_keyfile:
        old_encrypted = Path(cfg.get("encrypted_keyfile", "../keys/keyfile.vc.gpg"))
        if not old_encrypted.is_absolute():
            old_encrypted = (Path.cwd() / old_encrypted).resolve()
        
        print(f"\n  Encrypted keyfile: {old_encrypted}")
        print("\n  ⚠️  Insert the YubiKey that can decrypt this keyfile.")
        input("  Press Enter when ready...")
        
        try:
            old_keyfile_data = decrypt_old_keyfile(old_encrypted)
            old_keyfile_temp = write_temp_keyfile(old_keyfile_data)
            log(f"✓ Old keyfile decrypted to: {old_keyfile_temp}")
        except RuntimeError as e:
            error(str(e))
            sys.exit(1)
    else:
        log("Volume uses password-only authentication")
    
    # ==========================================================================
    # PHASE 2: New Credentials
    # ==========================================================================
    
    print_phase(2, 4, "NEW CREDENTIALS")
    
    print("Now, configure your NEW credentials.\n")
    print("Options:")
    print("  • Change password only (keep or remove keyfile)")
    print("  • Add YubiKey protection (generate new encrypted keyfile)")
    print("  • Rotate YubiKey (new keyfile encrypted to different keys)")
    print("")
    
    use_new_keyfile = input("Use a NEW keyfile encrypted to YubiKey(s)? (y/n): ").strip().lower() == "y"
    new_keyfile_data = None
    new_keyfile_temp = None
    new_encrypted_path = None
    new_fingerprints = None
    
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
        configured_keyfile = Path(cfg.get("encrypted_keyfile", "../keys/keyfile.vc.gpg"))
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
    else:
        log("New credentials will use password-only (no keyfile)")
    
    # ==========================================================================
    # PHASE 3: Review & Confirm
    # ==========================================================================
    
    print_phase(3, 4, "REVIEW & CONFIRM")
    
    print("Review the credential change:\n")
    print(f"  Volume:           {volume_path}")
    print(f"  Current keyfile:  {'Yes' if use_old_keyfile else 'No'}")
    if use_old_keyfile and old_keyfile_temp:
        print(f"                    {old_keyfile_temp}")
    print(f"  New keyfile:      {'Yes (newly generated)' if use_new_keyfile else 'No'}")
    if use_new_keyfile and new_keyfile_temp:
        print(f"                    {new_keyfile_temp}")
    if use_new_keyfile and new_fingerprints:
        print(f"  Encrypted to:     {len(new_fingerprints)} YubiKey(s)")
    print("")
    print("  Password will be entered in VeraCrypt GUI.")
    print("")
    print("!"*70)
    print("  ⚠️  Make sure you remember your NEW password!")
    print("  ⚠️  If verification fails, your original keyfile stays safe.")
    print("!"*70)
    
    # Confirmation loop
    while True:
        print("\n  Type 'YES' to proceed with credential change")
        print("  Type 'CANCEL' to abort (no changes will be made)")
        confirm = input("\n> ").strip().upper()
        
        if confirm == "YES":
            break
        elif confirm == "CANCEL":
            log("Operation cancelled by user.")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            print("\n✓ Cancelled. No changes were made.")
            sys.exit(0)
        else:
            print(f"  Invalid input. Please type exactly 'YES' or 'CANCEL'.")
    
    # ==========================================================================
    # PHASE 4: Execute & Verify
    # ==========================================================================
    
    print_phase(4, 4, "EXECUTE & VERIFY")
    
    print("[Step 1/3] Opening VeraCrypt GUI for credential change...\n")
    
    try:
        if "windows" in system:
            success = change_veracrypt_credentials_windows(
                vc_exe,
                volume_path,
                old_keyfile_temp,
                new_keyfile_temp
            )
        else:
            success = change_veracrypt_credentials_unix(
                volume_path,
                old_keyfile_temp,
                new_keyfile_temp
            )
        
        if not success:
            error("Credential change failed - cleaning up temporary files")
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
            print("\n✓ Rollback complete. No changes were made to your encrypted keyfile.")
            sys.exit(1)
    except RuntimeError as e:
        error(str(e))
        if old_keyfile_temp:
            secure_delete_file(old_keyfile_temp)
        if new_keyfile_temp:
            secure_delete_file(new_keyfile_temp)
        if new_encrypted_path and new_encrypted_path.exists():
            new_encrypted_path.unlink()
        sys.exit(1)
    
    # Step 2: VERIFY new credentials work before committing
    print("\n" + "─"*70)
    print("[Step 2/3] VERIFYING NEW CREDENTIALS")
    print("─"*70)
    print("\nTo ensure the credential change worked, we'll test-mount the volume.")
    print("Enter the NEW password you just set in VeraCrypt.\n")
    
    new_password = getpass("Enter NEW password: ")
    
    try:
        if "windows" in system:
            verified = verify_new_credentials_windows(
                vc_exe,
                volume_path,
                new_password,
                new_keyfile_temp
            )
        else:
            verified = verify_new_credentials_unix(
                volume_path,
                new_password,
                new_keyfile_temp
            )
        
        if not verified:
            print("\n" + "!"*70)
            error("VERIFICATION FAILED!")
            print("!"*70)
            print("\nThe volume could NOT be mounted with the new credentials.")
            print("Your encrypted keyfile has NOT been replaced.\n")
            print("Possible causes:")
            print("  • Wrong password entered for verification")
            print("  • Volume header change failed in GUI")
            print("  • Wrong keyfile was selected in GUI")
            print("\n✓ Your original encrypted keyfile is safe and unchanged.")
            
            if old_keyfile_temp:
                secure_delete_file(old_keyfile_temp)
            if new_keyfile_temp:
                secure_delete_file(new_keyfile_temp)
            if new_encrypted_path and new_encrypted_path.exists():
                new_encrypted_path.unlink()
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
        sys.exit(1)
    
    # Step 3: Cleanup and finalize
    print("\n" + "─"*70)
    print("[Step 3/3] FINALIZING")
    print("─"*70 + "\n")
    
    if old_keyfile_temp:
        secure_delete_file(old_keyfile_temp)
        log("✓ Old temporary keyfile securely deleted")
    if new_keyfile_temp:
        secure_delete_file(new_keyfile_temp)
        log("✓ New temporary keyfile securely deleted")
    
    if new_encrypted_path:
        # Move new encrypted keyfile to final location (same as config)
        configured_keyfile = Path(cfg.get("encrypted_keyfile", "../keys/keyfile.vc.gpg"))
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
    
    # Success message
    print("\n" + "="*70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║                    ✓ SUCCESS!                                 ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("="*70)
    print("\nCredentials have been changed and verified successfully!\n")
    
    # Update last_password_change in config.json
    try:
        from datetime import datetime
        config_path = Path("config.json")
        if config_path.exists():
            with open(config_path, 'r') as f:
                cfg_update = json.load(f)
            cfg_update["last_password_change"] = datetime.now().strftime("%Y-%m-%d")
            with open(config_path, 'w') as f:
                json.dump(cfg_update, f, indent=2)
            log("✓ Updated last_password_change in config.json")
    except Exception as e:
        warn(f"Could not update config.json: {e}")
    
    if use_new_keyfile:
        configured_keyfile = Path(cfg.get("encrypted_keyfile", "../keys/keyfile.vc.gpg"))
        if not configured_keyfile.is_absolute():
            configured_keyfile = (Path.cwd() / configured_keyfile).resolve()
        print(f"  New encrypted keyfile: {configured_keyfile}")
        print(f"  Backup of old keyfile: {configured_keyfile.with_suffix(configured_keyfile.suffix + '.old')}")
        print("\n  💡 Test mount.py before deleting the .old backup!")
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error("\nAborted by user.")
        sys.exit(1)
