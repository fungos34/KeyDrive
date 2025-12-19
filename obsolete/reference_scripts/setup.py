#!/usr/bin/env python3
"""
SmartDrive Setup Wizard

Automated setup for encrypted external drives with YubiKey + VeraCrypt:
- Detect and select external drive
- Partition drive (LAUNCHER + PAYLOAD)
- Create VeraCrypt encrypted volume
- Add YubiKey protection
- Copy scripts and generate config

⚠️ WARNING: This script performs DESTRUCTIVE operations!
All data on the selected drive will be permanently erased.

Dependencies:
- Python 3.7+
- gpg in PATH with YubiKeys configured
- VeraCrypt installed
- Administrator/root privileges

Usage:
    python setup.py              # Interactive wizard
    python setup.py --help       # Show options
"""

import ctypes
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from getpass import getpass


# =============================================================================
# Constants
# =============================================================================

LAUNCHER_SIZE_MB = 200  # Default LAUNCHER partition size
LAUNCHER_LABEL = "LAUNCHER"
PAYLOAD_LABEL = "PAYLOAD"
KEYFILE_SIZE = 64  # bytes

# Get current version
try:
    from version import VERSION
except ImportError:
    VERSION = "1.0.0"


# =============================================================================
# Utility Functions
# =============================================================================

def log(msg: str) -> None:
    print(f"[SmartDrive] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[WARNING] {msg}")


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def is_admin() -> bool:
    """Check if running with administrator privileges."""
    system = platform.system().lower()
    if "windows" in system:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    else:
        return os.geteuid() == 0


def run_cmd(args, *, check=True, capture_output=True, text=True, input_text=None, timeout=None):
    """Run a subprocess command."""
    try:
        result = subprocess.run(
            args,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input_text,
            timeout=timeout,
        )
        return result
    except subprocess.CalledProcessError as e:
        error_details = []
        if e.stdout:
            error_details.append(f"stdout: {e.stdout}")
        if e.stderr:
            error_details.append(f"stderr: {e.stderr}")
        error_msg = '\n'.join(error_details) if error_details else f"exit code {e.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(str(a) for a in args)}\n{error_msg}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out: {' '.join(str(a) for a in args)}")


def confirm_destructive(prompt: str, confirm_word: str = "ERASE") -> bool:
    """
    Require user to type exact confirmation word for destructive operations.
    Returns True only if exact match. Loops until ERASE or CANCEL.
    """
    print(f"\n{'='*60}")
    print(f"⚠️  {prompt}")
    print(f"{'='*60}")
    
    while True:
        print(f"\n  Type '{confirm_word}' to proceed with data destruction.")
        print(f"  Type 'CANCEL' to abort safely (no changes will be made).")
        print()
        response = input("> ").strip()
        
        if response == confirm_word:
            return True
        elif response == "CANCEL":
            print("\n✓ Cancelled. No changes were made to any drive.")
            return False
        else:
            print(f"\n❌ Invalid input. You entered: '{response}'")
            print(f"   Expected exactly '{confirm_word}' or 'CANCEL'.")


# =============================================================================
# Drive Detection
# =============================================================================

def get_drives_windows() -> list[dict]:
    """Get list of drives on Windows with detailed info."""
    drives = []
    try:
        # Get disk info via PowerShell (include ALL disks, even system)
        ps_script = """
        Get-Disk | ForEach-Object {
            $disk = $_
            $partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | ForEach-Object {
                @{
                    Number = $_.PartitionNumber
                    Size = [math]::Round($_.Size / 1GB, 2)
                    DriveLetter = $_.DriveLetter
                    Type = $_.Type
                }
            }
            @{
                Number = $disk.Number
                Name = $disk.FriendlyName
                Bus = $disk.BusType.ToString()
                SizeGB = [math]::Round($disk.Size / 1GB, 2)
                PartitionStyle = $disk.PartitionStyle.ToString()
                IsSystem = $disk.IsSystem
                IsBoot = $disk.IsBoot
                Partitions = @($partitions)
            }
        } | ConvertTo-Json -Depth 3
        """
        result = run_cmd(
            ["powershell", "-NoProfile", "-Command", ps_script],
            check=True
        )
        
        data = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]
        
        for disk in data:
            drives.append({
                "number": disk["Number"],
                "name": disk["Name"],
                "bus": disk["Bus"],
                "size_gb": disk["SizeGB"],
                "partition_style": disk["PartitionStyle"],
                "is_system": disk.get("IsSystem", False),
                "is_boot": disk.get("IsBoot", False),
                "partitions": disk.get("Partitions") or [],
            })
    except Exception as e:
        error(f"Failed to list drives: {e}")
    
    return drives


def get_drives_unix() -> list[dict]:
    """Get list of drives on Linux/macOS with detailed info."""
    drives = []
    system = platform.system().lower()
    
    try:
        if "darwin" in system:
            # macOS
            result = run_cmd(["diskutil", "list", "-plist"], check=True)
            import plistlib
            data = plistlib.loads(result.stdout.encode())
            # Parse macOS disk info...
            for disk_id in data.get("AllDisksAndPartitions", []):
                if disk_id.get("Content") == "GUID_partition_scheme":
                    drives.append({
                        "name": disk_id.get("DeviceIdentifier", "?"),
                        "size_gb": disk_id.get("Size", 0) / (1024**3),
                        "bus": "unknown",
                        "is_system": disk_id.get("DeviceIdentifier") == "disk0",
                    })
        else:
            # Linux
            result = run_cmd(
                ["lsblk", "-d", "-o", "NAME,SIZE,TYPE,TRAN,MODEL", "-J"],
                check=True
            )
            data = json.loads(result.stdout)
            
            for device in data.get("blockdevices", []):
                if device.get("type") == "disk":
                    name = f"/dev/{device['name']}"
                    is_system = device["name"] in ["sda", "nvme0n1", "vda"]
                    drives.append({
                        "name": name,
                        "model": device.get("model", "Unknown"),
                        "size": device.get("size", "?"),
                        "bus": device.get("tran", "?"),
                        "is_system": is_system,
                    })
    except Exception as e:
        error(f"Failed to list drives: {e}")
    
    return drives


