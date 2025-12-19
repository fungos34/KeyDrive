#!/usr/bin/env python3
"""
SmartDrive mount script (MVP)

Updated: 2025-12-12 - Test update mechanism

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

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from getpass import getpass
from pathlib import Path


CONFIG_FILENAME = "config.json"


CONFIG_TEMPLATE = {
    # Keyfile settings (all optional - leave empty for password-only)
    # For GPG-encrypted keyfile (YubiKey): "keyfile.vc.gpg"
    # For plain keyfile: "keyfile.bin"
    # For no keyfile (password only): "" or remove the key
    "encrypted_keyfile": "../keys/keyfile.vc.gpg",
    "windows": {
        # Use either a device path like:
        #   "\\Device\\Harddisk1\\Partition2"
        # NOTE: Harddisk numbers can change when plugging into different USB ports!
        # Use PowerShell 'Get-Disk | Format-Table' to find the correct number.
        "volume_path": "\\Device\\Harddisk1\\Partition2",
        "mount_letter": "V",
        # Optional override. If empty, script tries to auto-detect VeraCrypt.exe
        "veracrypt_path": ""
    },
    "unix": {
        # Device path: "/dev/sdX2"
        # or container: "/run/media/user/PAYLOAD/vault.hc"
        "volume_path": "/dev/sdX2",
        "mount_point": "~/veradrive"
    }
}


def log(msg: str) -> None:
    print(f"[SmartDrive] {msg}")


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
    Resolve path to keyfile from config.
    Returns None if no keyfile configured (password-only mode).
    """
    rel = cfg.get("encrypted_keyfile", "").strip()
    if not rel:
        return None  # Password-only mode
    
    enc_path = (script_root / rel).expanduser().resolve()
    if not enc_path.exists():
        raise RuntimeError(f"Keyfile not found: {enc_path}")
    return enc_path


