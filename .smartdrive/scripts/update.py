#!/usr/bin/env python3
"""
SmartDrive Update Deployment Tool

Safely updates SmartDrive scripts and documentation from development
environment to deployment drives without overwriting user data.

Usage:
    python update.py                                 # Interactive mode
    python update.py --drive G                       # Update specific drive
    python update.py --dry-run                       # Preview changes

    # External drive GUI mode
    python update.py --mode external_drive --source server --url <URL>
    python update.py --mode external_drive --source local  --root <DIR>
"""

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Set

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/update.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/update.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.config import write_config_atomic
    from core.constants import Branding, ConfigKeys, FileNames
    from core.paths import Paths
    from core.platform import is_windows as _is_windows
    from core.platform import windows_create_shortcut, windows_refresh_explorer, windows_set_attributes
    from core.version import VERSION as CURRENT_VERSION
except ImportError:
    CURRENT_VERSION = "1.0.0"  # Fallback for when core not available (bootstrap scenario)
    write_config_atomic = None  # Fallback will use direct write

    class FileNames:
        CONFIG_JSON = "config.json"
        BAT_LAUNCHER = "KeyDrive.bat"
        GUI_BAT_LAUNCHER = "KeyDriveGUI.bat"

    class ConfigKeys:
        LAST_UPDATED = "last_updated"


# =============================================================================
# Logging - Structured log events
# =============================================================================
import logging

_update_logger = logging.getLogger("smartdrive.update")


def _log_update(event: str, **kwargs) -> None:
    """Emit structured update log event."""
    details = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    _update_logger.info(f"{event}{': ' + details if details else ''}")


# Configuration (source roots)
# IMPORTANT: This updater may run either from a repo checkout or from a deployed drive.
# In both cases, `_project_root` resolves to the drive/repo root that contains `.smartdrive/`.
DEV_ROOT = _project_root
DEV_SCRIPTS = DEV_ROOT / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR

# Import branding variables


# Files to update inside .smartdrive/scripts (drive root must contain entrypoints only)
FILES_TO_UPDATE = FileNames.FILES_TO_UPDATE

# Files/folders to NEVER overwrite (user data)
# Note: config.json user data is protected, but version metadata is updated
PROTECTED = FileNames.FILES_PROTECTED_FROM_UPDATE


# =============================================================================
# CHG-20251221-004: Deployment filtering
# =============================================================================
def should_exclude_from_deployment(path: Path, base_path: Path) -> bool:
    """
    Check if a path should be excluded from deployment.

    Args:
        path: Full path to check
        base_path: Base directory (for relative path calculation)

    Returns:
        True if path should be excluded, False if should be included
    """
    try:
        rel_path = path.relative_to(base_path)
    except ValueError:
        # Path not relative to base, include it
        return False

    rel_str = rel_path.as_posix()
    name = path.name

    # Check patterns from SSOT
    patterns = FileNames.DEPLOYMENT_EXCLUDE_PATTERNS

    # First pass: check if explicitly kept by negation pattern
    for pattern in patterns:
        if pattern.startswith("!"):
            keep_pattern = pattern[1:]
            import fnmatch

            if fnmatch.fnmatch(name, keep_pattern):
                return False  # Explicitly keep this file

    # Second pass: check exclusion patterns
    for pattern in patterns:
        # Skip negation patterns (already processed)
        if pattern.startswith("!"):
            continue

        # Exact directory name match (anywhere in path)
        if pattern in rel_str.split("/"):
            return True

        # Wildcard pattern matching
        if "*" in pattern:
            import fnmatch

            if fnmatch.fnmatch(name, pattern):
                return True
            if fnmatch.fnmatch(rel_str, pattern):
                return True

        # Exact name match
        if pattern == name:
            return True

        # Path starts with pattern (for directories)
        if rel_str.startswith(pattern + "/") or rel_str.startswith(pattern):
            return True

    return False


def create_deployment_ignore_function(base_path: Path):
    """
    Create an ignore function for shutil.copytree that filters development files.

    Args:
        base_path: Base source directory

    Returns:
        Function compatible with shutil.copytree ignore parameter
    """

    def ignore_deployment_files(directory, names):
        """Ignore function for shutil.copytree."""
        ignored = []
        dir_path = Path(directory)

        for name in names:
            full_path = dir_path / name
            if should_exclude_from_deployment(full_path, base_path):
                ignored.append(name)

        return ignored

    return ignore_deployment_files