def display_drives(drives: list[dict], system: str) -> None:
    """Display drives in a formatted table."""
    print("\n" + "="*70)
    print("  AVAILABLE DRIVES")
    print("="*70)
    
    # Sort drives by number/name for consistent display
    if "windows" in system:
        sorted_drives = sorted(drives, key=lambda d: d.get("number", 0))
        print(f"{'[#]':<6} {'Name':<28} {'Size':<10} {'Bus':<8} {'Status'}")
        print("-"*70)
        
        for d in sorted_drives:
            status_parts = []
            if d.get("is_system") or d.get("is_boot"):
                status_parts.append("⛔ SYSTEM")
            elif d["bus"] in ["USB", "7"]:  # 7 = USB in some versions
                status_parts.append("✓ External")
            
            if d["partitions"]:
                letters = [p.get("DriveLetter") for p in d["partitions"] if p.get("DriveLetter")]
                if letters:
                    status_parts.append(f"[{', '.join(letters)}:]")
            
            status = " ".join(status_parts)
            num_display = f"[{d['number']}]"
            print(f"{num_display:<6} {d['name'][:28]:<28} {d['size_gb']:<10.1f} {d['bus']:<8} {status}")
    else:
        sorted_drives = sorted(drives, key=lambda d: d.get("name", ""))
        print(f"{'[Device]':<15} {'Model':<25} {'Size':<10} {'Bus':<8} {'Status'}")
        print("-"*70)
        
        for d in sorted_drives:
            status = "⛔ SYSTEM" if d.get("is_system") else "✓ External" if d.get("bus") == "usb" else ""
            model = d.get("model", d.get("name", "?"))[:25]
            print(f"[{d['name']:<13}] {model:<25} {d.get('size', '?'):<10} {d.get('bus', '?'):<8} {status}")
    
    print("="*70)


def select_drive(drives: list[dict], system: str) -> dict | None:
    """Let user select a drive. Returns selected drive or None."""
    # Filter out system drives for selection
    safe_drives = [d for d in drives if not d.get("is_system") and not d.get("is_boot")]
    system_drives = [d for d in drives if d.get("is_system") or d.get("is_boot")]
    
    if not safe_drives:
        error("No external drives detected!")
        print("Please connect an external USB drive and try again.")
        return None
    
    display_drives(drives, system)
    
    print("\n⚠️  WARNING: System drives are shown but CANNOT be selected.")
    print("    Only external drives can be configured.\n")
    
    while True:
        if "windows" in system:
            choice = input("Enter disk NUMBER to configure (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                return None
            
            try:
                disk_num = int(choice)
                selected = next((d for d in safe_drives if d["number"] == disk_num), None)
                if selected:
                    return selected
                else:
                    # Check if they tried to select a system drive
                    system_drive = next((d for d in drives if d["number"] == disk_num), None)
                    if system_drive:
                        error("Cannot select system/boot drive! Choose an external drive.")
                    else:
                        error(f"Disk {disk_num} not found.")
            except ValueError:
                error("Please enter a valid disk number.")
        else:
            choice = input("Enter device path to configure (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                return None
            
            selected = next((d for d in safe_drives if d["name"] == choice), None)
            if selected:
                return selected
            else:
                error(f"Device {choice} not found or is a system drive.")


# =============================================================================
# GPG/YubiKey Functions
# =============================================================================

def get_available_fingerprints() -> list[tuple[str, str]]:
    """Get available GPG key fingerprints."""
    try:
        result = run_cmd(
            ["gpg", "--list-keys", "--with-colons"],
            check=True
        )
        
        fingerprints = []
        current_fpr = None
        
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr":
                current_fpr = parts[9]
            elif parts[0] == "uid" and current_fpr:
                uid = parts[9]
                fingerprints.append((current_fpr, uid))
                current_fpr = None
        
        return fingerprints
    except:
        return []


def prompt_for_fingerprints(available: list[tuple[str, str]]) -> list[str]:
    """Prompt user to select YubiKey fingerprints. Returns empty list for password-only mode."""
    selected = []
    
    print("\n" + "="*60)
    print("  SECURITY MODE SELECTION")
    print("="*60)
    print("""
Choose your security level:

  [1] Password + YubiKey (Recommended)
      Keyfile encrypted to hardware token(s)
      Requires: Password + YubiKey + PIN
      
  [2] Password + Plain Keyfile
      Unencrypted keyfile stored on LAUNCHER
      Requires: Password + keyfile present
      
  [3] Password Only
      No keyfile, just VeraCrypt password
      Requires: Password only
""")
    
    while True:
        mode = input("Select security mode [1/2/3]: ").strip()
        if mode in ("1", "2", "3"):
            break
        print("Please enter 1, 2, or 3.")
    
    if mode == "3":
        # Password-only mode
        print("\n  ℹ️  Password-only mode selected.")
        print("     Your drive will be protected by password alone.")
        return []  # Empty list signals password-only
    
    if mode == "2":
        # Plain keyfile mode
        print("\n  ℹ️  Plain keyfile mode selected.")
        print("     A keyfile will be generated but NOT encrypted.")
        print("     Store the keyfile securely (separate from the drive).")
        return ["PLAIN_KEYFILE"]  # Special marker for plain keyfile mode
    
    # YubiKey mode - select fingerprints
    print("\n" + "-"*60)
    print("  SELECT YUBIKEY(S)")
    print("-"*60)
    print("Select YubiKey(s) to encrypt the keyfile to.")
    print("Recommend: Select MAIN + BACKUP keys.\n")
    
    if available:
        for i, (fpr, uid) in enumerate(available, 1):
            formatted = " ".join([fpr[j:j+4] for j in range(0, len(fpr), 4)])
            print(f"  [{i}] {formatted}")
            print(f"      {uid}")
        print(f"  [m] Enter fingerprint manually")
        print(f"  [d] Done selecting\n")
        
        while True:
            choice = input("Select [1-9/m/d]: ").strip().lower()
            
            if choice == "d":
                if not selected:
                    print("Please select at least one key.")
                    continue
                break
            elif choice == "m":
                fpr = input("Enter 40-char fingerprint: ").strip().replace(" ", "").upper()
                if len(fpr) == 40 and all(c in "0123456789ABCDEF" for c in fpr):
                    if fpr not in selected:
                        selected.append(fpr)
                        log(f"Added: {fpr[:16]}...")
                else:
                    error("Invalid fingerprint format.")
            elif choice.isdigit() and 1 <= int(choice) <= len(available):
                fpr = available[int(choice) - 1][0]
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr[:16]}...")
            else:
                print("Invalid selection.")
    else:
        print("No GPG keys found in keyring.")
        print("Enter fingerprints manually.\n")
        
        while True:
            fpr = input("Enter fingerprint (or 'd' when done): ").strip()
            if fpr.lower() == "d":
                if selected:
                    break
                print("Please enter at least one fingerprint.")
                continue
            
            fpr = fpr.replace(" ", "").upper()
            if len(fpr) == 40 and all(c in "0123456789ABCDEF" for c in fpr):
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr[:16]}...")
            else:
                error("Invalid fingerprint (must be 40 hex characters).")
    
    return selected