def is_gpg_encrypted(file_path: Path) -> bool:
    """Check if a file is GPG-encrypted (by extension or magic bytes)."""
    # Check extension
    if file_path.suffix.lower() in ['.gpg', '.pgp', '.asc']:
        return True
    
    # Check magic bytes (GPG binary format starts with specific bytes)
    try:
        with open(file_path, 'rb') as f:
            header = f.read(2)
            # GPG packets start with 0x84, 0x85, 0x8c, 0xa3, etc. (old format)
            # or 0xc0-0xff (new format)
            if header and (header[0] >= 0x84 or header[0] >= 0xc0):
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
        try:
            result = subprocess.run(
                ["gpg", "--yes", "--decrypt", str(keyfile_path)],
                check=True,
                capture_output=True,
                text=False,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr.decode('utf-8', errors='replace') if e.stderr else 'Unknown error'
            raise RuntimeError(f"GPG decryption failed: {stderr_text}")
    else:
        log(f"Loading plain keyfile: {keyfile_path.name}")
        with open(keyfile_path, 'rb') as f:
            return f.read()


def find_veracrypt_windows(script_root: Path, cfg: dict) -> Path:
    """
    Try to find VeraCrypt.exe on Windows:
    1) Config override
    2) Local copy next to this script
    3) Typical install locations
    4) PATH
    """
    cfg_win = cfg.get("windows", {})
    override = cfg_win.get("veracrypt_path", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise RuntimeError(
            f"veracrypt_path in config.json points to non-existent file: {override}"
        )

    candidates = [
        script_root / "VeraCrypt.exe",
        script_root.parent / "VeraCrypt.exe",
        Path(r"C:\Program Files\VeraCrypt\VeraCrypt.exe"),
        Path(r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c

    path_exe = shutil.which("VeraCrypt.exe")
    if path_exe:
        return Path(path_exe)

    raise RuntimeError(
        "Could not find VeraCrypt.exe. "
        "Set 'windows.veracrypt_path' in config.json or install VeraCrypt."
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
                timeout=5
            )
            agent_running = result.returncode == 0 and result.stdout and "gpg-agent.exe" in result.stdout
        else:
            # On Unix, check for gpg-agent process
            result = subprocess.run(
                ["pgrep", "-f", "gpg-agent"],
                capture_output=True,
                timeout=5
            )
            agent_running = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    
    if not agent_running:
        error_msg = (
            "\n" + "="*70 + "\n"
            "GPG AGENT NOT RUNNING\n" + 
            "="*70 + "\n\n"
            "The GPG agent (gpg-agent.exe) is not running.\n"
            "This is required to communicate with your YubiKey.\n\n"
            "SOLUTIONS:\n\n"
            "1. Start Kleopatra (GUI for GPG):\n"
            "   - Launch Kleopatra from Start Menu\n"
            "   - This will start the GPG agent automatically\n\n"
            "2. Or start GPG agent manually:\n"
            "   gpg-connect-agent /bye\n\n"
            "3. Or restart your computer\n"
            "   (GPG agent should start on login)\n\n"
            "After starting the agent, try mounting again.\n" +
            "="*70
        )
        raise RuntimeError(error_msg)
    
    # Check 2: YubiKey detected by GPG
    log("GPG agent is running ✓")
    log("Checking for YubiKey...")
    
    try:
        # Try to list smartcards - this will fail if no YubiKey or agent issues
        result = subprocess.run(
            ["gpg", "--card-status"],
            capture_output=True,
            text=True,
            timeout=10,  # Give it time to prompt for PIN if needed
            encoding='utf-8',
            errors='ignore'  # Ignore decoding errors
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
    error_msg = (
        "\n" + "="*70 + "\n"
        "YUBIKEY NOT DETECTED\n" + 
        "="*70 + "\n\n"
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
        "After fixing the issue, try mounting again.\n" +
        "="*70
    )
    raise RuntimeError(error_msg)


def load_keyfile(keyfile_path: Path) -> bytes:
    """
    Load keyfile data, decrypting if GPG-encrypted.
    Returns the plaintext keyfile bytes.
    """
    if is_gpg_encrypted(keyfile_path):
        log(f"Decrypting GPG-encrypted keyfile: {keyfile_path}")
        
        # Create temporary file for decrypted output
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            # Decrypt using GPG
            args = [
                "gpg",
                "--decrypt",
                "--yes",  # Overwrite output if exists
                "--output", str(tmp_path),
                str(keyfile_path),
            ]
            
            log("Insert YubiKey and enter PIN when prompted...")
            
            # Run GPG with a timeout to prevent hanging
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=60  # 60 second timeout
                )
                
                if result.returncode != 0:
                    # Clean up temp file
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except:
                        pass
                    
                    # Provide helpful error message
                    stderr = result.stderr.lower()
                    if "no secret key" in stderr or "key not found" in stderr:
                        error_msg = (
                            "\n" + "="*70 + "\n"
                            "GPG DECRYPTION FAILED: No matching private key\n" + 
                            "="*70 + "\n\n"
                            "The keyfile is encrypted to a GPG key that's not available.\n\n"
                            "This could mean:\n"
                            "1. Wrong YubiKey inserted (need the one used during setup)\n"
                            "2. YubiKey keys were not properly imported\n"
                            "3. Using a different YubiKey than during setup\n\n"
                            "SOLUTIONS:\n\n"
                            "1. Insert the correct YubiKey\n"
                            "2. Check available GPG keys: gpg --list-secret-keys\n"
                            "3. If this is a backup YubiKey, ensure it has the right subkeys\n\n"
                            "For help with key management, see the setup documentation.\n" +
                            "="*70
                        )
                    elif "bad passphrase" in stderr or "pin" in stderr:
                        error_msg = (
                            "\n" + "="*70 + "\n"
                            "GPG DECRYPTION FAILED: Incorrect PIN\n" + 
                            "="*70 + "\n\n"
                            "The YubiKey PIN you entered was incorrect.\n\n"
                            "Note: YubiKeys have a limited number of PIN attempts\n"
                            "(usually 3) before locking. If locked, you may need\n"
                            "to reset the PIN using the PUK or factory reset.\n\n"
                            "Try again with the correct PIN.\n" +
                            "="*70
                        )
                    elif "card not present" in stderr or "no reader" in stderr:
                        error_msg = (
                            "\n" + "="*70 + "\n"
                            "GPG DECRYPTION FAILED: YubiKey not detected\n" + 
                            "="*70 + "\n\n"
                            "Your YubiKey is not detected during decryption.\n\n"
                            "This could happen if:\n"
                            "1. YubiKey was removed during decryption\n"
                            "2. YubiKey connection was interrupted\n"
                            "3. GPG agent lost connection to the YubiKey\n\n"
                            "SOLUTIONS:\n\n"
                            "1. Ensure YubiKey remains inserted\n"
                            "2. Try restarting Kleopatra or the GPG agent\n"
                            "3. Re-run: gpg-connect-agent /bye\n\n"
                            "Then try mounting again.\n" +
                            "="*70
                        )
                    else:
                        error_msg = (
                            f"GPG decryption failed: {result.stderr}\n"
                            f"Exit code: {result.returncode}\n\n"
                            "Check that your YubiKey is properly configured and inserted."
                        )
                    
                    raise RuntimeError(error_msg)
                
            except subprocess.TimeoutExpired:
                # Clean up temp file
                try:
                    tmp_path.unlink(missing_ok=True)
                except:
                    pass
                
                error_msg = (
                    "\n" + "="*70 + "\n"
                    "GPG DECRYPTION TIMED OUT\n" + 
                    "="*70 + "\n\n"
                    "The GPG decryption process timed out, likely because:\n\n"
                    "1. You cancelled the operation (Ctrl+C)\n"
                    "2. GPG is waiting for PIN input but not prompting properly\n"
                    "3. GPG agent is not running or unresponsive\n\n"
                    "SOLUTIONS:\n\n"
                    "1. Ensure Kleopatra is running\n"
                    "2. Try: gpg-connect-agent /bye\n"
                    "3. Check YubiKey status: gpg --card-status\n\n"
                    "Then try mounting again.\n" +
                    "="*70
                )
                raise RuntimeError(error_msg)
            
            # Read decrypted data
            with open(tmp_path, 'rb') as f:
                data = f.read()
            
            # Clean up temp file securely
            try:
                tmp_path.unlink(missing_ok=True)
            except:
                pass
            
            log(f"✓ Keyfile decrypted successfully ({len(data)} bytes)")
            return data
            
        except Exception as e:
            # Clean up temp file
            try:
                tmp_path.unlink(missing_ok=True)
            except:
                pass
            raise
    else:
        # Plain keyfile - just read it
        log(f"Loading plain keyfile: {keyfile_path}")
        try:
            with open(keyfile_path, 'rb') as f:
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
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="sd_key_",
            suffix=".bin"
        )
        tmp = Path(tmp_path)
        
        try:
            # Write keyfile data
            with os.fdopen(tmp_fd, 'wb') as f:
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
            Path("/tmp"),      # Fallback
        ]
        
        for ramdisk in ramdisk_paths:
            if ramdisk.exists() and ramdisk.is_dir():
                try:
                    tmp_fd, tmp_path = tempfile.mkstemp(
                        prefix="sd_key_",
                        suffix=".bin",
                        dir=str(ramdisk)
                    )
                    tmp = Path(tmp_path)
                    
                    # Set restrictive permissions immediately (before writing)
                    os.chmod(tmp, 0o600)  # rw------- (owner only)
                    
                    with os.fdopen(tmp_fd, 'wb') as f:
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
            with path.open('r+b') as f:
                # Pass 1: Overwrite with zeros
                f.write(b'\x00' * file_size)
                f.flush()
                os.fsync(f.fileno())
                
                # Pass 2: Overwrite with random data
                f.seek(0)
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
        
        # Use shred if available (Unix)
        if os.name != "nt" and have("shred"):
            subprocess.run(
                ["shred", "-u", "-n", "1", str(path)],
                check=False,
                capture_output=True
            )
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
    normalized = volume_path.strip().upper().replace("\\\\", "\\")
    
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
    
    normalized = volume_path.strip().lower()
    
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


def mount_veracrypt_windows(vc_exe: Path, cfg: dict, tmp_key: Path | None, password: str) -> None:
    cfg_win = cfg.get("windows", {})
    volume_path = cfg_win.get("volume_path", "").strip()
    if not volume_path:
        raise RuntimeError("windows.volume_path is missing/empty in config.json")

    # Safety check: prevent mounting system drives
    validate_volume_path_windows(volume_path)

    mount_letter = cfg_win.get("mount_letter", "").strip().upper() or "V"

    # Check if drive letter is already in use
    if Path(f"{mount_letter}:\\").exists():
        raise RuntimeError(
            f"Drive letter {mount_letter}: is already in use.\n"
            f"Please choose a different letter in config.json or unmount the existing drive."
        )

    log(f"Mounting VeraCrypt volume on Windows as drive {mount_letter}:")
    log(f"  Volume path: {volume_path}")
    if tmp_key:
        log(f"  Using keyfile: yes")
    else:
        log(f"  Using keyfile: no (password only)")
    
    args = [
        str(vc_exe),
        "/q",  # quiet
        "/s",  # silent
        "/h",  # no GUI
        "/v", volume_path,
        "/l", mount_letter,
        "/a",  # auto-mount
        "/m", "rm",  # read/write mount
    ]

    # Add keyfile if provided
    if tmp_key:
        args.extend(["/k", str(tmp_key)])

    # VeraCrypt requires /p even for empty password; use empty string if none
    args.extend(["/p", password if password is not None else ""])

    try:
        run_cmd(args, check=True)
        log(f"Mounted successfully as {mount_letter}:")
    except RuntimeError as e:
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
            f"   - Keyfile: {tmp_key}\n"
            f"   - Enter password when prompted\n"
            f"   - This will show the exact error if the path is wrong\n\n"
            f"Try mounting manually to see exact error:\n"
            f'  "{vc_exe}" /v {volume_path} /l {mount_letter} /k "{tmp_key}"'
        )
        raise RuntimeError(error_msg) from e


def mount_veracrypt_unix(cfg: dict, tmp_key: Path | None, password: str) -> None:
    cfg_unix = cfg.get("unix", {})
    volume_path = cfg_unix.get("volume_path", "").strip()
    if not volume_path:
        raise RuntimeError("unix.volume_path is missing/empty in config.json")

    # Safety check: prevent mounting system drives
    validate_volume_path_unix(volume_path)

    mount_point_raw = cfg_unix.get("mount_point", "").strip() or "~/veradrive"
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
    
    # Add keyfile if provided
    if tmp_key:
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
                f"VeraCrypt mount failed (exit {proc.returncode}).\n"
                f"stdout: {stdout}\n"
                f"stderr: {stderr}"
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
    if keyfile_path and is_gpg_encrypted(keyfile_path):
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
        print("\n" + "="*70)
        print("MISSING DEPENDENCIES DETECTED")
        print("="*70)
        print(f"\nThe following required tools are not installed: {', '.join(missing_tools)}")
        print("\nINSTALLATION INSTRUCTIONS:")
        print("-" * 40)
        
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. {rec}")
        
        print(f"\n{'='*70}")
        print("After installing the missing tools, run this script again.")
        print("="*70)
        
        # Ask if user wants to continue anyway (might work if tools are in non-standard locations)
        try:
            choice = input("\nTry to continue anyway? [y/N]: ").strip().lower()
            if choice != 'y':
                print("Exiting. Please install the required tools and try again.")
                sys.exit(1)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(1)
    
    # If GPG is needed, give a quick status check
    if keyfile_path and is_gpg_encrypted(keyfile_path) and have("gpg"):
        print("\nNote: YubiKey mode detected.")
        print("Make sure your YubiKey is inserted and Kleopatra is running.")
        print("If mounting fails, the script will provide specific guidance.")


def main() -> None:
    script_root = Path(__file__).resolve().parent
    cfg = load_or_init_config(script_root)

    # Check for required dependencies and offer installation
    keyfile_path = resolve_encrypted_keyfile(script_root, cfg)
    check_and_offer_dependency_installation(script_root, cfg, keyfile_path)

    try:
        vc_path_windows = ensure_dependencies(script_root, cfg, keyfile_path)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Determine mount mode
    if keyfile_path is None:
        log("Mode: Password-only (no keyfile configured)")
    elif is_gpg_encrypted(keyfile_path):
        log("Mode: GPG-encrypted keyfile (YubiKey/GPG key required)")
    else:
        log("Mode: Plain keyfile")

    # Ask for VeraCrypt password (can be empty)
    try:
        password = getpass("Enter VeraCrypt password (leave empty if none): ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted by user.", file=sys.stderr)
        sys.exit(1)

    keyfile_data: bytes | None = None
    tmp_key: Path | None = None
    
    try:
        # Handle keyfile if configured
        if keyfile_path:
            # Step 1: Load keyfile (decrypt if GPG-encrypted, or read plain)
            keyfile_data = load_keyfile(keyfile_path)
            
            # Step 2: Create temporary file (preferably in RAM)
            tmp_key = create_temp_keyfile_secure(keyfile_data)
            
            # Step 3: Zero out the in-memory copy immediately
            if keyfile_data:
                keyfile_data = b'\x00' * len(keyfile_data)
                del keyfile_data
                keyfile_data = None
        
        # Step 4: Mount the volume
        system = platform.system().lower()
        if "windows" in system:
            if vc_path_windows is None:
                raise RuntimeError("Internal error: VeraCrypt path not resolved on Windows.")
            mount_veracrypt_windows(vc_path_windows, cfg, tmp_key, password)
        else:
            mount_veracrypt_unix(cfg, tmp_key, password)

    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Cleanup in reverse order
        if tmp_key is not None:
            cleanup_temp_keyfile(tmp_key)
        if keyfile_data is not None:
            keyfile_data = b'\x00' * len(keyfile_data)
            del keyfile_data


if __name__ == "__main__":
    main()
