#!/usr/bin/env python3
"""
SmartDrive Update Deployment Tool

Safely updates SmartDrive scripts and documentation from development
environment to deployment drives without overwriting user data.

Usage:
    python update.py                    # Interactive mode
    python update.py --drive G          # Update specific drive
    python update.py --dry-run          # Preview changes
"""

import os
import shutil
import sys
import json
from pathlib import Path
from typing import List, Set
from datetime import datetime

# Configuration
DEV_SCRIPTS = Path(__file__).parent  # scripts/ directory
DEV_ROOT = Path(__file__).parent.parent  # project root

# Current SmartDrive version
try:
    from version import VERSION as CURRENT_VERSION
except ImportError:
    CURRENT_VERSION = "1.0.0"  # Fallback

# Files to update (patterns)
FILES_TO_UPDATE = [
    "*.py",           # All Python scripts
    "README.md",      # Documentation
    "requirements.txt", # Dependencies
    "*.bat",          # Windows launchers
    "*.sh"            # Unix launchers
]

# Files/folders to NEVER overwrite (user data)
# Note: config.json user data is protected, but version metadata is updated
PROTECTED = {
    "keys",           # Keyfiles directory
    "integrity",      # Signatures directory
    "recovery_kits"   # Recovery documents
}

def log(msg: str, level: str = "INFO"):
    """Log message with level."""
    print(f"[{level}] {msg}")

def error(msg: str):
    """Log error message."""
    log(msg, "ERROR")

def warn(msg: str):
    """Log warning message."""
    log(msg, "WARN")

def get_available_drives() -> List[str]:
    """Get list of available drive letters."""
    drives = []
    for drive in "DEFGHIJKLMNOPQRSTUVWXYZ":
        path = f"{drive}:\\"
        if os.path.exists(path):
            drives.append(drive)
    return drives

def select_drive_interactive() -> str:
    """Interactive drive selection."""
    drives = get_available_drives()
    
    if not drives:
        error("No external drives found (D:-Z:)")
        return None
    
    print("\nAvailable drives:")
    for i, drive in enumerate(drives, 1):
        path = f"{drive}:\\"
        try:
            # Get drive label if possible
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volume_name = ctypes.create_unicode_buffer(1024)
            file_system = ctypes.create_unicode_buffer(1024)
            kernel32.GetVolumeInformationW(path, volume_name, 1024, None, None, None, file_system, 1024)
            label = volume_name.value or "No Label"
        except:
            label = "Unknown"
        print(f"  [{i}] {drive}:\\ - {label}")
    
    while True:
        try:
            choice = input("\nSelect drive to update (number or letter): ").strip().upper()
            
            # Check if it's a number
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(drives):
                    return drives[idx]
                else:
                    print("Invalid number.")
                    continue
            
            # Check if it's a drive letter
            if len(choice) == 1 and choice in drives:
                return choice
            
            print("Invalid choice. Enter a number or drive letter.")
            
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None

def is_smartdrive_drive(drive_path: Path) -> bool:
    """Check if drive has SmartDrive installed."""
    smartdrive_dir = drive_path / ".smartdrive"
    config_file = smartdrive_dir / "scripts" / "config.json"
    return config_file.exists()

def get_files_to_update() -> List[Path]:
    """Get list of files to update from dev environment."""
    files = []
    
    # Get files from scripts directory
    for pattern in FILES_TO_UPDATE:
        for src in DEV_SCRIPTS.glob(pattern):
            if src.is_file():
                # Skip protected files
                if src.name in PROTECTED:
                    continue
                files.append(src)
    
    # Add top-level README
    readme = DEV_ROOT / "README.md"
    if readme.exists():
        files.append(readme)
    
    return files