# =============================================================================
# Partitioning Functions
# =============================================================================

def partition_drive_windows(disk_number: int, launcher_size_mb: int) -> tuple[str, str]:
    """
    Partition a drive on Windows using diskpart.
    Creates: LAUNCHER (exFAT) + PAYLOAD (for VeraCrypt)
    Returns: (launcher_letter, payload_device_path)
    """
    log(f"Partitioning disk {disk_number}...")
    
    # Create diskpart script
    # Use 'clean all' or just stick with MBR if GPT conversion fails
    # Some USB drives have issues with GPT, so we'll use MBR which is more compatible
    diskpart_script = f"""select disk {disk_number}
clean
rem Using MBR for better USB compatibility
create partition primary size={launcher_size_mb}
format fs=exfat label="{LAUNCHER_LABEL}" quick
assign
create partition primary
"""
    
    # Write script to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(diskpart_script)
        script_path = f.name
    
    try:
        # Run diskpart
        result = run_cmd(
            ["diskpart", "/s", script_path],
            check=False,  # We'll check manually for better error messages
            timeout=120
        )
        
        # Check for errors in diskpart output
        if result.returncode != 0 or "error" in result.stdout.lower():
            error(f"Diskpart failed!")
            print(f"\nDiskpart output:\n{result.stdout}")
            if result.stderr:
                print(f"\nDiskpart errors:\n{result.stderr}")
            raise RuntimeError("Diskpart partitioning failed - see output above")
        
        log("✓ Partitioning complete")
        
        # Wait for Windows to recognize new partitions
        time.sleep(3)
        
        # Get the assigned drive letters
        ps_script = f"""
        $disk = Get-Disk -Number {disk_number}
        $partitions = Get-Partition -DiskNumber {disk_number} | Sort-Object PartitionNumber
        @{{
            LauncherLetter = ($partitions | Where-Object {{ $_.PartitionNumber -eq 1 }}).DriveLetter
            PayloadPartition = ($partitions | Where-Object {{ $_.PartitionNumber -eq 2 }}).PartitionNumber
        }} | ConvertTo-Json
        """
        
        result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
        info = json.loads(result.stdout)
        
        launcher_letter = info.get("LauncherLetter", "")
        payload_partition = info.get("PayloadPartition", 2)
        
        # Device path for VeraCrypt
        payload_device = f"\\Device\\Harddisk{disk_number}\\Partition{payload_partition}"
        
        return launcher_letter, payload_device
        
    finally:
        os.unlink(script_path)


def partition_drive_unix(device: str, launcher_size_mb: int) -> tuple[str, str]:
    """
    Partition a drive on Linux using parted.
    Returns: (launcher_mount, payload_device)
    """
    log(f"Partitioning {device}...")
    
    # Create GPT partition table
    run_cmd(["parted", "-s", device, "mklabel", "gpt"], check=True)
    
    # Create LAUNCHER partition
    run_cmd([
        "parted", "-s", device,
        "mkpart", "primary", "fat32", "1MiB", f"{launcher_size_mb + 1}MiB"
    ], check=True)
    
    # Create PAYLOAD partition (rest of disk)
    run_cmd([
        "parted", "-s", device,
        "mkpart", "primary", f"{launcher_size_mb + 1}MiB", "100%"
    ], check=True)
    
    # Determine partition names
    if "nvme" in device or "mmcblk" in device:
        launcher_dev = f"{device}p1"
        payload_dev = f"{device}p2"
    else:
        launcher_dev = f"{device}1"
        payload_dev = f"{device}2"
    
    # Format LAUNCHER as exFAT
    time.sleep(1)  # Wait for kernel to recognize partitions
    run_cmd(["mkfs.exfat", "-n", LAUNCHER_LABEL, launcher_dev], check=True)
    
    log("✓ Partitioning complete")
    
    # Mount LAUNCHER temporarily
    mount_point = f"/mnt/{LAUNCHER_LABEL}"
    os.makedirs(mount_point, exist_ok=True)
    run_cmd(["mount", launcher_dev, mount_point], check=True)
    
    return mount_point, payload_dev


# =============================================================================
# VeraCrypt Functions
# =============================================================================