def set_drive_icon(target_path: Path, drive_letter: str) -> None:
    """Set a custom drive icon using desktop.ini (no admin required)."""
    if not _is_windows():
        return  # Only for Windows

    try:
        desktop_ini = target_path / FileNames.DRIVE_ICON

        # Always reference the deployed static folder (root must stay clean)
        icon_rel = Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.STATIC_SUBDIR / FileNames.ICON_MAIN
        icon_path = icon_rel.as_posix().replace("/", "\\")

        ini_content = f"""[.ShellClassInfo]
IconFile={icon_path}
IconIndex=0

[ViewState]
Mode=
Vid=
FolderType=Generic
"""

        # Remove attributes if file exists (best-effort)
        if desktop_ini.exists():
            windows_set_attributes(desktop_ini, hidden=False, system=False)

        with open(desktop_ini, "w", encoding="utf-8") as f:
            f.write(ini_content)

        # Required: desktop.ini System+Hidden, drive root System
        windows_set_attributes(desktop_ini, hidden=True, system=True)
        windows_set_attributes(target_path, system=True)
        windows_refresh_explorer()

        log(f"Created {FileNames.DRIVE_ICON} for custom drive icon on {drive_letter}:")
    except Exception as e:
        log(f"Could not create {FileNames.DRIVE_ICON}: {e}", "WARN")


