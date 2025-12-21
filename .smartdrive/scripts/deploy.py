#!/usr/bin/env python3
"""
KeyDrive Initial Deployment Tool

Deploys KeyDrive GUI to external drives for the first time.
This creates the initial .smartdrive directory structure.

Usage:
    python deploy.py                    # Interactive deployment
    python deploy.py --drive G          # Deploy to specific drive
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from core.paths import Paths

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context
# After restructure: deploy.py is always at .smartdrive/scripts/deploy.py
# - In repo: repo/.smartdrive/scripts/deploy.py
# - On deployed drive: DRIVE:/.smartdrive/scripts/deploy.py

# Since both have .smartdrive structure, we check for repo markers to distinguish
_potential_repo_root = _script_dir.parent.parent  # parent of .smartdrive

# Check if we're in the development repo (has .git directory at root)
_is_repo = (_potential_repo_root / ".git").exists()

if _is_repo:
    # Development context: repo/.smartdrive/scripts/deploy.py
    REPO_ROOT = _potential_repo_root
    REPO_SMARTDRIVE = _script_dir.parent  # repo/.smartdrive
else:
    # Deployed context - can't deploy from deployed drive
    print("❌ Cannot run deploy.py from deployed drive. Run from development repository.")
    sys.exit(1)

# Add .smartdrive to path for core imports
if str(REPO_SMARTDRIVE) not in sys.path:
    sys.path.insert(0, str(REPO_SMARTDRIVE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.constants import Branding, FileNames

# Import PathResolver for SSOT path management
from core.path_resolver import RuntimePaths, consolidate_duplicates
from core.platform import is_windows as _is_windows
from core.platform import windows_create_shortcut, windows_set_attributes

# Get product name from variables (optional)
try:
    from variables import PRODUCT_NAME
except ImportError:
    PRODUCT_NAME = Branding.PRODUCT_NAME

# =============================================================================
# Logging - Structured log events
# =============================================================================
import logging

_deploy_logger = logging.getLogger("smartdrive.deploy")


def _log_deploy(event: str, **kwargs) -> None:
    """Emit structured deploy log event."""
    details = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    _deploy_logger.info(f"{event}{': ' + details if details else ''}")


def get_available_drives():
    """Get list of available drive letters."""
    drives = []
    for drive in "DEFGHIJKLMNOPQRSTUVWXYZ":
        path = f"{drive}:\\"
        if os.path.exists(path):
            drives.append(drive)
    return drives


def select_drive_interactive():
    """Interactive drive selection."""
    drives = get_available_drives()

    if not drives:
        print("❌ No external drives found (D:-Z:)")
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
            choice = input("\nSelect drive to deploy to (number or letter): ").strip().upper()

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


# =============================================================================
# Deployed Layout Verification (per AGENT_ARCHITECTURE.md §17)
# =============================================================================

# =============================================================================
# PAYLOAD MANIFEST - Single Source of Truth for deployment completeness
# =============================================================================

# P1 Payload Manifest: All files required for a complete deployed .smartdrive
# This is the SSOT for what deploy.py copies and update.py validates.

PAYLOAD_MANIFEST = {
    # Core SSOT modules (MANDATORY - operations abort if missing)
    "core": {
        "files": [
            ("__init__.py", "SSOT module init", True),
            (FileNames.VERSION_PY, "VERSION constant", True),
            (FileNames.CONSTANTS_PY, "ConfigKeys, UserInputs, SecurityMode", True),
            (FileNames.PATHS_PY, "Paths class for path resolution", True),
            (FileNames.LIMITS_PY, "Limits class for validation bounds", True),
            (FileNames.MODES_PY, "SecurityMode enum definitions", True),
            (FileNames.PLATFORM_PY, "Platform detection utilities", True),
            (FileNames.SAFETY_PY, "DiskIdentity, PartitionRef guardrails", True),
        ],
        "critical": True,  # Abort deployment if any missing
    },
    # Runtime scripts (functional modules)
    "scripts": {
        "files": [
            (FileNames.GUI_PY, "Main GUI application", True),
            (FileNames.GUI_LAUNCHER_PY, "GUI launcher script", True),
            (FileNames.GUI_I18N_PY, "GUI internationalization", True),
            (FileNames.KEYDRIVE_PY, "Unified CLI interface", True),
            (FileNames.CLI_I18N_PY, "CLI internationalization", False),  # Optional
            (FileNames.MOUNT_PY, "Volume mounting", True),
            (FileNames.UNMOUNT_PY, "Volume unmounting", True),
            (FileNames.KEYFILE_PY, "Keyfile management", True),
            (FileNames.RECOVERY_PY, "Recovery kit generation", True),
            (FileNames.RECOVERY_CONTAINER_PY, "Recovery crypto container", True),
            (FileNames.REKEY_PY, "Password/keyfile rotation", True),
            (FileNames.SETUP_PY, "Setup wizard", True),
            (FileNames.UPDATE_PY, "Update functionality", True),
            (FileNames.VERSION_PY, "Version display", False),  # Legacy, optional
            (FileNames.CRYPTO_UTILS_PY, "Cryptographic utilities", True),
            (FileNames.VERACRYPT_CLI_PY, "VeraCrypt CLI wrapper", True),
            (FileNames.DEPLOY_PY, "Deployment tool (for re-deploy)", False),
        ],
        "critical": False,  # Warn but continue if non-required missing
    },
    # Static assets
    "static": {
        "files": [
            (FileNames.ICON_MAIN, "Application icon", True),
            (FileNames.ICON_MAIN_PNG, "Application logo", True),
        ],
        "critical": False,  # Icons missing degrades UX but doesn't break functionality
    },
}


def get_required_files_for_verification() -> dict:
    """
    Build REQUIRED_DEPLOYED_FILES dict from PAYLOAD_MANIFEST.

    Returns dict compatible with existing verify_deployed_layout().
    """
    required = {}
    for category, spec in PAYLOAD_MANIFEST.items():
        for filename, description, is_required in spec["files"]:
            if is_required:
                rel_path = f"{category}/{filename}"
                required[rel_path] = description
    return required


# Required files for a valid deployed .smartdrive layout
# Built from PAYLOAD_MANIFEST for backwards compatibility
REQUIRED_DEPLOYED_FILES = get_required_files_for_verification()


def verify_deployed_layout(smartdrive_dir: Path) -> tuple[bool, list[str]]:
    """
    Verify that a deployed .smartdrive directory has all required files.

    Per AGENT_ARCHITECTURE.md: If any required file is missing,
    operations MUST abort with explicit missing-file list.

    Args:
        smartdrive_dir: Path to .smartdrive directory

    Returns:
        (is_valid, missing_files): Tuple of validation result and missing file list
    """
    missing = []
    for rel_path, description in REQUIRED_DEPLOYED_FILES.items():
        full_path = smartdrive_dir / rel_path
        if not full_path.exists():
            missing.append(f"{rel_path} ({description})")

    return (len(missing) == 0, missing)


def deploy_to_drive(target_drive):
    """
    Deploy KeyDrive to the specified drive.

    Uses PathResolver as SSOT for all target paths.
    Copies 1:1 from repo/.smartdrive/ to DRIVE:/.smartdrive/ per AGENT_ARCHITECTURE.md.
    """
    # Use PathResolver as SSOT for target paths (cross-drive support)
    target_path = Path(f"{target_drive}:\\")

    # Create RuntimePaths for target (SSOT)
    target_paths = RuntimePaths.for_target(target_path, create_dirs=True)

    # Source directories from repo's canonical .smartdrive structure
    src_core = REPO_SMARTDRIVE / "core"
    src_scripts = REPO_SMARTDRIVE / "scripts"

    _log_deploy("deploy.start", target=str(target_path), source=str(REPO_SMARTDRIVE))

    print(f"\n🚀 Deploying {PRODUCT_NAME} to {target_drive}:\\")
    print(f"   Source: {REPO_SMARTDRIVE}")
    print(f"   Target: {target_paths.smartdrive_root}")

    # Directories already created by PathResolver.for_target()
    print("📁 Target directories created via PathResolver...")
    target_core = target_paths.smartdrive_root / "core"
    target_scripts = target_paths.scripts_root
    target_keys = target_paths.keys_dir

    target_core.mkdir(parents=True, exist_ok=True)
    target_scripts.mkdir(parents=True, exist_ok=True)
    target_keys.mkdir(parents=True, exist_ok=True)
    _log_deploy("deploy.directories.created")

    # Copy SSOT core modules 1:1 (MANDATORY - per AGENT_ARCHITECTURE.md §3)
    print("🔧 Copying SSOT core modules...")
    # Extract core files from PAYLOAD_MANIFEST (SSOT)
    core_manifest = PAYLOAD_MANIFEST.get("core", {}).get("files", [])
    core_files = [fname for fname, _, _ in core_manifest]
    missing_core = []
    for core_file in core_files:
        src = src_core / core_file
        dst = target_core / core_file
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ core/{core_file}")
        else:
            missing_core.append(core_file)
            print(f"  ❌ core/{core_file} MISSING")

    if missing_core:
        print(f"\n❌ FATAL: Missing SSOT core modules: {missing_core}")
        print("   Deployment ABORTED. core/* modules are required per AGENT_ARCHITECTURE.md.")
        return False

    # Copy runtime scripts 1:1 (use PAYLOAD_MANIFEST as SSOT)
    print("📋 Copying scripts...")
    # Extract script files from manifest
    script_manifest = PAYLOAD_MANIFEST.get("scripts", {}).get("files", [])
    script_files = [fname for fname, _, _ in script_manifest]

    for script in script_files:
        src = src_scripts / script
        dst = target_scripts / script
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {script}")
        else:
            print(f"  ⚠ {script} not found")

    # Copy keys (if they exist in repo)
    print("🔑 Copying keys...")
    repo_keys = REPO_ROOT / Paths.KEYS_SUBDIR
    if repo_keys.exists():
        for key_file in repo_keys.glob("*"):
            if key_file.is_file():
                shutil.copy2(key_file, target_keys)
                print(f"  ✓ {key_file.name}")
    else:
        print("  ℹ No keys directory found (expected for deployment)")

    # Copy docs into .smartdrive/docs (drive root must contain entrypoints only)
    print("📖 Copying documentation...")
    docs_dst = target_paths.smartdrive_root / "docs"
    docs_dst.mkdir(parents=True, exist_ok=True)
    readme_src = REPO_ROOT / FileNames.README
    gui_readme_src = REPO_ROOT / FileNames.GUI_README
    if readme_src.exists():
        shutil.copy2(readme_src, docs_dst / FileNames.README)
        print(f"  ✓ {FileNames.README}")
    if gui_readme_src.exists():
        shutil.copy2(gui_readme_src, docs_dst / FileNames.GUI_README)
        print(f"  ✓ {FileNames.GUI_README}")

    # Copy the compiled GUI executable into .smartdrive/scripts (preferred Windows entrypoint)
    exe_src = REPO_ROOT / "dist" / f"{PRODUCT_NAME}GUI.exe"
    exe_dst = target_scripts / f"{PRODUCT_NAME}GUI.exe"
    if exe_src.exists():
        shutil.copy2(exe_src, exe_dst)
        print(f"  ✓ {PRODUCT_NAME}GUI.exe copied")
        _log_deploy("deploy.executable.copied", file=f"{PRODUCT_NAME}GUI.exe")
    else:
        print(f"  ⚠ {PRODUCT_NAME}GUI.exe not found in dist/ (run PyInstaller first)")
        _log_deploy("deploy.executable.notfound", file=f"{PRODUCT_NAME}GUI.exe")

    # Copy static assets (MANDATORY - icons, images per AGENT_ARCHITECTURE.md)
    # Use PathResolver canonical static path (SSOT)
    # After restructure: static/ is inside .smartdrive/, not at repo root
    print("🎨 Copying static assets...")
    static_src = REPO_SMARTDRIVE / "static"  # .smartdrive/static/
    static_dst = target_paths.static_dir  # SSOT from PathResolver
    if static_src.exists():
        shutil.copytree(static_src, static_dst, dirs_exist_ok=True)
        # Count files for logging
        static_files = list(static_dst.rglob("*"))
        file_count = sum(1 for f in static_files if f.is_file())
        print(f"  ✓ static/ directory copied ({file_count} files)")
        _log_deploy("deploy.static.copied", path=str(static_dst), file_count=file_count)
    else:
        print("  ⚠ static/ directory not found")
        _log_deploy("deploy.static.notfound", source=str(static_src))

    # Create clean root entrypoints AFTER assets/exe are in place
    print("🔧 Creating root entrypoints...")

    if _is_windows():
        windows_set_attributes(target_paths.smartdrive_root, hidden=True)

    sh_src = REPO_ROOT / FileNames.SH_LAUNCHER
    sh_dst = target_path / FileNames.SH_LAUNCHER
    if sh_src.exists():
        shutil.copy2(sh_src, sh_dst)
        print(f"  ✓ {FileNames.SH_LAUNCHER} created")

    command_name = f"{PRODUCT_NAME}.command"
    command_path = target_path / command_name
    command_path.write_text(
        "#!/bin/bash\n"
        'cd "$(dirname "$0")"\n'
        f"chmod +x './{FileNames.SH_LAUNCHER}' 2>/dev/null || true\n"
        f"./{FileNames.SH_LAUNCHER}\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"  ✓ {command_name} created")

    if _is_windows():
        shortcut_name = Path(FileNames.BAT_LAUNCHER).with_suffix(".lnk").name
        shortcut_path = target_path / shortcut_name
        icon_path = target_paths.static_dir / FileNames.ICON_MAIN

        if exe_dst.exists():
            windows_create_shortcut(
                shortcut_path=shortcut_path,
                target_path=exe_dst,
                working_dir=target_path,
                icon_path=icon_path,
                description=f"{PRODUCT_NAME} (GUI)",
            )
            print(f"  ✓ {shortcut_name} created")
        else:
            print(f"  ⚠ {PRODUCT_NAME}GUI.exe not available; shortcut not created")

    _log_deploy("deploy.entrypoints.created")

    # Verify deployed layout (per AGENT_ARCHITECTURE.md)
    print("\n🔍 Verifying deployed layout...")
    is_valid, missing = verify_deployed_layout(target_paths.smartdrive_root)
    if not is_valid:
        _log_deploy("deploy.verify.failed", missing_count=len(missing))
        print(f"\n❌ DEPLOYMENT FAILED: Missing required files:")
        for m in missing:
            print(f"   ❌ {m}")
        print("\nDeployment is incomplete. Cannot proceed.")
        return False
    print("  ✓ All required files present")

    # Check for duplicates (SSOT enforcement)
    print("🔍 Checking for duplicates...")
    duplicates = target_paths.detect_duplicates()
    if duplicates:
        print("  ❌ DUPLICATES DETECTED:")
        for resource, paths in duplicates.items():
            print(f"     {resource}: {len(paths)} locations")
            for p in paths:
                print(f"       - {p}")
        print("\n  Attempting to consolidate...")
        actions = consolidate_duplicates(target_paths, dry_run=False)
        if actions["errors"]:
            print("  ❌ Consolidation failed:")
            for err in actions["errors"]:
                print(f"     {err}")
            return False
        print("  ✓ Duplicates consolidated")
    else:
        print("  ✓ No duplicates found")

    _log_deploy("deploy.verify.success")

    _log_deploy("deploy.complete", target=str(target_path))
    print(f"\n✅ Deployment complete!")
    if _is_windows():
        print(f"🚀 Launch {PRODUCT_NAME} from: {target_path / Path(FileNames.BAT_LAUNCHER).with_suffix('.lnk').name}")
    print(f"🚀 Launch on Linux from: {target_path / FileNames.SH_LAUNCHER}")
    print(f"🚀 Launch on macOS from: {target_path / f'{PRODUCT_NAME}.command'}")
    print(f"📂 {PRODUCT_NAME} files are in: {target_paths.smartdrive_root}")
    print(f"📂 Config will be at: {target_paths.config_file}")
    print(f"📂 Static assets at: {target_paths.static_dir}")

    return True


def main():
    """Main deployment function."""
    print(f"🎯 {PRODUCT_NAME} Initial Deployment Tool")
    print("=" * 40)

    target_drive = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("--drive"):
        if len(sys.argv) > 2:
            target_drive = sys.argv[2].upper()
        else:
            print("❌ --drive requires a drive letter (e.g., --drive G)")
            sys.exit(1)

    if not target_drive:
        target_drive = select_drive_interactive()

    if not target_drive:
        print("❌ No drive selected.")
        sys.exit(1)

    # Confirm deployment
    target_path = Path(f"{target_drive}:\\")
    smartdrive_dir = target_path / ".smartdrive"

    if smartdrive_dir.exists():
        print(f"\n⚠️  {PRODUCT_NAME} is already deployed to {target_drive}:\\")
        response = input("Overwrite existing deployment? (y/N): ").strip().lower()
        if response != "y":
            print("❌ Deployment cancelled.")
            sys.exit(0)

    success = deploy_to_drive(target_drive)
    if success:
        print("\n🎉 Ready to test! Run the launcher and configure config.json for your setup.")
        sys.exit(0)
    else:
        print("❌ Deployment failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