def find_veracrypt_windows() -> Path | None:
    """Find VeraCrypt.exe on Windows."""
    if have("VeraCrypt.exe"):
        return Path(shutil.which("VeraCrypt.exe"))
    
    paths = [
        Path(r"C:\Program Files\VeraCrypt\VeraCrypt.exe"),
        Path(r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"),
    ]
    for p in paths:
        if p.exists():
            return p
    return None


def create_veracrypt_volume_windows(
    vc_exe: Path,
    device_path: str,
    password: str,
    keyfile_path: Path | None = None,
    size_mb: int | None = None
) -> bool:
    """Create a VeraCrypt volume on Windows."""
    log(f"Creating VeraCrypt volume on {device_path}...")
    
    # VeraCrypt CLI (Format.exe) does NOT support partition/device encryption reliably.
    # It only works well for file containers with explicit size.
    # For partition encryption, we MUST use the GUI.
    
    # Check if this is a device path (partition encryption) vs file container
    is_device = (
        device_path.startswith("\\Device\\") or
        device_path.startswith("\\\\.\\") or
        device_path.startswith("\\\\?\\")
    )
    
    if is_device:
        # Device/partition encryption - go directly to GUI
        log("Partition encryption requires VeraCrypt GUI...")
        return create_veracrypt_volume_gui(vc_exe, device_path, password, keyfile_path)
    
    # File container - CLI works fine
    log("Creating file container via CLI...")
    
    format_exe = vc_exe.parent / "VeraCrypt Format.exe"
    if not format_exe.exists():
        format_exe = vc_exe
    
    args = [
        str(format_exe),
        "/create", device_path,
        "/password", password,
        "/encryption", "AES",
        "/hash", "SHA-512",
        "/filesystem", "exFAT",
        "/quick",
        "/silent",
    ]
    
    if size_mb:
        args.extend(["/size", f"{size_mb}M"])
    
    if keyfile_path:
        args.extend(["/keyfile", str(keyfile_path)])
    
    try:
        # VeraCrypt volume creation can take a while
        result = run_cmd(args, check=False, timeout=600)
        
        # Check output for success or known issues
        output = (result.stdout or "") + (result.stderr or "")
        
        if result.returncode == 0 and "error" not in output.lower():
            log("✓ VeraCrypt volume created successfully")
            return True
        else:
            # CLI often fails for device encryption - fall back to GUI
            if output:
                log(f"CLI output: {output[:200]}...")
            log("CLI volume creation failed, opening GUI...")
            return create_veracrypt_volume_gui(vc_exe, device_path, password, keyfile_path)
    except Exception as e:
        error(f"VeraCrypt volume creation failed: {e}")
        # Try GUI as last resort
        return create_veracrypt_volume_gui(vc_exe, device_path, password, keyfile_path)


def create_veracrypt_volume_gui(vc_exe: Path, device_path: str, password: str, keyfile_path: Path | None = None) -> bool:
    """Guide user through VeraCrypt GUI volume creation."""
    print("\n" + "="*60)
    print("  MANUAL VERACRYPT VOLUME CREATION")
    print("="*60)
    print("\nVeraCrypt GUI will open. Please follow these steps:\n")
    print("  1. Click 'Create Volume'")
    print("  2. Select 'Encrypt a non-system partition/drive' → Next")
    print("  3. Select 'Standard VeraCrypt volume' → Next")
    print(f"  4. Click 'Select Device' and choose: {device_path}")
    print("  5. Select 'Create encrypted volume and format it'")
    print("     (NOT 'Encrypt partition in place'!) → Next")
    print("  6. Choose encryption: AES and SHA-512 are fine → Next")
    print("  7. Verify the volume size is correct → Next")
    print(f"  8. Enter your password")
    if keyfile_path:
        print(f"     ✓ Click 'Use keyfiles', then 'Add File...' and select:")
        print(f"       {keyfile_path}")
    else:
        print("     ⚠️  Do NOT add a keyfile here! We add YubiKey protection later.")
    print("     → Next")
    print("  9. Select 'Yes' for large files support → Next")
    print(" 10. Choose filesystem: exFAT (for cross-platform)")
    print("     Enable 'Quick Format' (much faster, fine for new drives) → Next")
    print(" 11. Move mouse randomly until bar is full")
    print(" 12. Click 'Format' and confirm the warning")
    print(" 13. Wait for completion, then click 'Exit'")
    print("\n" + "="*60)
    
    input("\nPress Enter to open VeraCrypt...")
    
    try:
        subprocess.Popen([str(vc_exe)])
        print("\nVeraCrypt opened. Complete the volume creation.")
        
        while True:
            response = input("\nDid volume creation succeed? [yes/no]: ").strip().lower()
            if response == "yes":
                return True
            elif response == "no":
                return False
            print("Please type 'yes' or 'no'")
    except Exception as e:
        error(f"Failed to open VeraCrypt: {e}")
        return False


def create_veracrypt_volume_unix(device: str, password: str, keyfile_path: Path | None = None) -> bool:
    """Create a VeraCrypt volume on Linux/macOS."""
    log(f"Creating VeraCrypt volume on {device}...")
    
    args = [
        "veracrypt", "--text", "--create", device,
        "--password", password,
        "--encryption", "AES",
        "--hash", "SHA-512",
        "--filesystem", "exfat",
        "--quick",
        "--non-interactive",
    ]
    
    if keyfile_path:
        args.extend(["--keyfiles", str(keyfile_path)])
    
    try:
        run_cmd(args, check=True, timeout=600)
        log("✓ VeraCrypt volume created successfully")
        return True
    except Exception as e:
        error(f"VeraCrypt volume creation failed: {e}")
        return False


# =============================================================================
# Keyfile & Encryption
# =============================================================================

def generate_keyfile() -> bytes:
    """Generate random keyfile data."""
    return secrets.token_bytes(KEYFILE_SIZE)


def encrypt_keyfile_to_yubikeys(keyfile_data: bytes, fingerprints: list[str], output_path: Path) -> bool:
    """Encrypt keyfile to multiple YubiKey recipients."""
    log("Encrypting keyfile to YubiKeys...")
    log("(You may be prompted for YubiKey PIN/touch)")
    
    args = ["gpg", "--encrypt", "--armor", "--output", str(output_path)]
    for fpr in fingerprints:
        args.extend(["--recipient", fpr])
    
    try:
        # GPG reads from stdin for encryption
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(input=keyfile_data)
        
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode())
        
        log(f"✓ Encrypted keyfile: {output_path}")
        return True
    except Exception as e:
        error(f"Keyfile encryption failed: {e}")
        return False