def preview_update(target_drive: str, dry_run: bool = True) -> List[tuple]:
    """Preview what will be updated."""
    target_path = Path(f"{target_drive}:\\")
    target_scripts = target_path / ".smartdrive" / "scripts"
    
    changes = []
    files_to_update = get_files_to_update()
    
    for src in files_to_update:
        if src.name == "README.md" and src.parent == DEV_ROOT:
            # Top-level README goes to drive root
            dst = target_path / "README.md"
        else:
            # Scripts go to .smartdrive/scripts/
            dst = target_scripts / src.name
        
        action = "COPY"
        if dst.exists():
            # Check if different
            try:
                if src.stat().st_mtime > dst.stat().st_mtime:
                    action = "UPDATE"
                else:
                    action = "SKIP (same)"
            except:
                action = "UPDATE"
        
        changes.append((src, dst, action))
    
    if dry_run:
        print(f"\n{'─' * 70}")
        print(f"  UPDATE PREVIEW: {target_drive}:\\")
        print(f"{'─' * 70}\n")
        
        for src, dst, action in changes:
            if action != "SKIP (same)":
                print(f"  {action}: {dst}")
        
        skipped = sum(1 for _, _, a in changes if a == "SKIP (same)")
        if skipped:
            print(f"  SKIP: {skipped} files unchanged")
        
        print(f"\n  Protected (never overwritten): {', '.join(PROTECTED)}")
        print(f"  Note: config.json version will be updated to {CURRENT_VERSION}")
    
    return changes

def perform_update(target_drive: str, dry_run: bool = False) -> bool:
    """Perform the update."""
    target_path = Path(f"{target_drive}:\\")
    
    if not target_path.exists():
        error(f"Drive {target_drive}:\\ not found")
        return False
    
    # Check if it's a SmartDrive drive
    if not is_smartdrive_drive(target_path):
        warn(f"Drive {target_drive}:\\ doesn't appear to have SmartDrive installed")
        confirm = input("Continue anyway? [y/N]: ").strip().lower()
        if confirm != 'y':
            return False
    
    # Preview
    changes = preview_update(target_drive, dry_run=True)
    
    if dry_run:
        return True
    
    # Confirm
    print()
    confirm = input("Proceed with update? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("Update cancelled.")
        return False
    
    # Perform update
    print(f"\n{'─' * 70}")
    print("  PERFORMING UPDATE")
    print(f"{'─' * 70}\n")
    
    target_scripts = target_path / ".smartdrive" / "scripts"
    target_scripts.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    error_count = 0
    
    for src, dst, action in changes:
        if action == "SKIP (same)":
            continue
        
        try:
            shutil.copy2(src, dst)
            print(f"  ✓ {dst.name}")
            success_count += 1
        except Exception as e:
            error(f"Failed to copy {src.name}: {e}")
            error_count += 1
    
    # Update config.json version (only if version actually changed)
    config_path = target_scripts / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            current_config_version = config.get("version")
            
            # Only update if the version in version.py is different
            if current_config_version != CURRENT_VERSION:
                config["version"] = CURRENT_VERSION
                config["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                print(f"  ✓ Updated version: {current_config_version or 'none'} → {CURRENT_VERSION}")
                success_count += 1
            # If version is already current, don't count it as an update
        
        except Exception as e:
            error(f"Failed to update config.json version: {e}")
            error_count += 1
    
    print(f"\n{'─' * 70}")
    print(f"  UPDATE COMPLETE")
    print(f"{'─' * 70}")
    print(f"  Updated: {success_count} files")
    if error_count:
        print(f"  Errors: {error_count} files")
    print(f"  Target: {target_drive}:\\")
    print(f"  Version: {CURRENT_VERSION}")
    
    return error_count == 0

def update_deployment_drive(target_drive: str = None, dry_run: bool = False) -> bool:
    """
    Update a deployment drive with latest SmartDrive files.
    
    Args:
        target_drive: Drive letter (e.g., 'G'), or None for interactive selection
        dry_run: If True, only preview changes
    
    Returns:
        True if successful
    """
    if target_drive is None:
        target_drive = select_drive_interactive()
        if not target_drive:
            return False
    
    return perform_update(target_drive, dry_run)

# For backward compatibility and direct execution
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Update SmartDrive deployment drives")
    parser.add_argument("--drive", "-d", help="Target drive letter (e.g., G)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating")
    
    args = parser.parse_args()
    
    if args.drive:
        update_deployment_drive(args.drive, args.dry_run)
    else:
        update_deployment_drive(dry_run=args.dry_run)