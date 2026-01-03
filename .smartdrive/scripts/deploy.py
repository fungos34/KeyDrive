#!/usr/bin/env python3
"""
KeyDrive Initial Deployment Tool

Deploys KeyDrive GUI to external drives for the first time.
This creates the initial .smartdrive directory structure.

Usage:
    python deploy.py                              # Interactive deployment
    python deploy.py --drive G                    # Deploy to Windows drive G:
    python deploy.py --drive /media/user/USBDrive # Deploy to Linux/macOS mount point
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

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

# BUG-20260102-005 FIX: Import core modules AFTER sys.path setup
from core.constants import Branding, FileNames

# Import PathResolver for SSOT path management
from core.path_resolver import RuntimePaths, consolidate_duplicates
from core.paths import Paths
from core.platform import get_platform as _get_platform
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


# =============================================================================
# BUG-20260102-010: Pre-deployment cleanup to prevent storage accumulation
# =============================================================================


def _get_os_venv_dir_name() -> str:
    """
    Get the OS-specific venv directory name for the current platform.

    BUG-20260102-012: Returns .venv-win, .venv-linux, or .venv-mac based on OS.
    """
    platform = _get_platform().lower()
    if platform == "windows":
        return FileNames.VENV_DIR_WIN
    elif platform == "darwin":
        return FileNames.VENV_DIR_MAC
    else:  # Linux and other Unix-like
        return FileNames.VENV_DIR_LINUX


def _handle_remove_readonly(func, path, exc_info):
    """
    Error handler for shutil.rmtree to handle Windows read-only files.

    Windows sets read-only attribute on some files, preventing deletion.
    This handler clears the attribute and retries.
    """
    import stat

    # Clear the read-only attribute and retry
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _cleanup_existing_smartdrive(smartdrive_dir: Path) -> bool:
    r"""
    Clean up existing .smartdrive directory before deployment.

    BUG-20260102-010: Ensures storage doesn't accumulate between deployments.

    On Windows:
    - Clears hidden attribute before deletion
    - Handles read-only files
    - Handles long paths via \\?\ prefix when needed

    Args:
        smartdrive_dir: Path to the .smartdrive directory to clean

    Returns:
        True if cleanup succeeded (or directory didn't exist), False on failure
    """
    if not smartdrive_dir.exists():
        return True

    _log_deploy("deploy.cleanup.start", path=str(smartdrive_dir))
    print(f"🧹 Cleaning up existing deployment at {smartdrive_dir}...")

    try:
        if _is_windows():
            # Clear hidden attribute first
            try:
                windows_set_attributes(smartdrive_dir, hidden=False)
            except Exception as e:
                _log_deploy("deploy.cleanup.attrib_warning", error=str(e))

            # For Windows, convert to long path format to handle >260 char paths
            # This is common with nested venv directories
            long_path = str(smartdrive_dir)
            if not long_path.startswith("\\\\?\\") and len(long_path) > 200:
                long_path = "\\\\?\\" + os.path.abspath(long_path)

            shutil.rmtree(long_path, onerror=_handle_remove_readonly)
        else:
            # Unix: simple rmtree
            shutil.rmtree(smartdrive_dir)

        _log_deploy("deploy.cleanup.success", path=str(smartdrive_dir))
        print(f"  ✓ Removed existing .smartdrive directory")
        return True

    except Exception as e:
        _log_deploy("deploy.cleanup.error", path=str(smartdrive_dir), error=str(e))
        print(f"  ❌ Failed to clean up: {e}")
        print(f"     You may need to manually delete: {smartdrive_dir}")
        return False


def _copy_shell_script_with_unix_endings(src: Path, dst: Path) -> bool:
    """
    Copy a shell script ensuring Unix (LF) line endings.

    BUG-20260102-011: Shell scripts deployed from Windows must have Unix line endings
    to work when the drive is used on Linux/macOS.

    Args:
        src: Source script path
        dst: Destination script path

    Returns:
        True if copy succeeded, False otherwise
    """
    try:
        # Read the file content
        content = src.read_text(encoding="utf-8")
        # Write with explicit Unix line endings
        dst.write_text(content, encoding="utf-8", newline="\n")
        return True
    except Exception as e:
        _log_deploy("deploy.shell_script.error", src=str(src), error=str(e))
        return False


def get_available_drives():
    """Get list of available drives/mount points based on platform."""
    if _is_windows():
        # Windows: scan drive letters D-Z
        drives = []
        for drive in "DEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{drive}:\\"
            if os.path.exists(path):
                drives.append(drive)
        return drives
    else:
        # Linux/macOS: scan common mount points for removable media
        mount_points = []
        # Linux mount locations
        linux_media_paths = [
            Path("/media"),  # Ubuntu/Debian auto-mount
            Path("/run/media"),  # Fedora/Arch auto-mount
            Path("/mnt"),  # Manual mounts
        ]
        # macOS mount location
        macos_volumes = Path("/Volumes")

        for media_base in linux_media_paths:
            if media_base.exists():
                # Check for user subdirectories (e.g., /media/username/)
                for user_dir in media_base.iterdir():
                    if user_dir.is_dir():
                        for mount in user_dir.iterdir():
                            if mount.is_dir() and _is_likely_removable(mount):
                                mount_points.append(mount)

        if macos_volumes.exists():
            for volume in macos_volumes.iterdir():
                # Skip system volumes
                if volume.name not in ("Macintosh HD", "Recovery", "Preboot", "VM", "Data"):
                    if volume.is_dir():
                        mount_points.append(volume)

        return mount_points


def _is_likely_removable(path: Path) -> bool:
    """Check if a mount point is likely a removable drive (heuristic)."""
    try:
        # Check if it's a mount point (different device than parent)
        if path.stat().st_dev == path.parent.stat().st_dev:
            return False  # Same device as parent, not a separate mount
        # Basic writability check
        return os.access(path, os.W_OK)
    except (OSError, PermissionError):
        return False


def select_drive_interactive():
    """Interactive drive selection (cross-platform)."""
    drives = get_available_drives()

    if not drives:
        if _is_windows():
            print("❌ No external drives found (D:-Z:)")
        else:
            print("❌ No external drives found in /media, /run/media, /mnt, or /Volumes")
            print("   Tip: Use --drive /path/to/mount to specify a path directly.")
        return None

    print("\nAvailable drives:")
    if _is_windows():
        # Windows: show drive letters with labels
        for i, drive in enumerate(drives, 1):
            path = f"{drive}:\\"
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                volume_name = ctypes.create_unicode_buffer(1024)
                file_system = ctypes.create_unicode_buffer(1024)
                kernel32.GetVolumeInformationW(path, volume_name, 1024, None, None, None, file_system, 1024)
                label = volume_name.value or "No Label"
            except Exception:
                label = "Unknown"
            print(f"  [{i}] {drive}:\\ - {label}")
    else:
        # Linux/macOS: show mount paths
        for i, mount_path in enumerate(drives, 1):
            print(f"  [{i}] {mount_path}")

    while True:
        try:
            choice = input("\nSelect drive to deploy to (number): ").strip()

            # Check if it's a number
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(drives):
                    return drives[idx]
                else:
                    print("Invalid number.")
                    continue

            # Windows: also accept drive letter directly
            if _is_windows() and len(choice) == 1 and choice.upper() in drives:
                return choice.upper()

            print("Invalid choice. Enter a number from the list.")

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
    # BUG-20260102-009: Added ALL core/*.py modules - gui.py requires all of them
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
            (FileNames.DEPENDENCIES_PY, "Dependency checking module", True),
            (FileNames.RESOURCES_PY, "Resource resolution (icons, assets)", True),
            (FileNames.CONFIG_PY, "Config file handling", True),
            # Additional core modules required by gui.py and scripts
            ("single_instance.py", "Single instance manager", True),
            ("clipboard.py", "Clipboard utilities", True),
            ("context.py", "Runtime context management", True),
            ("filesystems.py", "Filesystem utilities", True),
            ("formatting.py", "Output formatting utilities", True),
            ("integrity.py", "File integrity checking", True),
            ("path_resolver.py", "Path resolution utilities", True),
            ("qr_chain.py", "QR code chain generation", True),
            ("secrets.py", "Secrets management", True),
            ("settings_schema.py", "Settings schema definitions", True),
            ("tray.py", "System tray support", True),
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
            (FileNames.BOOTSTRAP_DEPENDENCIES_PY, "Dependency bootstrap script", True),
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

# BUG-20260102-005 FIX: requirements.txt is at .smartdrive root, not .smartdrive/root/
# It gets copied to target_paths.smartdrive_root / requirements.txt
# So verification should check for it at smartdrive root, not under a "root" subdirectory


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

    # BUG-20260102-005 FIX: Check requirements.txt at smartdrive root (not under "root" subdir)
    requirements_path = smartdrive_dir / FileNames.REQUIREMENTS_TXT
    if not requirements_path.exists():
        missing.append(f"{FileNames.REQUIREMENTS_TXT} (Python dependencies for pip install)")

    return (len(missing) == 0, missing)


def deploy_to_drive(target_drive):
    """
    Deploy KeyDrive to the specified drive.

    Uses PathResolver as SSOT for all target paths.
    Copies 1:1 from repo/.smartdrive/ to DRIVE:/.smartdrive/ per AGENT_ARCHITECTURE.md.

    Args:
        target_drive: Windows drive letter (e.g., 'G') or Path to mount point

    BUG-20260102-010: Now cleans up existing .smartdrive before deployment
    BUG-20260102-011: Shell scripts written with Unix line endings
    BUG-20260102-012: Uses OS-specific venv directory names
    """
    # Normalize target_drive to Path (cross-platform support)
    if isinstance(target_drive, Path):
        target_path = target_drive
    elif _is_windows() and len(str(target_drive)) == 1:
        # Windows drive letter
        target_path = Path(f"{target_drive}:\\")
    else:
        # Assume it's a path string (Linux/macOS mount point)
        target_path = Path(target_drive)

    # BUG-20260102-010: Clean up existing .smartdrive to prevent storage accumulation
    existing_smartdrive = target_path / ".smartdrive"
    if existing_smartdrive.exists():
        if not _cleanup_existing_smartdrive(existing_smartdrive):
            print("⚠️  Warning: Could not fully clean existing deployment.")
            print("    Deployment will continue, but some old files may remain.")

    # Create RuntimePaths for target (SSOT)
    target_paths = RuntimePaths.for_target(target_path, create_dirs=True)

    # Source directories from repo's canonical .smartdrive structure
    src_core = REPO_SMARTDRIVE / "core"
    src_scripts = REPO_SMARTDRIVE / "scripts"

    _log_deploy("deploy.start", target=str(target_path), source=str(REPO_SMARTDRIVE))

    print(f"\n🚀 Deploying {PRODUCT_NAME} to {target_path}")
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

    # CHG-20251229-002: Copy requirements.txt for platform-independent dependency installation
    print("📦 Copying requirements.txt for dependency bootstrap...")
    req_src = REPO_SMARTDRIVE / FileNames.REQUIREMENTS_TXT
    req_dst = target_paths.smartdrive_root / FileNames.REQUIREMENTS_TXT
    if req_src.exists():
        shutil.copy2(req_src, req_dst)
        print(f"  ✓ {FileNames.REQUIREMENTS_TXT}")
        _log_deploy("deploy.requirements.copied", file=FileNames.REQUIREMENTS_TXT)
    else:
        print(f"  ⚠ {FileNames.REQUIREMENTS_TXT} not found (dependency bootstrap may fail)")
        _log_deploy("deploy.requirements.notfound", source=str(req_src))

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

    # BUG-20251221-032: Copy tests directory for post-deployment verification
    # Tests MUST be deployed to target so verification runs against deployed code
    print("🧪 Copying tests...")
    tests_src = REPO_SMARTDRIVE / "tests"  # .smartdrive/tests/
    tests_dst = target_paths.smartdrive_root / "tests"  # target/.smartdrive/tests/
    if tests_src.exists():
        shutil.copytree(tests_src, tests_dst, dirs_exist_ok=True)
        # Count files for logging
        test_files = list(tests_dst.rglob("*.py"))
        file_count = len(test_files)
        print(f"  ✓ tests/ directory copied ({file_count} test files)")
        _log_deploy("deploy.tests.copied", path=str(tests_dst), file_count=file_count)
    else:
        print("  ⚠ tests/ directory not found (tests will not be deployed)")
        _log_deploy("deploy.tests.notfound", source=str(tests_src))

    # CHG-20260103-001: Virtual environments are NOT copied during deployment
    # They are auto-created and dependencies installed on first startup via bootstrap_dependencies.py
    # This reduces deployment size and ensures each OS creates its own compatible venv
    print("📦 Python environment: Will be auto-created on first startup")
    _log_deploy("deploy.venv.skipped", reason="auto_bootstrap_on_startup")

    # Create clean root entrypoints AFTER assets/exe are in place
    # BUG-20260102-006: Copy ALL launcher files from repo root to ensure consistency
    print("🔧 Creating root entrypoints...")

    if _is_windows():
        windows_set_attributes(target_paths.smartdrive_root, hidden=True)

    # Define all launcher files that should be copied from repo root to drive root
    # CHG-20260102-007: Removed KeyDriveGUI.bat (redundant - KeyDrive.bat via .vbs is superior)
    launcher_files = [
        FileNames.SH_LAUNCHER,  # keydrive.sh
        FileNames.BAT_LAUNCHER,  # KeyDrive.bat
        FileNames.VBS_LAUNCHER,  # KeyDrive.vbs
    ]

    # BUG-20260102-011: Copy launcher scripts, ensuring shell scripts have Unix line endings
    for launcher in launcher_files:
        src = REPO_ROOT / launcher
        dst = target_path / launcher
        if src.exists():
            # Check if this is a shell script that needs Unix line endings
            if launcher in FileNames.SHELL_SCRIPTS:
                if _copy_shell_script_with_unix_endings(src, dst):
                    print(f"  ✓ {launcher} (Unix line endings)")
                else:
                    # Fallback to binary copy
                    shutil.copy2(src, dst)
                    print(f"  ✓ {launcher} (binary copy)")
            else:
                shutil.copy2(src, dst)
                print(f"  ✓ {launcher}")
        else:
            print(f"  ⚠ {launcher} not found in repo root")

    # BUG-20260102-008: CREATE .lnk shortcuts with correct target paths
    # Do NOT copy .lnk files - they contain hardcoded paths to source location
    # Instead, create new shortcuts pointing to the deployed .vbs file
    if _is_windows():
        shortcut_name = "KeyDrive.lnk"
        shortcut_path = target_path / shortcut_name
        vbs_target = target_path / FileNames.VBS_LAUNCHER
        icon_path = target_paths.static_dir / FileNames.ICON_MAIN

        if vbs_target.exists():
            windows_create_shortcut(
                shortcut_path=shortcut_path,
                target_path=vbs_target,
                working_dir=target_path,
                icon_path=icon_path,
                description=f"{PRODUCT_NAME} (GUI)",
            )
            print(f"  ✓ {shortcut_name} (created with local paths)")
        else:
            print(f"  ⚠ {FileNames.VBS_LAUNCHER} not found, skipping shortcut creation")

    # Create .command for macOS if not present
    command_name = f"{PRODUCT_NAME}.command"
    command_path = target_path / command_name
    if not command_path.exists():
        command_path.write_text(
            "#!/bin/bash\n"
            'cd "$(dirname "$0")"\n'
            f"chmod +x './{FileNames.SH_LAUNCHER}' 2>/dev/null || true\n"
            f"./{FileNames.SH_LAUNCHER}\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"  ✓ {command_name} created")

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
    if len(sys.argv) > 1 and sys.argv[1] == "--drive":
        if len(sys.argv) > 2:
            drive_arg = sys.argv[2]
            # Check if it's a path (starts with / on Unix or contains path separators)
            if drive_arg.startswith("/") or os.path.sep in drive_arg or len(drive_arg) > 2:
                # It's a path (Linux/macOS mount point)
                target_drive = Path(drive_arg)
                if not target_drive.exists():
                    print(f"❌ Path does not exist: {target_drive}")
                    sys.exit(1)
                if not target_drive.is_dir():
                    print(f"❌ Path is not a directory: {target_drive}")
                    sys.exit(1)
            else:
                # Windows drive letter
                target_drive = drive_arg.upper().rstrip(":")
        else:
            print("❌ --drive requires a drive letter or path")
            print("   Examples: --drive G")
            print("             --drive /media/user/USBDrive")
            sys.exit(1)

    if not target_drive:
        target_drive = select_drive_interactive()

    if not target_drive:
        print("❌ No drive selected.")
        sys.exit(1)

    # Normalize to Path for confirmation
    if isinstance(target_drive, Path):
        target_path = target_drive
    elif _is_windows() and len(str(target_drive)) == 1:
        target_path = Path(f"{target_drive}:\\")
    else:
        target_path = Path(target_drive)

    smartdrive_dir = target_path / ".smartdrive"

    if smartdrive_dir.exists():
        print(f"\n⚠️  {PRODUCT_NAME} is already deployed to {target_path}")
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
