"""
PathResolver - Single Source of Truth for Runtime Paths
========================================================
Enforces SSOT for all file system paths used across the application.

Rules:
1. No implicit CWD usage - all paths via resolver
2. Fail loudly on writes outside authorized roots
3. Exactly one config.json location per runtime
4. Exactly one static/ directory location
5. All logs, keys, and payload files under root

Usage:
    from core.path_resolver import RuntimePaths
    
    paths = RuntimePaths.from_script(__file__)
    config_path = paths.config_file
    static_dir = paths.static_dir
    
    # Write with validation
    paths.validate_write_path(target_path)  # Raises if outside roots
"""

import os
import sys
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class RuntimePaths:
    """
    Immutable runtime path configuration.
    
    All paths are absolute and verified to exist (except for files that may be created).
    """
    
    # Root directories
    project_root: Path
    smartdrive_root: Path  # .smartdrive/
    scripts_root: Path     # .smartdrive/scripts/
    
    # Config and data
    config_file: Path      # config.json (may not exist yet)
    static_dir: Path       # static/ assets
    keys_dir: Path         # Encryption keys
    logs_dir: Path         # Log files
    
    # Authorized write roots (writes must be under one of these)
    write_roots: tuple[Path, ...]
    
    @classmethod
    def from_script(cls, script_path: str | Path) -> 'RuntimePaths':
        """
        Create RuntimePaths from a script's location.
        
        Args:
            script_path: Path to calling script (usually __file__)
        
        Returns:
            Configured RuntimePaths instance
        
        Raises:
            RuntimeError: If directory structure is invalid
        """
        script_path = Path(script_path).resolve()
        
        # Determine root based on script location
        if ".smartdrive" in script_path.parts:
            # Script is in .smartdrive/ tree
            smartdrive_idx = script_path.parts.index(".smartdrive")
            smartdrive_root = Path(*script_path.parts[:smartdrive_idx + 1])
            project_root = smartdrive_root.parent
        else:
            # Script is in project root tree (e.g., scripts/deploy.py)
            # Assume .smartdrive is in same directory or parent
            project_root = script_path.parent
            while project_root != project_root.parent:
                smartdrive_candidate = project_root / ".smartdrive"
                if smartdrive_candidate.exists() and smartdrive_candidate.is_dir():
                    smartdrive_root = smartdrive_candidate
                    break
                project_root = project_root.parent
            else:
                raise RuntimeError(
                    f"Cannot locate .smartdrive directory from {script_path}\n"
                    "PathResolver requires .smartdrive/ to exist in project tree"
                )
        
        scripts_root = smartdrive_root / "scripts"
        
        # Define standard paths
        # NOTE: Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
        config_file = smartdrive_root / "config.json"
        static_dir = smartdrive_root / "static"
        keys_dir = smartdrive_root / "keys"
        logs_dir = smartdrive_root / "logs"
        
        # Create directories if they don't exist (except config file)
        for directory in [static_dir, keys_dir, logs_dir, scripts_root]:
            directory.mkdir(parents=True, exist_ok=True)
        
        # Define authorized write roots
        # NOTE: smartdrive_root is included for config.json which lives there
        write_roots = (
            smartdrive_root,  # config.json lives here
            scripts_root,     # temporary files
            static_dir,       # Assets
            keys_dir,         # Keyfiles
            logs_dir,         # Log files
        )
        
        return cls(
            project_root=project_root,
            smartdrive_root=smartdrive_root,
            scripts_root=scripts_root,
            config_file=config_file,
            static_dir=static_dir,
            keys_dir=keys_dir,
            logs_dir=logs_dir,
            write_roots=write_roots,
        )
    
    @classmethod
    def from_drive_letter(cls, drive_letter: str) -> 'RuntimePaths':
        """
        Create RuntimePaths for a USB drive deployment.
        
        Args:
            drive_letter: Drive letter (e.g., 'F' or 'F:')
        
        Returns:
            Configured RuntimePaths instance
        """
        if len(drive_letter) > 1 and drive_letter.endswith(':'):
            drive_letter = drive_letter[0]
        
        drive_root = Path(f"{drive_letter}:/")
        smartdrive_root = drive_root / ".smartdrive"
        
        if not smartdrive_root.exists():
            raise RuntimeError(
                f"No .smartdrive directory found on drive {drive_letter}:\n"
                f"Expected: {smartdrive_root}"
            )
        
        # Use from_script with a path in the drive's .smartdrive
        return cls.from_script(smartdrive_root / "scripts" / "mount.py")
    
    @classmethod
    def for_target(cls, target_root: Path, create_dirs: bool = False) -> 'RuntimePaths':
        """
        Create RuntimePaths for an explicit target root (cross-drive support).
        
        This is the PRIMARY factory for setup/deploy operations that target
        a specific drive, regardless of where the script is running from.
        
        Args:
            target_root: Absolute path to target drive/directory root
            create_dirs: If True, create directories that don't exist
        
        Returns:
            Configured RuntimePaths instance
        
        Raises:
            ValueError: If target_root is not absolute
        """
        target_root = Path(target_root).resolve()
        
        if not target_root.is_absolute():
            raise ValueError(f"target_root must be absolute: {target_root}")
        
        project_root = target_root
        smartdrive_root = project_root / ".smartdrive"
        scripts_root = smartdrive_root / "scripts"
        
        # Define standard paths
        # NOTE: Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
        config_file = smartdrive_root / "config.json"
        static_dir = smartdrive_root / "static"
        keys_dir = smartdrive_root / "keys"
        logs_dir = smartdrive_root / "logs"
        
        # Create directories if requested
        if create_dirs:
            for directory in [static_dir, keys_dir, logs_dir, scripts_root]:
                directory.mkdir(parents=True, exist_ok=True)
        
        # Define authorized write roots
        # NOTE: smartdrive_root is included for config.json which lives there
        write_roots = (
            smartdrive_root,  # config.json lives here
            scripts_root,
            static_dir,
            keys_dir,
            logs_dir,
        )
        
        return cls(
            project_root=project_root,
            smartdrive_root=smartdrive_root,
            scripts_root=scripts_root,
            config_file=config_file,
            static_dir=static_dir,
            keys_dir=keys_dir,
            logs_dir=logs_dir,
            write_roots=write_roots,
        )
    
    def validate_write_path(self, target_path: Path | str) -> Path:
        """
        Validate that a write path is under authorized roots.
        
        Args:
            target_path: Path to validate
        
        Returns:
            Absolute resolved path
        
        Raises:
            SecurityError: If path is outside authorized write roots
        """
        target_path = Path(target_path).resolve()
        
        for root in self.write_roots:
            try:
                target_path.relative_to(root)
                return target_path  # Path is under this root
            except ValueError:
                continue  # Not under this root, try next
        
        # Path is not under any authorized root
        raise SecurityError(
            f"Write path outside authorized roots:\n"
            f"  Target: {target_path}\n"
            f"  Authorized roots:\n" +
            "\n".join(f"    - {root}" for root in self.write_roots)
        )
    
    def get_config_path(self) -> Path:
        """Get path to config.json (SSOT)."""
        return self.config_file
    
    def get_static_path(self, filename: str = "") -> Path:
        """
        Get path to static/ directory or file within it.
        
        Args:
            filename: Optional filename within static/
        
        Returns:
            Path to static/ or static/<filename>
        """
        if filename:
            return self.static_dir / filename
        return self.static_dir
    
    def get_keys_path(self, filename: str = "") -> Path:
        """
        Get path to keys/ directory or file within it.
        
        Args:
            filename: Optional filename within keys/
        
        Returns:
            Path to keys/ or keys/<filename>
        """
        if filename:
            return self.keys_dir / filename
        return self.keys_dir
    
    def get_log_path(self, filename: str) -> Path:
        """
        Get path to log file.
        
        Args:
            filename: Log filename
        
        Returns:
            Path to logs/<filename>
        """
        return self.logs_dir / filename
    
    def detect_duplicates(self) -> dict[str, list[Path]]:
        """
        Detect duplicate config.json or static/ directories.
        
        Returns:
            Dict mapping resource name to list of paths (empty if no duplicates)
        """
        duplicates = {}
        
        # Search for config.json duplicates
        config_files = []
        for root, dirs, files in os.walk(self.project_root):
            if "config.json" in files:
                config_path = Path(root) / "config.json"
                # Only consider .smartdrive tree
                if ".smartdrive" in config_path.parts:
                    config_files.append(config_path)
        
        if len(config_files) > 1:
            duplicates["config.json"] = config_files
        
        # Search for static/ duplicates
        static_dirs = []
        for root, dirs, files in os.walk(self.project_root):
            if "static" in dirs:
                static_path = Path(root) / "static"
                # Only consider .smartdrive tree
                if ".smartdrive" in static_path.parts:
                    static_dirs.append(static_path)
        
        if len(static_dirs) > 1:
            duplicates["static/"] = static_dirs
        
        return duplicates


