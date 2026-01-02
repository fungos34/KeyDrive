#!/usr/bin/env python3
"""
Enforcement script: Check for forbidden string-based filesystem paths.

This script scans all Python files in the repository and fails if any
forbidden path patterns are found.

Exit codes:
    0 - No violations found
    1 - Violations found

Usage:
    python scripts/check_no_string_paths.py
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple

# Patterns that indicate forbidden string-based paths
# NOTE: We use [/] for forward slash and [\\\\] for backslash (escaped for regex in Python)
# We avoid matching \n (newline) by being more specific about path patterns
FORBIDDEN_PATTERNS = [
    # Hardcoded Windows absolute paths (drive letter)
    (r'["\'][A-Z]:\\\\', "Hardcoded Windows absolute path"),
    (r'Path\s*\(\s*r?["\'][A-Z]:', "Hardcoded Windows absolute path in Path()"),
    # Hardcoded Unix absolute paths (with realistic path prefixes)
    (r'["\']\/(?:usr|home|var|opt|etc|Applications)\/[a-zA-Z]', "Hardcoded Unix absolute path"),
    (r'["\']\/mnt\/[a-zA-Z]', "Hardcoded Unix /mnt path"),
    # Hardcoded relative paths with directory separators (must have path-like continuation)
    (r'["\']\.smartdrive[/\\\\][a-zA-Z]', "Hardcoded .smartdrive path (use Paths.smartdrive_dir())"),
    (r'["\']scripts[/\\\\][a-zA-Z]', "Hardcoded scripts path (use Paths.scripts_dir())"),
    (r'["\']keys[/\\\\][a-zA-Z]', "Hardcoded keys path (use Paths.keys_dir())"),
    (r'["\']integrity[/\\\\][a-zA-Z]', "Hardcoded integrity path (use Paths.integrity_dir())"),
    (r'["\']recovery[/\\\\][a-zA-Z]', "Hardcoded recovery path (use Paths.recovery_dir())"),
    # os.path.join with string literals that look like paths
    (r'os\.path\.join\s*\([^)]*["\'][a-zA-Z_][^"\']*[/\\\\][a-zA-Z]', "os.path.join with hardcoded path (use pathlib)"),
    # VeraCrypt executable names with .exe extension (should use Paths.veracrypt_exe())
    (r'["\']VeraCrypt\.exe["\']', "Hardcoded VeraCrypt.exe (use Paths.VERACRYPT_EXE_NAME)"),
    (r'["\']VeraCrypt Format\.exe["\']', "Hardcoded VeraCrypt Format.exe (use Paths.VERACRYPT_FORMAT_EXE_NAME)"),
    # Hardcoded VeraCrypt paths with Path()
    (r'\/\s*["\']VeraCrypt\.exe["\']', "Hardcoded VeraCrypt.exe path (use Paths.veracrypt_exe())"),
    (r'\/\s*["\']VeraCrypt Format\.exe["\']', "Hardcoded VeraCrypt Format.exe path"),
]

# Files to exclude from checking (core modules defining paths are allowed)
EXCLUDED_FILES = [
    ".smartdrive/core/paths.py",  # Path definitions live here (canonical location)
    "core/paths.py",  # Legacy exclusion (path definitions)
    "scripts/check_no_string_paths.py",  # This script
    "scripts/check_single_source_of_truth.py",  # Sibling enforcement script
    ".smartdrive/scripts/deploy.py",  # Deployment layout definitions (uses relative path patterns)
    "scripts/deploy.py",  # DEV wrapper (not deployed)
]

# Directories to exclude from checking
EXCLUDED_DIRS = [
    "venv",
    ".venv",
    ".venv-win",  # BUG-20260102-012: OS-specific venv
    ".venv-linux",  # BUG-20260102-012: OS-specific venv
    ".venv-mac",  # BUG-20260102-012: OS-specific venv
    "tests",  # Test fixtures use synthetic paths for config mocking
    "env",
    ".env",
    "__pycache__",
    ".git",
    "node_modules",
    "reference_scripts",  # Reference/legacy code
    "helper",  # Utility scripts not part of core
]

# Patterns that are false positives (allowed)
ALLOWED_PATTERNS = [
    r"#.*",  # Comments
    r'["\']\.smartdrive["\']',  # Just the directory name string (allowed)
    r'Path\s*\(\s*["\'][A-Z]:\\\\?["\']?\s*\)',  # Dynamic mount point like Path("Z:\\")
    r'["\'][A-Z]:\\\\?["\'].*mount',  # Mount-related drive letters
    r"target:.*\/mnt",  # Docstring examples
    r'["\']scripts["\']',  # Just the directory name string (allowed)
    r"SMARTDRIVE_DIR_NAME\s*=",  # Constant definition in paths.py
    r"SCRIPTS_SUBDIR\s*=",  # Constant definition in paths.py
    r"docstring",  # Docstrings explaining paths
    r'""".*"""',  # Multi-line docstrings
    r"'''.*'''",  # Multi-line docstrings
    r"dangerous_patterns\s*=",  # Safety check pattern definitions
    r'\(\s*["\'][A-Z]:.*["\'].*"',  # Tuple patterns for safety checks like ("C:", "desc")
    r'\.glob\s*\(\s*["\']Scripts/',  # Windows venv glob patterns (e.g., Scripts/python.exe)
    r'\.glob\s*\(\s*["\']bin/',  # Unix venv glob patterns (e.g., bin/python*)
]


def is_excluded_file(filepath: Path, repo_root: Path) -> bool:
    """Check if file should be excluded from checking."""
    rel_path = filepath.relative_to(repo_root)
    rel_str = str(rel_path).replace("\\", "/")

    # Check if in excluded directory
    parts = rel_path.parts
    for excl_dir in EXCLUDED_DIRS:
        if excl_dir in parts:
            return True

    # Check if file is explicitly excluded
    return any(excl in rel_str for excl in EXCLUDED_FILES)


def is_false_positive(line: str) -> bool:
    """Check if the line is a known false positive."""
    # Skip comments
    stripped = line.strip()
    if stripped.startswith("#"):
        return True

    # Skip docstrings
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return True

    # Check allowed patterns
    for pattern in ALLOWED_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True

    return False


def check_file(filepath: Path) -> List[Tuple[int, str, str]]:
    """
    Check a single file for forbidden path patterns.

    Returns list of (line_number, line_content, violation_description).
    """
    violations = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            if is_false_positive(line):
                continue

            for pattern, description in FORBIDDEN_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    # Double-check it's not in a comment at end of line
                    comment_pos = line.find("#")
                    if comment_pos != -1:
                        match = re.search(pattern, line[:comment_pos], re.IGNORECASE)
                        if not match:
                            continue

                    violations.append((line_num, line.strip()[:80], description))
                    break  # One violation per line is enough

    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)

    return violations


def main() -> int:
    """Main entry point."""
    # Find repository root
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent

    # Find all Python files
    python_files = list(repo_root.glob("**/*.py"))

    total_violations = 0
    files_with_violations = []

    print("Checking for forbidden string-based filesystem paths...")
    print(f"Repository root: {repo_root}")
    print(f"Files to check: {len(python_files)}")
    print()

    for filepath in sorted(python_files):
        if is_excluded_file(filepath, repo_root):
            continue

        violations = check_file(filepath)

        if violations:
            rel_path = filepath.relative_to(repo_root)
            files_with_violations.append(rel_path)

            print(f"❌ {rel_path}")
            for line_num, line_content, description in violations:
                print(f"   Line {line_num}: {description}")
                print(f"      {line_content}")
                total_violations += 1
            print()

    # Summary
    print("=" * 70)
    if total_violations == 0:
        print("✓ No forbidden path patterns found.")
        print("=" * 70)
        return 0
    else:
        print(f"❌ Found {total_violations} violation(s) in {len(files_with_violations)} file(s).")
        print()
        print("To fix these violations:")
        print("  1. Import Paths from core.paths")
        print("  2. Use Paths methods (e.g., Paths.scripts_dir(launcher_root))")
        print("  3. Use Path / operator for joins")
        print("  4. Convert to str() only at I/O boundaries")
        return 1


if __name__ == "__main__":
    sys.exit(main())
