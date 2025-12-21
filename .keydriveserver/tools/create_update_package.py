#!/usr/bin/env python3
"""
Create Update Package Tool

CHG-20251221-011: Automates creation of update packages for KeyDrive server.

This script:
1. Collects all deployment files (applying DEPLOYMENT_EXCLUDE_PATTERNS)
2. Creates a zip archive with proper structure
3. Calculates SHA-512 hash
4. Registers the update in the server database
5. Stores the package in the server's updates/ directory

Usage:
    python create_update_package.py --version 1.0.0 --changelog "Initial release"
    python create_update_package.py --version 1.0.1 --changelog "Bug fixes" --set-current
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Set

# Determine paths
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_ROOT = SCRIPT_DIR.parent  # .keydriveserver/
PROJECT_ROOT = SERVER_ROOT.parent  # VeraCrypt_Yubikey_2FA/
SMARTDRIVE_ROOT = PROJECT_ROOT / ".smartdrive"
UPDATES_DIR = SERVER_ROOT / "updates"
DATABASE_PATH = SERVER_ROOT / "keydrive.db"


# =============================================================================
# DEPLOYMENT_EXCLUDE_PATTERNS from SSOT
# =============================================================================

# These patterns are copied from core/constants.py FileNames.DEPLOYMENT_EXCLUDE_PATTERNS
# to avoid import issues when running standalone
DEPLOYMENT_EXCLUDE_PATTERNS = [
    # Git and version control
    ".git",
    ".gitignore",
    ".gitattributes",
    ".github",
    # IDE and editor files
    ".vscode",
    ".idea",
    "*.swp",
    "*.swo",
    "*~",
    # Python artifacts
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.egg-info",
    ".eggs",
    # Virtual environments
    "venv",
    ".venv",
    "env",
    ".env",
    # Test directories
    "tests",
    "test",
    # Documentation (development)
    "docs/development",
    "docs/internal",
    # Build artifacts
    "build",
    "dist",
    "*.spec",
    # Development files
    "Makefile",
    "setup.cfg",
    "pyproject.toml",
    "tox.ini",
    ".pre-commit-config.yaml",
    # Server (not deployed to drives)
    ".keydriveserver",
    # Temporary files
    "*.tmp",
    "*.temp",
    "*.log",
    "_update_tmp",
    # OS files
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    # Backup files
    "*.bak",
    "*.old",
    "*.orig",
    # Architecture documents (development only)
    "AGENT_ARCHITECTURE.md",
    "FEATURE_FLOWS.md",
    # Keep README files (negation pattern)
    "!README.md",
    "!GUI_README.md",
]


def should_exclude(path: Path, base_path: Path) -> bool:
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
        return False

    rel_str = rel_path.as_posix()
    name = path.name

    # First pass: check if explicitly kept by negation pattern
    for pattern in DEPLOYMENT_EXCLUDE_PATTERNS:
        if pattern.startswith("!"):
            keep_pattern = pattern[1:]
            if fnmatch(name, keep_pattern):
                return False  # Explicitly keep this file

    # Second pass: check exclusion patterns
    for pattern in DEPLOYMENT_EXCLUDE_PATTERNS:
        if pattern.startswith("!"):
            continue

        # Exact directory name match (anywhere in path)
        if pattern in rel_str.split("/"):
            return True

        # Wildcard pattern matching
        if "*" in pattern:
            if fnmatch(name, pattern):
                return True

    return False


def collect_files(source_dir: Path) -> List[Path]:
    """
    Collect all files to include in the update package.
    
    Args:
        source_dir: Root directory to scan
    
    Returns:
        List of file paths to include
    """
    files = []
    
    for item in source_dir.rglob("*"):
        if item.is_file():
            if not should_exclude(item, source_dir):
                files.append(item)
    
    return files


def create_zip_package(
    source_dir: Path,
    output_path: Path,
    version: str,
) -> tuple[int, int]:
    """
    Create a zip package with proper structure.
    
    Args:
        source_dir: Root directory containing .smartdrive
        output_path: Path for output zip file
        version: Version string for logging
    
    Returns:
        Tuple of (total_files, total_size_bytes)
    """
    files = collect_files(source_dir / ".smartdrive")
    total_files = 0
    total_size = 0
    
    print(f"Creating update package v{version}...")
    print(f"Source: {source_dir}")
    print(f"Output: {output_path}")
    
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add .smartdrive directory contents
        for file_path in files:
            rel_path = file_path.relative_to(source_dir)
            zf.write(file_path, rel_path)
            total_files += 1
            total_size += file_path.stat().st_size
            
        # Add root-level files that should be deployed
        root_files = [
            "constants.py",
            "variables.py", 
            "README.md",
            "GUI_README.md",
            "requirements.txt",
        ]
        
        for fname in root_files:
            fpath = source_dir / fname
            if fpath.exists():
                zf.write(fpath, fname)
                total_files += 1
                total_size += fpath.stat().st_size
    
    print(f"  Included {total_files} files ({total_size / 1024:.1f} KB)")
    return total_files, total_size


def calculate_hash(file_path: Path) -> str:
    """Calculate SHA-512 hash of a file."""
    sha512 = hashlib.sha512()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha512.update(chunk)
    return sha512.hexdigest()


def register_update(
    db_path: Path,
    version: str,
    package_filename: str,
    package_hash: str,
    package_size: int,
    changelog: str,
    min_version: str | None,
    set_current: bool,
) -> None:
    """
    Register update in the database.
    
    Args:
        db_path: Path to SQLite database
        version: Version string
        package_filename: Name of the zip file
        package_hash: SHA-512 hash
        package_size: Size in bytes
        changelog: Changelog text
        min_version: Minimum version required to upgrade
        set_current: Whether to mark this as the current version
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create updates table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT UNIQUE NOT NULL,
            release_date TEXT NOT NULL,
            package_filename TEXT NOT NULL,
            package_hash TEXT NOT NULL,
            package_size INTEGER NOT NULL,
            changelog TEXT,
            min_version TEXT,
            is_current INTEGER DEFAULT 0
        )
    """)
    
    # Check if version already exists
    cursor.execute("SELECT id FROM updates WHERE version = ?", (version,))
    if cursor.fetchone():
        print(f"ERROR: Version {version} already exists in database")
        conn.close()
        sys.exit(1)
    
    # If setting as current, unset all others
    if set_current:
        cursor.execute("UPDATE updates SET is_current = 0")
    
    # Insert new update
    cursor.execute(
        """
        INSERT INTO updates (version, release_date, package_filename, package_hash, 
                           package_size, changelog, min_version, is_current)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version,
            datetime.utcnow().isoformat(),
            package_filename,
            package_hash,
            package_size,
            changelog,
            min_version,
            1 if set_current else 0,
        ),
    )
    
    conn.commit()
    conn.close()
    print(f"  Registered in database (is_current={set_current})")