# =============================================================================
# Script Deployment
# =============================================================================

def deploy_scripts(launcher_path: Path, payload_device: str, encrypted_keyfile: Path, mount_letter: str = "V") -> bool:
    """Copy scripts and create config on LAUNCHER partition."""
    log("Deploying scripts to LAUNCHER partition...")
    
    scripts_dir = Path(__file__).resolve().parent
    project_root = scripts_dir.parent
    target_scripts = launcher_path / "scripts"
    target_keys = launcher_path / "keys"
    
    # Create directories
    target_scripts.mkdir(parents=True, exist_ok=True)
    target_keys.mkdir(parents=True, exist_ok=True)
    
    # Copy scripts
    scripts_to_copy = ["smartdrive.py", "mount.py", "unmount.py", "rekey.py", "keyfile.py"]
    for script in scripts_to_copy:
        src = scripts_dir / script
        if src.exists():
            shutil.copy2(src, target_scripts / script)
            log(f"  Copied {script}")
    
    # Copy launcher scripts and docs to root of LAUNCHER partition
    bat_launcher = project_root / "KeyDrive.bat"
    sh_launcher = project_root / "keydrive.sh"
    readme_file = project_root / "README.md"
    
    if bat_launcher.exists():
        shutil.copy2(bat_launcher, launcher_path / "KeyDrive.bat")
        log("  Copied KeyDrive.bat (Windows launcher)")
    if sh_launcher.exists():
        shutil.copy2(sh_launcher, launcher_path / "keydrive.sh")
        log("  Copied keydrive.sh (Linux/macOS launcher)")
    if readme_file.exists():
        shutil.copy2(readme_file, launcher_path / "README.md")
        log("  Copied README.md (documentation)")
    
    # Copy encrypted keyfile
    shutil.copy2(encrypted_keyfile, target_keys / "keyfile.vc.gpg")
    log("  Copied keyfile.vc.gpg")
    
    # Create config.json
    # Note: json.dump handles backslash escaping automatically
    config = {
        "version": VERSION,
        "encrypted_keyfile": "../keys/keyfile.vc.gpg",
        "windows": {
            "volume_path": payload_device,
            "mount_letter": mount_letter,
            "veracrypt_path": ""
        },
        "unix": {
            "volume_path": payload_device,
            "mount_point": "~/veradrive"
        }
    }
    
    config_path = target_scripts / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    log("  Created config.json")
    
    log("✓ Scripts deployed successfully")
    return True


def deploy_scripts_extended(
    launcher_path: Path, 
    payload_device: str, 
    encrypted_keyfile: Path = None,
    plain_keyfile: Path = None,
    mount_letter: str = "V",
    use_keyfile: bool = True,
    use_gpg: bool = True
) -> bool:
    """
    Copy scripts and create config on LAUNCHER partition.
    Supports all security modes: password-only, plain keyfile, GPG-encrypted keyfile.
    
    New folder structure:
    LAUNCHER/
    ├── KeyDrive.bat
    ├── keydrive.sh
    └── .smartdrive/
        ├── scripts/
        ├── keys/
        └── integrity/
    """
    log("Deploying scripts to LAUNCHER partition...")
    
    scripts_dir = Path(__file__).resolve().parent
    project_root = scripts_dir.parent
    
    # New folder structure: all data under .smartdrive
    smartdrive_dir = launcher_path / ".smartdrive"
    target_scripts = smartdrive_dir / "scripts"
    target_keys = smartdrive_dir / "keys"
    target_integrity = smartdrive_dir / "integrity"
    
    # Create directories
    target_scripts.mkdir(parents=True, exist_ok=True)
    target_keys.mkdir(parents=True, exist_ok=True)
    target_integrity.mkdir(parents=True, exist_ok=True)
    
    # Copy scripts
    scripts_to_copy = ["smartdrive.py", "mount.py", "unmount.py", "rekey.py", "keyfile.py"]
    for script in scripts_to_copy:
        src = scripts_dir / script
        if src.exists():
            shutil.copy2(src, target_scripts / script)
            log(f"  Copied {script}")
    
    # Copy launcher scripts and docs to root of LAUNCHER partition
    bat_launcher = project_root / "KeyDrive.bat"
    sh_launcher = project_root / "keydrive.sh"
    readme_file = project_root / "README.md"
    
    if bat_launcher.exists():
        shutil.copy2(bat_launcher, launcher_path / "KeyDrive.bat")
        log("  Copied KeyDrive.bat (Windows launcher)")
    if sh_launcher.exists():
        shutil.copy2(sh_launcher, launcher_path / "keydrive.sh")
        log("  Copied keydrive.sh (Linux/macOS launcher)")
    if readme_file.exists():
        shutil.copy2(readme_file, launcher_path / "README.md")
        log("  Copied README.md (documentation)")
    
    # Handle keyfile based on security mode
    keyfile_config = None
    
    if use_keyfile:
        if use_gpg and encrypted_keyfile:
            # GPG-encrypted keyfile
            shutil.copy2(encrypted_keyfile, target_keys / "keyfile.vc.gpg")
            log("  Copied keyfile.vc.gpg (GPG-encrypted)")
            keyfile_config = "../keys/keyfile.vc.gpg"
        elif plain_keyfile:
            # Plain keyfile (not encrypted)
            shutil.copy2(plain_keyfile, target_keys / "keyfile.vc")
            log("  Copied keyfile.vc (plain keyfile)")
            keyfile_config = "../keys/keyfile.vc"
    else:
        log("  No keyfile (password-only mode)")
    
    # Get current date for metadata
    from datetime import datetime
    setup_date = datetime.now().strftime("%Y-%m-%d")
    
    # Create config.json with metadata
    config = {
        "version": VERSION,
        "drive_name": None,  # User can set this later
        "security_mode": "yubikey" if use_gpg else ("keyfile" if use_keyfile else "password"),
        "setup_date": setup_date,
        "last_password_change": setup_date,  # Initial setup counts as password set
        "windows": {
            "volume_path": payload_device,
            "mount_letter": mount_letter,
            "veracrypt_path": ""
        },
        "unix": {
            "volume_path": payload_device,
            "mount_point": "~/veradrive"
        }
    }
    
    if keyfile_config:
        config["keyfile"] = keyfile_config
        if use_gpg:
            config["encrypted_keyfile"] = keyfile_config
    
    config_path = target_scripts / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    log("  Created config.json")
    
    log("✓ Scripts deployed successfully")
    return True