class SecurityError(Exception):
    """Raised when attempting to write outside authorized roots."""
    pass


# =============================================================================
# Migration Helpers
# =============================================================================

def migrate_legacy_config(old_path: Path, new_path: Path, force: bool = False) -> None:
    """
    Migrate config.json from legacy location to SSOT location.
    
    Args:
        old_path: Legacy config.json path
        new_path: New SSOT config.json path
        force: If True, overwrite existing new_path
    
    Raises:
        FileExistsError: If new_path exists and force=False
        RuntimeError: If migration fails
    """
    import json
    import shutil
    
    if not old_path.exists():
        raise RuntimeError(f"Legacy config not found: {old_path}")
    
    if new_path.exists() and not force:
        raise FileExistsError(
            f"Target config already exists: {new_path}\n"
            "Use force=True to overwrite"
        )
    
    # Validate config is valid JSON
    try:
        with open(old_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Legacy config is invalid JSON: {e}")
    
    # Write to new location atomically
    temp_path = new_path.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        temp_path.replace(new_path)
        
        # Backup old config
        backup_path = old_path.with_suffix('.migrated_backup')
        shutil.copy2(old_path, backup_path)
        
        print(f"✓ Migrated config: {old_path} → {new_path}")
        print(f"  Backup created: {backup_path}")
        
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Migration failed: {e}")

def consolidate_duplicates(paths: RuntimePaths, dry_run: bool = False) -> dict:
    """
    Consolidate duplicate config.json and static/ directories.
    
    Migration strategy:
    1. Determine canonical location (.smartdrive/scripts/config.json, .smartdrive/static/)
    2. If duplicates exist, move/merge to canonical
    3. Delete duplicates after successful migration
    4. Preserve all unknown keys (deep merge)
    
    Args:
        paths: RuntimePaths instance
        dry_run: If True, report actions but don't modify filesystem
    
    Returns:
        Dict with migration actions taken
    """
    import json
    import shutil
    
    actions = {"moved": [], "merged": [], "deleted": [], "errors": []}
    
    duplicates = paths.detect_duplicates()
    
    if not duplicates:
        return actions
    
    # Consolidate config.json duplicates
    if "config.json" in duplicates:
        config_paths = duplicates["config.json"]
        canonical = paths.config_file
        
        # Load all configs and merge (preserving unknown keys)
        merged_data = {}
        for config_path in config_paths:
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Deep merge (later files override earlier)
                _deep_merge(merged_data, data)
            except Exception as e:
                actions["errors"].append(f"Failed to read {config_path}: {e}")
        
        if not dry_run:
            # Write merged config to canonical location
            canonical.parent.mkdir(parents=True, exist_ok=True)
            with open(canonical, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, indent=2)
            actions["merged"].append(str(canonical))
            
            # Delete duplicates (not canonical)
            for config_path in config_paths:
                if config_path != canonical:
                    try:
                        config_path.unlink()
                        actions["deleted"].append(str(config_path))
                    except Exception as e:
                        actions["errors"].append(f"Failed to delete {config_path}: {e}")
        else:
            actions["merged"].append(f"[DRY-RUN] Would merge to {canonical}")
            for config_path in config_paths:
                if config_path != canonical:
                    actions["deleted"].append(f"[DRY-RUN] Would delete {config_path}")
    
    # Consolidate static/ duplicates
    if "static/" in duplicates:
        static_paths = duplicates["static/"]
        canonical = paths.static_dir
        
        for static_path in static_paths:
            if static_path != canonical:
                if not dry_run:
                    try:
                        # Move/merge files to canonical
                        canonical.mkdir(parents=True, exist_ok=True)
                        for item in static_path.rglob("*"):
                            if item.is_file():
                                rel_path = item.relative_to(static_path)
                                dest = canonical / rel_path
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(item, dest)
                        # Delete duplicate after successful copy
                        shutil.rmtree(static_path)
                        actions["moved"].append(f"{static_path} -> {canonical}")
                    except Exception as e:
                        actions["errors"].append(f"Failed to migrate {static_path}: {e}")
                else:
                    actions["moved"].append(f"[DRY-RUN] Would move {static_path} -> {canonical}")
    
    return actions


def _deep_merge(base: dict, overlay: dict) -> None:
    """Deep merge overlay into base, preserving unknown keys."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

def check_no_duplicates(paths: RuntimePaths) -> bool:
    """
    Check for duplicate config.json or static/ directories.
    
    Args:
        paths: RuntimePaths instance
    
    Returns:
        True if no duplicates found, False otherwise (logs errors)
    """
    duplicates = paths.detect_duplicates()
    
    if not duplicates:
        return True
    
    print("\n" + "=" * 70)
    print("ERROR: Duplicate resources detected")
    print("=" * 70)
    
    for resource, paths_list in duplicates.items():
        print(f"\n{resource} found in multiple locations:")
        for path in paths_list:
            print(f"  - {path}")
    
    print("\nResolution:")
    print("1. Determine which is the canonical location")
    print("2. Delete or migrate duplicates")
    print("3. Ensure deployment scripts use PathResolver")
    
    return False


if __name__ == "__main__":
    # Self-test
    try:
        paths = RuntimePaths.from_script(__file__)
        print("PathResolver self-test:")
        print(f"  Project root:    {paths.project_root}")
        print(f"  SmartDrive root: {paths.smartdrive_root}")
        print(f"  Config file:     {paths.config_file}")
        print(f"  Static dir:      {paths.static_dir}")
        print(f"  Keys dir:        {paths.keys_dir}")
        print(f"  Logs dir:        {paths.logs_dir}")
        
        # Test duplicate detection
        duplicates = paths.detect_duplicates()
        if duplicates:
            print("\n⚠ WARNING: Duplicates detected:")
            for resource, dup_paths in duplicates.items():
                print(f"  {resource}: {len(dup_paths)} locations")
        else:
            print("\n✓ No duplicates detected")
        
        # Test write validation
        try:
            paths.validate_write_path(paths.config_file)
            print("✓ Config write path valid")
        except SecurityError as e:
            print(f"✗ Config write validation failed: {e}")
        
        print("\n✓ PathResolver self-test passed")
        
    except Exception as e:
        print(f"✗ PathResolver self-test failed: {e}")
        sys.exit(1)