def main():
    parser = argparse.ArgumentParser(
        description="Create update package for KeyDrive server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python create_update_package.py --version 1.0.0 --changelog "Initial release" --set-current
    python create_update_package.py --version 1.0.1 --changelog "Bug fixes"
    python create_update_package.py --version 1.1.0 --changelog "New features" --min-version 1.0.0 --set-current
        """,
    )
    
    parser.add_argument(
        "--version",
        required=True,
        help="Version string (e.g., 1.0.0)",
    )
    parser.add_argument(
        "--changelog",
        default="",
        help="Changelog description for this version",
    )
    parser.add_argument(
        "--min-version",
        default=None,
        help="Minimum version required to upgrade to this version",
    )
    parser.add_argument(
        "--set-current",
        action="store_true",
        help="Mark this version as the current/latest version",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT,
        help=f"Source directory containing .smartdrive (default: {PROJECT_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=UPDATES_DIR,
        help=f"Output directory for update package (default: {UPDATES_DIR})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DATABASE_PATH,
        help=f"Path to server database (default: {DATABASE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without creating files",
    )
    
    args = parser.parse_args()
    
    # Validate source directory
    if not (args.source / ".smartdrive").exists():
        print(f"ERROR: .smartdrive directory not found in {args.source}")
        sys.exit(1)
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate package filename
    package_filename = f"keydrive-update-{args.version}.zip"
    output_path = args.output_dir / package_filename
    
    if output_path.exists():
        print(f"ERROR: Package already exists: {output_path}")
        sys.exit(1)
    
    if args.dry_run:
        print("DRY RUN - No files will be created")
        print(f"Would create: {output_path}")
        files = collect_files(args.source / ".smartdrive")
        print(f"Would include {len(files)} files from .smartdrive/")
        return
    
    # Create zip package
    total_files, total_size = create_zip_package(
        args.source,
        output_path,
        args.version,
    )
    
    # Calculate hash
    package_hash = calculate_hash(output_path)
    package_size = output_path.stat().st_size
    print(f"  Package size: {package_size / 1024:.1f} KB")
    print(f"  SHA-512: {package_hash[:32]}...")
    
    # Register in database
    register_update(
        args.database,
        args.version,
        package_filename,
        package_hash,
        package_size,
        args.changelog,
        args.min_version,
        args.set_current,
    )
    
    print(f"\n✅ Update package created successfully!")
    print(f"   File: {output_path}")
    print(f"   Version: {args.version}")
    if args.set_current:
        print(f"   Status: CURRENT (will be served at /api/update/download/latest)")


if __name__ == "__main__":
    main()