def sign_deployed_scripts(launcher_path: Path, gpg_fingerprint: str = None) -> bool:
    """
    Sign deployed scripts with GPG for integrity verification.
    
    Args:
        launcher_path: Path to LAUNCHER partition
        gpg_fingerprint: Optional specific GPG key to use for signing
        
    Returns:
        True if signing succeeded, False otherwise
    """
    import hashlib
    
    log("Signing scripts for integrity verification...")
    
    # New folder structure
    smartdrive_dir = launcher_path / ".smartdrive"
    target_scripts = smartdrive_dir / "scripts"
    target_integrity = smartdrive_dir / "integrity"
    
    # Ensure integrity directory exists
    target_integrity.mkdir(parents=True, exist_ok=True)
    
    hash_file = target_integrity / "scripts.sha256"
    sig_file = target_integrity / "scripts.sha256.sig"
    
    # Calculate hash of all scripts
    hash_obj = hashlib.sha256()
    scripts = sorted([
        "smartdrive.py", "mount.py", "unmount.py",
        "rekey.py", "keyfile.py"
    ])
    
    for script_name in scripts:
        script_path = target_scripts / script_name
        if script_path.exists():
            hash_obj.update(script_name.encode('utf-8'))
            with open(script_path, 'rb') as f:
                hash_obj.update(f.read())
    
    script_hash = hash_obj.hexdigest()
    
    # Write hash file
    with open(hash_file, 'w') as f:
        f.write(f"{script_hash}  scripts\n")
    log(f"  Created {hash_file.name}")
    
    # Sign with GPG
    gpg_cmd = ["gpg", "--detach-sign"]
    if gpg_fingerprint:
        gpg_cmd.extend(["--default-key", gpg_fingerprint])
    gpg_cmd.append(str(hash_file))
    
    try:
        result = subprocess.run(
            gpg_cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and sig_file.exists():
            log(f"  Created {sig_file.name}")
            log("✓ Scripts signed successfully")
            return True
        else:
            warn(f"GPG signing failed: {result.stderr}")
            return False
    except Exception as e:
        warn(f"Could not sign scripts: {e}")
        return False


# =============================================================================
# Main Wizard
# =============================================================================

def print_banner():
    """Print welcome banner."""
    print("\n" + "="*70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║           SmartDrive Setup Wizard v1.0                        ║")
    print("  ║   Encrypted External Drive with YubiKey + VeraCrypt           ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("="*70)


def print_phase(num: int, total: int, title: str):
    """Print phase header."""
    print(f"\n{'─'*70}")
    print(f"  PHASE {num}/{total}: {title}")
    print(f"{'─'*70}\n")


def main() -> int:
    print_banner()
    
    system = platform.system().lower()
    
    # ==========================================================================
    # Pre-flight checks
    # ==========================================================================
    
    print("\nChecking requirements...\n")
    
    # Check admin privileges
    if not is_admin():
        error("This script requires administrator/root privileges!")
        if "windows" in system:
            print("\nRight-click and 'Run as Administrator', or run from elevated PowerShell.")
        else:
            print("\nRun with: sudo python setup.py")
        return 1
    log("✓ Running with administrator privileges")
    
    # Check GPG
    if not have("gpg"):
        error("gpg not found! Please install GnuPG.")
        return 1
    log("✓ GPG available")
    
    # Check VeraCrypt
    if "windows" in system:
        vc_exe = find_veracrypt_windows()
        if not vc_exe:
            error("VeraCrypt not found! Please install from veracrypt.fr")
            return 1
        log(f"✓ VeraCrypt found: {vc_exe}")
    else:
        if not have("veracrypt"):
            error("veracrypt not found in PATH!")
            return 1
        vc_exe = Path(shutil.which("veracrypt"))
        log("✓ VeraCrypt available")
    
    # ==========================================================================
    # PHASE 1: Drive Selection
    # ==========================================================================
    
    print_phase(1, 5, "DRIVE SELECTION")
    
    if "windows" in system:
        drives = get_drives_windows()
    else:
        drives = get_drives_unix()
    
    if not drives:
        error("No drives detected!")
        return 1
    
    selected_drive = select_drive(drives, system)
    if not selected_drive:
        log("Setup cancelled.")
        return 0
    
    if "windows" in system:
        drive_id = f"Disk {selected_drive['number']}"
        drive_name = selected_drive['name']
        drive_size = selected_drive['size_gb']
    else:
        drive_id = selected_drive['name']
        drive_name = selected_drive.get('model', drive_id)
        drive_size = selected_drive.get('size', '?')
    
    print(f"\n✓ Selected: {drive_id} - {drive_name} ({drive_size} GB)")
    
    # ==========================================================================
    # PHASE 2: Configuration
    # ==========================================================================
    
    print_phase(2, 5, "CONFIGURATION")
    
    # Launcher size
    print(f"LAUNCHER partition size (scripts, ~{LAUNCHER_SIZE_MB}MB recommended)")
    size_input = input(f"Enter size in MB [{LAUNCHER_SIZE_MB}]: ").strip()
    launcher_size = int(size_input) if size_input.isdigit() else LAUNCHER_SIZE_MB
    
    # YubiKey fingerprints
    available_fprs = get_available_fingerprints()
    fingerprints = prompt_for_fingerprints(available_fprs)
    
    # Mount letter (Windows only)
    mount_letter = "V"
    if "windows" in system:
        letter_input = input(f"\nMount drive letter [{mount_letter}]: ").strip().upper()
        if letter_input and len(letter_input) == 1 and letter_input.isalpha():
            mount_letter = letter_input
    
    # ==========================================================================
    # PHASE 3: Review & Confirm
    # ==========================================================================
    
    print_phase(3, 5, "REVIEW & CONFIRM")
    
    print("The following operations will be performed:\n")
    print(f"  Target Drive:     {drive_id} - {drive_name}")
    print(f"  Drive Size:       {drive_size} GB")
    print(f"  LAUNCHER:         {launcher_size} MB (exFAT)")
    print(f"  PAYLOAD:          ~{float(str(drive_size).replace('G','')) - launcher_size/1024:.1f} GB (VeraCrypt encrypted)")
    print(f"  Mount Letter:     {mount_letter}: (Windows)")
    
    # Show security mode
    if not fingerprints:
        print(f"  Security Mode:    Password Only")
    elif fingerprints == ["PLAIN_KEYFILE"]:
        print(f"  Security Mode:    Password + Plain Keyfile")
    else:
        print(f"  Security Mode:    Password + YubiKey ({len(fingerprints)} key(s))")
    
    print(f"  Password:         (will be prompted after confirmation)")
    
    print("\n" + "!"*70)
    print("  ⚠️  WARNING: ALL DATA ON THIS DRIVE WILL BE PERMANENTLY ERASED!")
    print("  ⚠️  This action CANNOT be undone!")
    print("!"*70)
    
    if not confirm_destructive(
        "This will ERASE ALL DATA on the selected drive.",
        "ERASE"
    ):
        log("Setup cancelled by user.")
        return 0
    
    # ==========================================================================
    # PHASE 4: Execution
    # ==========================================================================
    
    print_phase(4, 5, "EXECUTION")
    
    tmp_keyfile = None
    tmp_encrypted = None
    
    try:
        # Step 1: Partition drive
        print("\n[1/5] Partitioning drive...")
        if "windows" in system:
            launcher_letter, payload_device = partition_drive_windows(
                selected_drive["number"],
                launcher_size
            )
            # Convert letter to path
            launcher_mount = Path(f"{launcher_letter}:\\")
        else:
            launcher_mount, payload_device = partition_drive_unix(
                selected_drive["name"],
                launcher_size
            )
            launcher_mount = Path(launcher_mount)
        
        # Step 2: Collect password and generate keyfile
        print("\n[2/5] Setting up encryption...")
        
        # Determine security mode
        use_keyfile = bool(fingerprints)  # False for password-only
        use_gpg = fingerprints and fingerprints != ["PLAIN_KEYFILE"]
        
        if use_keyfile:
            if use_gpg:
                print("\nChoose a password for VeraCrypt encryption.")
                print("This password + YubiKey will be required to access your data.\n")
            else:
                print("\nChoose a password for VeraCrypt encryption.")
                print("This password + keyfile will be required to access your data.\n")
        else:
            print("\nChoose a password for VeraCrypt encryption.")
            print("This password alone will be required to access your data.\n")
        
        while True:
            password = getpass("Enter VeraCrypt password: ")
            password2 = getpass("Confirm password: ")
            if password != password2:
                error("Passwords don't match!")
                continue
            break
        
        tmp_keyfile = None
        tmp_encrypted = None
        keyfile_data = None
        
        if use_keyfile:
            print("\nGenerating keyfile...")
            keyfile_data = generate_keyfile()
            
            # Write temporary plaintext keyfile for VeraCrypt
            tmp_keyfile = Path(tempfile.gettempdir()) / "smartdrive_setup_key.bin"
            with open(tmp_keyfile, "wb") as f:
                f.write(keyfile_data)
            
            if use_gpg:
                # Encrypt keyfile to YubiKeys
                tmp_encrypted = Path(tempfile.gettempdir()) / "smartdrive_setup_key.gpg"
                if not encrypt_keyfile_to_yubikeys(keyfile_data, fingerprints, tmp_encrypted):
                    raise RuntimeError("Failed to encrypt keyfile")
            else:
                # Plain keyfile mode - tmp_keyfile will be copied directly
                log("Using plain keyfile (not GPG-encrypted)")
        
        # Step 3: Create VeraCrypt volume
        print("\n[3/5] Creating VeraCrypt volume...")
        print("       (This may take several minutes...)\n")
        
        if "windows" in system:
            success = create_veracrypt_volume_windows(
                vc_exe, payload_device, password, tmp_keyfile  # tmp_keyfile is None for password-only
            )
        else:
            success = create_veracrypt_volume_unix(
                payload_device, password, tmp_keyfile  # tmp_keyfile is None for password-only
            )
        
        if not success:
            raise RuntimeError("VeraCrypt volume creation failed")
        
        # Step 4: Deploy scripts
        print("\n[4/5] Deploying scripts...")
        
        # Wait for LAUNCHER to be accessible
        time.sleep(2)
        
        if "windows" in system:
            # Re-check launcher path after partitioning
            ps_script = f"""
            (Get-Partition -DiskNumber {selected_drive['number']} | 
             Where-Object {{ $_.PartitionNumber -eq 1 }}).DriveLetter
            """
            result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
            launcher_letter = result.stdout.strip()
            if launcher_letter:
                launcher_mount = Path(f"{launcher_letter}:\\")
        
        if not launcher_mount.exists():
            raise RuntimeError(f"LAUNCHER partition not accessible at {launcher_mount}")
        
        # Deploy scripts with appropriate keyfile
        deploy_scripts_extended(
            launcher_mount, payload_device, 
            tmp_encrypted if use_gpg else None,
            tmp_keyfile if (use_keyfile and not use_gpg) else None,
            mount_letter,
            use_keyfile, use_gpg
        )
        
        # Sign scripts for integrity verification (only if GPG is available)
        if have("gpg"):
            print("\n" + "─" * 70)
            print("  OPTIONAL: Sign scripts for integrity verification")
            print("─" * 70)
            print("\n  Signing scripts allows you to verify they haven't been tampered with.")
            print("  This uses your GPG key (YubiKey if configured).\n")
            
            sign_choice = input("  Sign scripts now? [Y/n]: ").strip().lower()
            if sign_choice != 'n':
                # Use the same GPG key that was used for keyfile encryption
                gpg_key = fingerprints[0] if use_gpg else None
                sign_deployed_scripts(launcher_mount, gpg_key)
            else:
                log("  Skipped signing (you can sign later from the menu)")
        
        # Step 5: Cleanup temp files
        print("\n[5/5] Cleaning up...")
        
        # Secure delete of plaintext keyfile
        if tmp_keyfile and tmp_keyfile.exists():
            with open(tmp_keyfile, "wb") as f:
                f.write(secrets.token_bytes(KEYFILE_SIZE))  # Overwrite
            tmp_keyfile.unlink()
            log("✓ Temporary keyfile securely deleted")
        
        if tmp_encrypted and tmp_encrypted.exists():
            tmp_encrypted.unlink()
        
    except Exception as e:
        error(f"Setup failed: {e}")
        print("\nCleanup: Removing temporary files...")
        for tmp in [tmp_keyfile, tmp_encrypted]:
            try:
                if tmp and tmp.exists():
                    tmp.unlink()
            except:
                pass
        return 1
    
    # ==========================================================================
    # PHASE 5: Verification
    # ==========================================================================
    
    print_phase(5, 5, "VERIFICATION")
    
    print("Setup complete! Let's verify it works.\n")
    
    print("To test, run from the LAUNCHER partition:")
    print(f"  cd {launcher_mount / 'scripts'}")
    print(f"  python mount.py")
    print(f"\nYou'll need:")
    print(f"  - Your VeraCrypt password")
    if use_gpg:
        print(f"  - YubiKey + PIN")
    elif use_keyfile:
        print(f"  - Keyfile present on LAUNCHER partition")
    
    # ==========================================================================
    # Success!
    # ==========================================================================
    
    print("\n" + "="*70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║                    ✓ SETUP COMPLETE!                          ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("="*70)
    
    # Security mode-aware success message
    print(f"""
Your SmartDrive is ready!

  LAUNCHER partition: {launcher_mount}
    Contains: KeyDrive.bat, keydrive.sh
    Hidden folder: .smartdrive/ (scripts, keys, integrity)
    
  PAYLOAD partition: Encrypted with VeraCrypt
    Access via: Double-click KeyDrive.bat (Windows)
                or ./keydrive.sh (Linux/macOS)
    
Security:
  ✓ Data encrypted with AES-256 (VeraCrypt)""")
    
    if use_gpg:
        print(f"  ✓ Keyfile encrypted to {len(fingerprints)} YubiKey(s)")
        print(f"  ✓ Requires: Password + YubiKey + PIN")
        print("""
Next steps:
  1. Test mounting: Double-click KeyDrive.bat
  2. Store backup YubiKey in secure location
  3. Consider backing up .smartdrive/keys/keyfile.vc.gpg
""")
        # YubiKey-specific security recommendation
        print("─" * 70)
        print("  🔐 SECURITY RECOMMENDATION: Enable Touch for Signing")
        print("─" * 70)
        print("""
  To prevent attackers from re-signing scripts while your YubiKey is
  plugged in, enable touch requirement for GPG signing operations:

    ykman openpgp keys set-touch sig on

  This ensures physical touch is required for every signature, even if
  the YubiKey is already inserted.

  Check current policy with: ykman openpgp info
""")
    elif use_keyfile:
        print(f"  ✓ Plain keyfile stored on LAUNCHER partition")
        print(f"  ✓ Requires: Password + keyfile")
        print("""
Next steps:
  1. Test mounting: Double-click KeyDrive.bat
  2. Consider storing keyfile backup in secure location
  
⚠️  Note: Plain keyfile is NOT encrypted. Anyone with access to the
    LAUNCHER partition can copy it. Consider upgrading to YubiKey mode
    for stronger security.
""")
    else:
        print(f"  ✓ Password-only protection")
        print(f"  ✓ Requires: Password")
        print("""
Next steps:
  1. Test mounting: Double-click KeyDrive.bat
  2. Use a strong, unique password
  
⚠️  Note: Password-only mode provides basic protection. Consider
    upgrading to YubiKey mode for hardware-based 2FA security.
""")
    
    print("Enjoy your secure portable storage! 🔐\n")
    
    # ==========================================================================
    # Optional: Recovery Kit Generation
    # ==========================================================================
    
    print("\n" + "="*70)
    print("  OPTIONAL: EMERGENCY RECOVERY KIT")
    print("="*70)
    print("""
A recovery kit provides emergency access if you lose your YubiKey or password.
It generates a 24-word phrase that grants ONE-TIME access to your drive.

Security considerations:
  ✓ Provides backup access method
  ✓ Must be stored offline (printed, in safe)
  ⚠️  Phrase = full access (no 2FA)
  ✓ One-time use only (invalidated after recovery)

""")
    
    recovery_choice = input("Generate recovery kit now? [y/N]: ").strip().lower()
    if recovery_choice == 'y':
        print("\n" + "─"*70)
        print("Generating recovery kit...")
        print("─"*70 + "\n")
        
        # Switch to launcher directory to run recovery.py with --skip-auth flag
        # (during setup, user just authenticated so we skip re-authentication)
        original_dir = os.getcwd()
        try:
            os.chdir(launcher_mount / ".smartdrive" / "scripts")
            result = subprocess.run(
                [sys.executable, "recovery.py", "generate", "--skip-auth"],
                capture_output=False,
                text=True
            )
            if result.returncode == 0:
                log("✓ Recovery kit generated successfully")
            else:
                warn("Recovery kit generation failed or was cancelled")
        except Exception as e:
            warn(f"Could not generate recovery kit: {e}")
        finally:
            os.chdir(original_dir)
    else:
        print("\n  You can generate a recovery kit later from the SmartDrive menu:")
        print("  LAUNCHER Menu → [6] Recovery Kit → [1] Generate new recovery kit\n")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user (Ctrl+C)")
        sys.exit(1)