def _cleanup_root_legacy_artifacts(target_path: Path) -> None:
    """Best-effort removal of legacy root artifacts to keep drive root clean."""
    legacy_paths = [
        target_path / FileNames.README,
        target_path / FileNames.GUI_README,
        target_path / FileNames.README_PDF,
        target_path / FileNames.GUI_README_PDF,
        target_path / FileNames.BAT_LAUNCHER,
        target_path / FileNames.GUI_BAT_LAUNCHER,
        target_path / FileNames.VBS_LAUNCHER,
        target_path / FileNames.GUI_EXE,
    ]

    for p in legacy_paths:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def _ensure_clean_root_entrypoints(target_path: Path, target_scripts: Path) -> None:
    """Ensure the drive root only contains OS-clickable entrypoints."""
    if _is_windows():
        try:
            windows_set_attributes(target_path / Paths.SMARTDRIVE_DIR_NAME, hidden=True)
        except Exception:
            pass

        shortcut_name = Path(FileNames.BAT_LAUNCHER).with_suffix(".lnk").name
        shortcut_path = target_path / shortcut_name
        icon_path = target_path / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR / FileNames.ICON_MAIN
        exe_path = target_scripts / FileNames.GUI_EXE

        if exe_path.exists():
            windows_create_shortcut(
                shortcut_path=shortcut_path,
                target_path=exe_path,
                working_dir=target_path,
                icon_path=icon_path,
                description=f"{Branding.PRODUCT_NAME} (GUI)",
            )

    sh_src = DEV_ROOT / FileNames.SH_LAUNCHER
    sh_dst = target_path / FileNames.SH_LAUNCHER
    if sh_src.exists():
        try:
            shutil.copy2(sh_src, sh_dst)
        except Exception:
            pass

    command_name = f"{Branding.PRODUCT_NAME}.command"
    command_path = target_path / command_name
    try:
        command_path.write_text(
            "#!/bin/bash\n"
            'cd "$(dirname "$0")"\n'
            f"chmod +x './{FileNames.SH_LAUNCHER}' 2>/dev/null || true\n"
            f"./{FileNames.SH_LAUNCHER}\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        pass


def _ensure_clean_root_entrypoints_external(drive_root: Path, target_scripts: Path, payload_dir: Path) -> None:
    """
    Ensure the drive root contains OS-clickable entrypoints for external_drive update mode.

    BUG-20260102-003 FIX: This function is specifically for the --mode external_drive path.
    Unlike _ensure_clean_root_entrypoints, it gets launcher source files from payload_dir
    (the update source) rather than DEV_ROOT (which may not be correct in this context).

    BUG-20260102-006 FIX: Copy ALL launcher files (not just those dependent on .exe).

    Args:
        drive_root: The root of the external drive (parent of .smartdrive/)
        target_scripts: The target .smartdrive/scripts/ directory
        payload_dir: The directory containing update payload (source for launcher files)
    """
    log("[INFO] Updating launcher files...")

    if _is_windows():
        try:
            windows_set_attributes(drive_root / Paths.SMARTDRIVE_DIR_NAME, hidden=True)
        except Exception:
            pass

    # Define all launcher files that should be present
    # CHG-20260102-007: Removed KeyDriveGUI.bat (redundant - KeyDrive.bat via .vbs is superior)
    launcher_files = [
        FileNames.SH_LAUNCHER,  # keydrive.sh
        FileNames.BAT_LAUNCHER,  # KeyDrive.bat
        FileNames.VBS_LAUNCHER,  # KeyDrive.vbs
    ]

    # Copy launcher scripts from payload (try both root and .smartdrive subdirectory)
    for launcher in launcher_files:
        candidates = [
            payload_dir / launcher,
            payload_dir / Paths.SMARTDRIVE_DIR_NAME / launcher,
        ]
        dst = drive_root / launcher
        for src in candidates:
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                    log(f"  ✓ Updated {launcher}")
                    _log_update("update.launcher.copied", name=launcher)
                except Exception as e:
                    warn(f"Could not copy {launcher}: {e}")
                break
        else:
            # Check DEV_ROOT as fallback
            dev_src = DEV_ROOT / launcher
            if dev_src.exists():
                try:
                    shutil.copy2(dev_src, dst)
                    log(f"  ✓ Updated {launcher} (from DEV_ROOT)")
                    _log_update("update.launcher.from_dev", name=launcher)
                except Exception:
                    pass

    # BUG-20260102-008: CREATE .lnk shortcuts with correct target paths
    # Do NOT copy .lnk files - they contain hardcoded paths to source location
    # Instead, create new shortcuts pointing to the deployed .vbs file
    if _is_windows():
        shortcut_name = "KeyDrive.lnk"
        shortcut_path = drive_root / shortcut_name
        vbs_target = drive_root / FileNames.VBS_LAUNCHER
        icon_path = drive_root / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR / FileNames.ICON_MAIN

        if vbs_target.exists():
            try:
                windows_create_shortcut(
                    shortcut_path=shortcut_path,
                    target_path=vbs_target,
                    working_dir=drive_root,
                    icon_path=icon_path,
                    description=f"{Branding.PRODUCT_NAME} (GUI)",
                )
                log(f"  ✓ Created {shortcut_name} (with local paths)")
                _log_update("update.launcher.shortcut_created", name=shortcut_name)
            except Exception as e:
                warn(f"Could not create shortcut: {e}")
                _log_update("update.launcher.shortcut_error", error=str(e))
        else:
            log(f"  ⚠ {FileNames.VBS_LAUNCHER} not found, skipping shortcut creation")

    # Create .command for macOS
    command_name = f"{Branding.PRODUCT_NAME}.command"
    command_path = drive_root / command_name
    try:
        command_path.write_text(
            "#!/bin/bash\n"
            'cd "$(dirname "$0")"\n'
            f"chmod +x './{FileNames.SH_LAUNCHER}' 2>/dev/null || true\n"
            f"./{FileNames.SH_LAUNCHER}\n",
            encoding="utf-8",
            newline="\n",
        )
        log(f"  ✓ Created {command_name}")
        _log_update("update.launcher.command_created", name=command_name)
    except Exception as e:
        warn(f"Could not create {command_name}: {e}")


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
        path = Path(f"{drive}:\\")
        if path.exists():
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
    smartdrive_dir = drive_path / Paths.SMARTDRIVE_DIR_NAME
    config_file = smartdrive_dir / Paths.SCRIPTS_SUBDIR / FileNames.CONFIG_JSON
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

    # Add documentation (to be deployed under .smartdrive/docs)
    for doc_name in (
        FileNames.README,
        FileNames.GUI_README,
        FileNames.README_PDF,
        FileNames.GUI_README_PDF,
    ):
        doc = DEV_ROOT / doc_name
        if doc.exists():
            files.append(doc)

    # Add constants.py
    constants_file = DEV_ROOT / "constants.py"
    if constants_file.exists():
        files.append(constants_file)

    # Add variables.py
    variables_file = DEV_ROOT / FileNames.VARIABLES_PY
    if variables_file.exists():
        files.append(variables_file)

    return files


def preview_update(target_drive: str, dry_run: bool = True) -> List[tuple]:
    """Preview what will be updated."""
    target_path = Path(f"{target_drive}:\\")
    target_scripts = target_path / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR
    target_docs = target_path / Paths.SMARTDRIVE_DIR_NAME / "docs"

    changes = []
    files_to_update = get_files_to_update()

    for src in files_to_update:
        if src.parent == DEV_ROOT and src.name in {
            FileNames.README,
            FileNames.GUI_README,
            FileNames.README_PDF,
            FileNames.GUI_README_PDF,
        }:
            # Documentation goes under .smartdrive/docs/
            dst = target_docs / src.name
        elif src.name == "constants.py" and src.parent == DEV_ROOT:
            # constants.py goes to scripts directory
            dst = target_scripts / FileNames.CONSTANTS_PY
        elif src.name == FileNames.VARIABLES_PY and src.parent == DEV_ROOT:
            # variables.py goes to scripts directory
            dst = target_scripts / FileNames.VARIABLES_PY
        else:
            # Scripts go to .smartdrive/scripts/
            dst = target_scripts / src.name

        action = "COPY"
        if dst.exists():
            # Determine if content differs (mtime alone is unreliable across drives)
            try:
                same = filecmp.cmp(src, dst, shallow=False)
                action = "SKIP (same)" if same else "UPDATE"
            except Exception:
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


def perform_update(target_drive: str, dry_run: bool = False, yes: bool = False) -> bool:
    """Perform the update."""
    target_path = Path(f"{target_drive}:\\")

    _log_update("update.start", target=f"{target_drive}:\\", dry_run=dry_run)

    if not target_path.exists():
        error(f"Drive {target_drive}:\\ not found")
        _log_update("update.failed", reason="drive_not_found")
        return False

    # Check if it's a SmartDrive drive
    if not is_smartdrive_drive(target_path):
        warn(f"Drive {target_drive}:\\ doesn't appear to have SmartDrive installed")
        if not yes:
            confirm = input("Continue anyway? [y/N]: ").strip().lower()
            if confirm != "y":
                _log_update("update.cancelled", reason="user_abort")
                return False

    # Preview
    changes = preview_update(target_drive, dry_run=True)

    if dry_run:
        _log_update("update.dry_run.complete", change_count=len(changes))
        return True

    # Confirm
    if not yes:
        print()
        confirm = input("Proceed with update? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Update cancelled.")
            _log_update("update.cancelled", reason="user_declined")
            return False

    # Perform update
    print(f"\n{'─' * 70}")
    print("  PERFORMING UPDATE")
    print(f"{'─' * 70}\n")

    target_scripts = target_path / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR
    target_scripts.mkdir(parents=True, exist_ok=True)
    (target_path / Paths.SMARTDRIVE_DIR_NAME / "docs").mkdir(parents=True, exist_ok=True)

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
    # IMPORTANT: config.json user data is PRESERVED - only version/last_updated are updated
    config_path = target_scripts / FileNames.CONFIG_JSON
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            current_config_version = config.get("version")
            _log_update("update.config.preserving", path=str(config_path))

            # Only update if the version in version.py is different
            if current_config_version != CURRENT_VERSION:
                config["version"] = CURRENT_VERSION
                config["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # ALWAYS use atomic write - no fallback to direct write
                if write_config_atomic:
                    write_config_atomic(config_path, config)
                else:
                    raise ImportError("write_config_atomic required but not available")

                print(f"  ✓ Updated version: {current_config_version or 'none'} → {CURRENT_VERSION}")
                _log_update("update.config.version_updated", old=current_config_version, new=CURRENT_VERSION)
                success_count += 1
            else:
                _log_update("update.config.version_unchanged", version=CURRENT_VERSION)
            # If version is already current, don't count it as an update

        except Exception as e:
            error(f"Failed to update config.json version: {e}")
            _log_update("update.config.error", error=str(e))
            error_count += 1

    # Copy core folder (SSOT modules)
    core_src = DEV_ROOT / Paths.SMARTDRIVE_DIR_NAME / "core"
    if core_src.exists():
        core_dst = target_path / Paths.SMARTDRIVE_DIR_NAME / "core"
        try:
            # Ensure destination exists
            core_dst.mkdir(parents=True, exist_ok=True)

            # Copy each file individually to ensure updates
            for item in core_src.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(core_src)
                    dst_file = core_dst / rel_path
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dst_file)

            print("  ✓ Core modules")
            _log_update("update.core.copied")
            success_count += 1
        except Exception as e:
            error(f"Failed to copy core modules: {e}")
            _log_update("update.core.error", error=str(e))
            error_count += 1

    # Copy static folder to .smartdrive/static/ (deployed structure)
    # MANDATORY: Icons must be present for tray/window functionality

    # BUG-INSTANT: Fix FileNames.STATIC_DIR reference error
    # Use canonical Paths.STATIC_SUBDIR ("static") for both source and destination
    static_src = DEV_ROOT / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR
    if static_src.exists():
        # Primary destination: .smartdrive/static/
        static_dst = target_path / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR
        try:
            static_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(static_src, static_dst, dirs_exist_ok=True)
            # Count files for logging
            static_files = list(static_dst.rglob("*"))
            file_count = sum(1 for f in static_files if f.is_file())
            print(f"  ✓ Static folder (.smartdrive/static/) - {file_count} files")
            _log_update("update.static.copied", path=str(static_dst), file_count=file_count)
            success_count += 1

            # Remove legacy ROOT/static/ folder if it exists (migration from old structure)
            legacy_static = target_path / Paths.STATIC_SUBDIR
            if legacy_static.exists() and legacy_static.is_dir():
                try:
                    shutil.rmtree(legacy_static)
                    print("  ✓ Removed legacy static/ folder (migrated to .smartdrive/static/)")
                    _log_update("update.static.legacy_removed", path=str(legacy_static))
                except Exception as e:
                    print(f"  ⚠ Could not remove legacy static/ folder: {e}")

        except Exception as e:
            error(f"Failed to copy static folder: {e}")
            _log_update("update.static.error", error=str(e))
            error_count += 1
    else:
        _log_update("update.static.notfound", source=str(static_src))

    # BUG-20251221-032: Copy tests directory for post-deployment verification
    # Tests MUST be deployed to target so verification runs against deployed code
    tests_src = DEV_ROOT / Paths.SMARTDRIVE_DIR_NAME / "tests"
    if tests_src.exists():
        tests_dst = target_path / Paths.SMARTDRIVE_DIR_NAME / "tests"
        try:
            tests_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(tests_src, tests_dst, dirs_exist_ok=True)
            # Count test files for logging
            test_files = list(tests_dst.rglob("*.py"))
            file_count = len(test_files)
            print(f"  ✓ Tests folder (.smartdrive/tests/) - {file_count} test files")
            _log_update("update.tests.copied", path=str(tests_dst), file_count=file_count)
            success_count += 1
        except Exception as e:
            error(f"Failed to copy tests folder: {e}")
            _log_update("update.tests.error", error=str(e))
            error_count += 1
    else:
        _log_update("update.tests.notfound", source=str(tests_src))

    # Copy GUI executable if it exists (to .smartdrive/scripts)
    exe_src = DEV_ROOT / FileNames.DISTRIBUTION_DIR / FileNames.GUI_EXE
    if exe_src.exists():
        exe_dst = target_scripts / FileNames.GUI_EXE
        try:
            # Use copy instead of copy2 to avoid potential metadata issues
            shutil.copy(exe_src, exe_dst)
            print(f"  ✓ {FileNames.GUI_EXE}")
            _log_update("update.executable.copied", file=FileNames.GUI_EXE)
            success_count += 1
        except Exception as e:
            error(f"Failed to copy {FileNames.GUI_EXE}: {e}")
            _log_update("update.executable.error", error=str(e))
            error_count += 1

    # Enforce clean root entrypoints and remove legacy artifacts
    _cleanup_root_legacy_artifacts(target_path)
    _ensure_clean_root_entrypoints(target_path, target_scripts)

    # Set custom drive icon if on Windows
    if _is_windows():
        set_drive_icon(target_path, target_drive)

    _log_update(
        "update.complete",
        target=f"{target_drive}:\\",
        success=success_count,
        errors=error_count,
        version=CURRENT_VERSION,
    )
    print(f"\n{'─' * 70}")
    print(f"  UPDATE COMPLETE")
    print(f"{'─' * 70}")
    print(f"  Updated: {success_count} files")
    if error_count:
        print(f"  Errors: {error_count} files")
    print(f"  Target: {target_drive}:\\")
    print(f"  Version: {CURRENT_VERSION}")

    # CHG-20251221-023: Run post-deployment tests after update completes
    # Only run if not in dry-run mode and update was successful
    if error_count == 0 and not dry_run:
        print(f"\n{'─' * 70}")
        print(f"  POST-UPDATE VERIFICATION")
        print(f"{'─' * 70}")
        try:
            from setup import run_post_deployment_tests

            run_post_deployment_tests(target_path)
        except ImportError:
            print("  [!] Post-deployment tests unavailable (setup module not found)")
            _log_update("update.tests.unavailable", reason="import_error")
        except Exception as e:
            print(f"  [!] Post-deployment tests failed: {e}")
            _log_update("update.tests.error", error=str(e))

    return error_count == 0


def update_deployment_drive(target_drive: str = None, dry_run: bool = False, yes: bool = False) -> bool:
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

    return perform_update(target_drive, dry_run, yes)


# For backward compatibility and direct execution
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Update SmartDrive deployment drives")
    parser.add_argument("--drive", "-d", help="Target drive letter (e.g., G)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    # External drive GUI mode
    parser.add_argument("--mode", choices=["external_drive"], help="Run in external drive mode")
    parser.add_argument("--source", choices=["server", "local"], help="Update source type")
    parser.add_argument("--url", help="Server URL for update payload")
    parser.add_argument("--root", help="Local directory for update payload")

    args = parser.parse_args()

    # External drive GUI mode path
    if args.mode == "external_drive" and args.source:
        try:
            # CANONICAL PATH COMPUTATION (per AGENT_ARCHITECTURE.md):
            # Script is at: DRIVE:\.smartdrive\scripts\update.py
            #   .parent = DRIVE:\.smartdrive\scripts\
            #   .parent.parent = DRIVE:\.smartdrive\  (DEPLOY_ROOT)
            #   .parent.parent.parent = DRIVE:\       (DRIVE_ROOT)
            scripts_root = Path(__file__).resolve().parent
            deploy_root = scripts_root.parent  # .smartdrive/
            drive_root = deploy_root.parent  # DRIVE:\

            # HARD GATE: Verify we're in a .smartdrive deployment
            expected_dir_name = Paths.SMARTDRIVE_DIR_NAME
            if deploy_root.name != expected_dir_name:
                error(f"FATAL: Expected to be in '{expected_dir_name}' but found '{deploy_root.name}'")
                error(f"Script path: {Path(__file__).resolve()}")
                error("Update aborted: Invalid deployment layout")
                sys.exit(3)

            # BUG-20251221-001 FIX: Cleanup strategy
            # 1. Clean up ANY lingering _update_tmp directories from previous runs
            # 2. Create fresh temp directory
            # 3. Use try/finally to ensure cleanup even on error
            temp_dir = scripts_root / "_update_tmp"

            # Cleanup old temp directories (best effort)
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    _log_update("update.cleanup.old_temp", path=str(temp_dir))
                except Exception as e:
                    warn(f"Could not remove old _update_tmp: {e}")

            # Create fresh temp directory
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Download/prepare payload
                payload_dir = temp_dir / "payload"
                payload_dir.mkdir(parents=True, exist_ok=True)

                if args.source == "server" and args.url:
                    # Download archive from server URL
                    import urllib.request

                    archive_path = temp_dir / "update.zip"
                    _log_update("update.download.start", url=args.url)
                    urllib.request.urlretrieve(args.url, archive_path)
                    # Extract zip
                    import zipfile

                    with zipfile.ZipFile(archive_path, "r") as zf:
                        zf.extractall(payload_dir)
                    _log_update("update.download.complete", archive=str(archive_path))

                    # CHG-20251221-004: Filter extracted files
                    excluded_count = 0
                    for item in list(payload_dir.rglob("*")):
                        if item.is_file() and should_exclude_from_deployment(item, payload_dir):
                            item.unlink()
                            excluded_count += 1
                        elif item.is_dir() and should_exclude_from_deployment(item, payload_dir):
                            shutil.rmtree(item, ignore_errors=True)
                            excluded_count += 1

                    copied_files = sum(1 for _ in payload_dir.rglob("*") if _.is_file())
                    _log_update("update.server.filtered", copied=copied_files, excluded=excluded_count)
                elif args.source == "local" and args.root:
                    # Copy from local directory
                    src_root = Path(args.root)
                    if not src_root.exists():
                        error(f"Local update root not found: {src_root}")
                        sys.exit(2)

                    # BUG-20260102-002 FIX: Auto-detect .smartdrive subdirectory
                    # If user selected a directory containing .smartdrive/, use that as source.
                    # This allows user to select either:
                    #   - The parent directory (e.g., C:\MyDev\ which contains .smartdrive/)
                    #   - Or the .smartdrive directory directly (e.g., C:\MyDev\.smartdrive\)
                    smartdrive_subdir = src_root / Paths.SMARTDRIVE_DIR_NAME
                    if src_root.name != Paths.SMARTDRIVE_DIR_NAME and smartdrive_subdir.exists():
                        log(f"Auto-detected .smartdrive subdirectory in {src_root}")
                        src_root = smartdrive_subdir
                        _log_update("update.local.autodetect", detected=str(src_root))

                    _log_update("update.local.start", source=str(src_root))

                    # CHG-20251221-004: Apply deployment filtering
                    ignore_func = create_deployment_ignore_function(src_root)
                    shutil.copytree(src_root, payload_dir, dirs_exist_ok=True, ignore=ignore_func)

                    # Count excluded files for logging
                    total_files = sum(1 for _ in src_root.rglob("*") if _.is_file())
                    copied_files = sum(1 for _ in payload_dir.rglob("*") if _.is_file())
                    excluded_count = total_files - copied_files
                    _log_update("update.local.complete", copied=copied_files, excluded=excluded_count)
                else:
                    error("Invalid update source or missing parameters")
                    sys.exit(2)

                # BUG-20251221-001 FIX: Direct copy WITHOUT staging intermediate
                # Old approach: deploy_root → staging → overlay payload → copy back
                # New approach: payload → deploy_root (direct, atomic per file)
                # This eliminates redundant full directory tree copies
                _log_update("update.overlay.start", target=str(deploy_root))

                # BUG-20251225-003 FIX: Backup config.json before overlay
                cfg_path = deploy_root / Paths.SCRIPTS_SUBDIR / FileNames.CONFIG_JSON
                cfg_backup_path = None
                if cfg_path.exists():
                    try:
                        cfg_backup_path = cfg_path.with_suffix(".json.backup")
                        shutil.copy2(cfg_path, cfg_backup_path)
                        _log_update("update.config.backup_created", path=str(cfg_backup_path))
                    except Exception as e:
                        warn(f"Could not backup config.json: {e}")
                        _log_update("update.config.backup_failed", error=str(e))
                        cfg_backup_path = None

                # Copy payload directly to deploy_root
                # dirs_exist_ok=True allows overlay without removing existing files
                # BUG-20251224-003 FIX: Skip protected user data files during overlay
                # BUG-20251225-003 FIX: Add explicit filename check for config.json
                # BUG-20260102-025 FIX: Skip venv directories (handled separately to avoid ETXTBSY)
                VENV_DIRS = {".venv", ".venv-win", ".venv-linux", ".venv-mac"}
                skipped_protected = 0
                for item in payload_dir.rglob("*"):
                    if item.is_file():
                        # Compute relative path from payload root
                        rel_path = item.relative_to(payload_dir)

                        # BUG-20251225-003: EXPLICIT filename check for config.json
                        # NEVER overwrite config.json regardless of path structure
                        if item.name == FileNames.CONFIG_JSON:
                            skipped_protected += 1
                            _log_update(
                                "update.config.skipped",
                                path=str(rel_path),
                                reason="explicit_protection",
                            )
                            continue

                        # BUG-20260102-025: Skip venv directories (handled separately)
                        # This prevents ETXTBSY errors when Python binary is in use
                        is_venv = False
                        for part in rel_path.parts:
                            if part in VENV_DIRS:
                                is_venv = True
                                break
                        if is_venv:
                            continue  # Venv handled separately below

                        # BUG-20251224-003: Check if any path component is protected
                        # Protected items: config.json, keys/, integrity/, recovery/
                        is_protected = False
                        for part in rel_path.parts:
                            if part in PROTECTED:
                                is_protected = True
                                break

                        if is_protected:
                            skipped_protected += 1
                            continue  # NEVER overwrite user data

                        dst = deploy_root / rel_path

                        # Ensure parent directory exists
                        dst.parent.mkdir(parents=True, exist_ok=True)

                        # Copy file (overwrites if exists)
                        shutil.copy2(item, dst)

                _log_update("update.overlay.complete", skipped_protected=skipped_protected)

                # BUG-20251225-003 FIX: Update config.json metadata with validation and restore
                if cfg_path.exists():
                    try:
                        # Load current config
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            cfg = json.load(f)

                        # Preserve original for validation
                        original_keys = set(cfg.keys())

                        # Update only metadata fields
                        cfg[ConfigKeys.LAST_UPDATED] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # Use atomic write if available
                        if write_config_atomic:
                            write_config_atomic(cfg_path, cfg)
                        else:
                            with open(cfg_path, "w", encoding="utf-8") as f:
                                json.dump(cfg, f, indent=2)

                        # BUG-20251225-003: Validate config.json after update
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            validated_cfg = json.load(f)

                        # Check no keys were lost
                        if set(validated_cfg.keys()) != original_keys:
                            raise ValueError("Config keys mismatch after update")

                        _log_update("update.config.updated", timestamp=cfg[ConfigKeys.LAST_UPDATED])

                        # BUG-20251225-003: Remove backup after successful update
                        if cfg_backup_path and cfg_backup_path.exists():
                            cfg_backup_path.unlink()
                            _log_update("update.config.backup_removed")

                    except Exception as e:
                        warn(f"Config.json update failed: {e}")
                        _log_update("update.config.error", error=str(e))

                        # BUG-20251225-003: Restore from backup on failure
                        if cfg_backup_path and cfg_backup_path.exists():
                            try:
                                shutil.copy2(cfg_backup_path, cfg_path)
                                warn("Restored config.json from backup")
                                _log_update("update.config.restored_from_backup")
                            except Exception as restore_error:
                                error(f"Failed to restore config.json: {restore_error}")
                                _log_update("update.config.restore_failed", error=str(restore_error))

                # BUG-20260102-003 FIX: Update launcher files in drive root
                # Launchers (.lnk, .sh, .command) must be placed at drive_root (parent of .smartdrive)
                # This was missing in external_drive mode, causing stale shortcuts
                log("Updating launcher files...")
                _ensure_clean_root_entrypoints_external(drive_root, scripts_root, payload_dir)
                _log_update("update.launchers.updated", target=str(drive_root))

                # BUG-20260102-012: Update OS-specific .venv for dependency shipping
                # Copy bundled Python environment if present in payload
                # Determine OS-specific venv name
                from core.platform import get_platform as _get_platform

                _platform = _get_platform().lower()
                if _platform == "windows":
                    os_venv_name = ".venv-win"
                elif _platform == "darwin":
                    os_venv_name = ".venv-mac"
                else:
                    os_venv_name = ".venv-linux"

                venv_candidates = [
                    # Try OS-specific venv first
                    payload_dir / os_venv_name,
                    payload_dir / Paths.SMARTDRIVE_DIR_NAME / os_venv_name,
                    # Fall back to legacy .venv
                    payload_dir / ".venv",
                    payload_dir / Paths.SMARTDRIVE_DIR_NAME / ".venv",
                ]
                # Target uses OS-specific name
                venv_dst = deploy_root / os_venv_name
                for venv_src in venv_candidates:
                    if venv_src.exists():
                        log(f"Updating bundled Python environment ({os_venv_name})...")
                        try:
                            # BUG-20260102-025: Handle "Text file busy" error on Linux
                            # When GUI is running from the venv, the Python binary can't be replaced/deleted
                            # First check if venv is in use by testing if we can rename the python binary
                            if venv_dst.exists():
                                # Check if venv is in use before attempting to delete
                                python_bins = list(venv_dst.glob("bin/python*")) + list(
                                    venv_dst.glob("Scripts/python.exe")
                                )
                                for pbin in python_bins:
                                    if pbin.exists():
                                        try:
                                            # Try to open for writing to test if in use
                                            # On Linux, open() succeeds but unlink/rename fails when busy
                                            test_path = pbin.with_suffix(".test")
                                            pbin.rename(test_path)
                                            test_path.rename(pbin)
                                        except OSError as e:
                                            if e.errno == 26:  # ETXTBSY - Text file busy
                                                warn(f"Skipping {os_venv_name}: Python environment is in use")
                                                warn(
                                                    "  (Restart KeyDrive and run update again to update Python dependencies)"
                                                )
                                                _log_update("update.venv.busy", venv_name=os_venv_name)
                                                break  # Skip venv update entirely
                                            raise
                                else:
                                    # No python binary was busy, proceed with removal
                                    shutil.rmtree(venv_dst)
                                    shutil.copytree(venv_src, venv_dst)
                                    _log_update("update.venv.copied", source=str(venv_src), venv_name=os_venv_name)
                                    log(f"  ✓ {os_venv_name}/ updated")
                            else:
                                # venv doesn't exist, just copy
                                shutil.copytree(venv_src, venv_dst)
                                _log_update("update.venv.copied", source=str(venv_src), venv_name=os_venv_name)
                                log(f"  ✓ {os_venv_name}/ updated")
                        except OSError as e:
                            # BUG-20260102-016: Handle "Text file busy" error on Linux
                            # When GUI is running from the venv, the Python binary can't be replaced
                            if e.errno == 26:  # ETXTBSY - Text file busy
                                warn(f"Skipping {os_venv_name}: Python environment is in use")
                                warn("  (Restart KeyDrive and run update again to update Python dependencies)")
                                _log_update("update.venv.busy", venv_name=os_venv_name)
                            else:
                                warn(f"Could not update {os_venv_name}: {e}")
                                _log_update("update.venv.error", error=str(e))
                        except Exception as e:
                            warn(f"Could not update {os_venv_name}: {e}")
                            _log_update("update.venv.error", error=str(e))
                        break

                print("Update overlay complete.")
                _log_update("update.external_drive.success")

            finally:
                # BUG-20251221-001 FIX: ALWAYS cleanup temp directory
                # This runs even if update fails or is interrupted
                if temp_dir.exists():
                    try:
                        shutil.rmtree(temp_dir)
                        _log_update("update.cleanup.success", path=str(temp_dir))
                    except Exception as e:
                        warn(f"Could not cleanup temp directory: {e}")
                        _log_update("update.cleanup.error", error=str(e))

            sys.exit(0)
        except Exception as e:
            error(str(e))
            _log_update("update.external_drive.failed", error=str(e))
            sys.exit(1)

    # Default interactive/drive mode
    ok = update_deployment_drive(args.drive, args.dry_run, args.yes)
    sys.exit(0 if ok else 1)

    if args.drive:
        update_deployment_drive(args.drive, args.dry_run, args.yes)
    else:
        update_deployment_drive(dry_run=args.dry_run, yes=args.yes)
