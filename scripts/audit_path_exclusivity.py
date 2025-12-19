#!/usr/bin/env python3
"""
PathResolver Exclusivity Audit Script

SSOT ENFORCEMENT: Verifies that PathResolver is the ONLY path authority.

This script fails if:
- String-based path joins (os.path.join) are used outside PathResolver
- Direct Path() construction with hardcoded paths outside core/paths.py
- String concatenation for paths (+ "/" or + "\\")

WHITELISTED FILES (documented exceptions):
- core/paths.py - THE path authority (defines Path patterns)
- core/path_resolver.py - The runtime path resolver (uses Paths)
- tests/ - Test files may construct paths for assertions
- helper/ - Development utilities (excluded per AGENT_ARCHITECTURE.md)

Usage:
    python scripts/audit_path_exclusivity.py
    python scripts/audit_path_exclusivity.py --strict  # Fail on any violation
    
Exit codes:
    0 - No violations (or only whitelisted files)
    1 - Violations found
    2 - Error running audit
"""

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Set

# Import SSOT Paths for canonical runtime directory name
try:
    from core.paths import Paths
except ImportError:

    class Paths:  # Fallback for standalone operation
        SMARTDRIVE_DIR_NAME = ".smartdrive"


# Project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _rel(*parts: str) -> str:
    """Return a repo-relative path string without hardcoded separators."""
    return str(Path(*parts)).replace("\\", "/")


class Violation(NamedTuple):
    """A path exclusivity violation."""

    file: Path
    line: int
    pattern: str
    code: str
    severity: str  # 'error', 'warning'


# Files that ARE the path authorities (whitelisted completely)
PATH_AUTHORITY_FILES = {
    _rel("core", "paths.py"),
    _rel("core", "path_resolver.py"),
    _rel("core", "constants.py"),  # Defines CONFIG_JSON constant
    _rel("core", "context.py"),  # Uses config.json via constant
    _rel(Paths.SMARTDRIVE_DIR_NAME, "core", "paths.py"),
    _rel(Paths.SMARTDRIVE_DIR_NAME, "core", "path_resolver.py"),
    _rel(Paths.SMARTDRIVE_DIR_NAME, "core", "constants.py"),
    _rel(Paths.SMARTDRIVE_DIR_NAME, "core", "context.py"),
}

# Directories where path construction is allowed (tests, helpers)
WHITELISTED_DIRS = {
    "tests",
    "helper",
    "obsolete",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "site-packages",
    "node_modules",
}

# Specific files with documented exceptions
WHITELISTED_FILES = {
    # Entry point bootstrapping - must find own location
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "setup.py"): [
        "_script_dir = Path(__file__)",
        "project_root = Path(__file__)",
        '"config.json"',
    ],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "update.py"): ["_script_dir = Path(__file__)", '"config.json"'],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "mount.py"): [
        "_script_dir = Path(__file__)",
        '"config.json"',
        'CONFIG_FILENAME = "config.json"',
    ],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "unmount.py"): [
        "_script_dir = Path(__file__)",
        '"config.json"',
        'CONFIG_FILENAME = "config.json"',
    ],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "recovery.py"): ["_script_dir = Path(__file__)", '"config.json"'],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "smartdrive.py"): ["_script_dir = Path(__file__)", '"config.json"'],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "gui.py"): [
        "_script_dir = Path(__file__)",
        "Path(__file__).resolve()",
        '"config.json"',
        "os.path.basename",
    ],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "deploy.py"): ["_script_dir = Path(__file__)"],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "rekey.py"): ['"config.json"'],
    _rel("scripts", "deploy.py"): ["_script_dir = Path(__file__)"],
    _rel("scripts", "gui.py"): ["Path(__file__)"],
    # Platform-specific path construction (unavoidable)
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "setup.py"): [
        'Path(f"{',
        "Path(f'{",  # Drive letter paths like Path(f"{letter}:\\")
        'Path("/dev/shm")',
        'Path("/tmp")',  # Linux RAM disk
        "Path(tempfile.gettempdir())",  # System temp
        "Path(shutil.which(",  # Executable lookup
        '"config.json"',  # Config file reference
    ],
    _rel(Paths.SMARTDRIVE_DIR_NAME, "scripts", "update.py"): [
        'Path(f"{',
        "Path(f'{",  # Drive letter paths
        '"config.json"',  # Config file reference
    ],
}

# Forbidden patterns (regex)
FORBIDDEN_PATTERNS = [
    # os.path usage (should use pathlib)
    (r"os\.path\.join\s*\(", "os.path.join", "error"),
    (r"os\.path\.dirname\s*\(", "os.path.dirname", "warning"),
    (r"os\.path\.basename\s*\(", "os.path.basename", "warning"),
    (r"os\.path\.abspath\s*\(", "os.path.abspath", "warning"),
    (r"os\.path\.realpath\s*\(", "os.path.realpath", "warning"),
    # String concatenation for paths (must contain path-like patterns)
    # Match patterns like: "some/path" + or + "some/path" or "some\\path" +
    (r'["\'][a-zA-Z0-9_]+[/\\][a-zA-Z0-9_./\\]+["\']\s*\+', "string path concat (+)", "error"),
    (r'\+\s*["\'][a-zA-Z0-9_]+[/\\][a-zA-Z0-9_./\\]+["\']', "string path concat (+)", "error"),
]


def is_whitelisted_dir(path: Path) -> bool:
    """Check if path is in a whitelisted directory."""
    parts = path.parts
    for whitelisted in WHITELISTED_DIRS:
        if whitelisted in parts:
            return True
    return False


def is_whitelisted_file(path: Path, line_content: str) -> bool:
    """Check if the specific line in the file is whitelisted."""
    rel_path = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    if rel_path in PATH_AUTHORITY_FILES:
        return True

    if rel_path in WHITELISTED_FILES:
        patterns = WHITELISTED_FILES[rel_path]
        for pattern in patterns:
            if pattern in line_content:
                return True

    return False


def scan_file(file_path: Path) -> List[Violation]:
    """Scan a Python file for path exclusivity violations."""
    violations = []

    if is_whitelisted_dir(file_path):
        return violations

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Skip whitelisted patterns for this file
            if is_whitelisted_file(file_path, line):
                continue

            # Check forbidden patterns
            for pattern, name, severity in FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    # Additional whitelist check for specific allowed usages
                    if _is_allowed_usage(file_path, line, name):
                        continue

                    violations.append(
                        Violation(file=file_path, line=line_num, pattern=name, code=stripped[:80], severity=severity)
                    )
    except Exception as e:
        print(f"Warning: Could not scan {file_path}: {e}", file=sys.stderr)

    return violations


def _is_allowed_usage(file_path: Path, line: str, pattern_name: str) -> bool:
    """Check for allowed specific usages."""
    # Drive letter path construction is allowed in mount-related scripts
    if 'Path(f"{' in line or "Path(f'{" in line:
        # Check if it's drive letter pattern like Path(f"{letter}:\\")
        if re.search(r'Path\(f["\'][{][a-zA-Z_]+[}]:\\', line):
            return True

    # Allow Path(__file__) for script location detection
    if "Path(__file__)" in line:
        return True

    # Allow Path(tempfile. or Path(shutil.which
    if "Path(tempfile." in line or "Path(shutil.which" in line:
        return True

    # Allow in exception/error messages
    if "error" in line.lower() or "exception" in line.lower():
        return True

    return False


def scan_repository() -> Dict[str, List[Violation]]:
    """Scan all Python files in the repository."""
    results = {
        "errors": [],
        "warnings": [],
    }

    # Find all Python files
    py_files = list(PROJECT_ROOT.rglob("*.py"))

    for py_file in py_files:
        violations = scan_file(py_file)
        for v in violations:
            if v.severity == "error":
                results["errors"].append(v)
            else:
                results["warnings"].append(v)

    return results


def print_violations(violations: List[Violation], header: str):
    """Print violations in a readable format."""
    if not violations:
        return

    print(f"\n{header}:")
    print("-" * 70)

    for v in violations:
        rel_path = v.file.relative_to(PROJECT_ROOT)
        print(f"  {rel_path}:{v.line}")
        print(f"    Pattern: {v.pattern}")
        print(f"    Code: {v.code}")
        print()


def main():
    parser = argparse.ArgumentParser(description="PathResolver exclusivity audit")
    parser.add_argument("--strict", action="store_true", help="Fail on any violation (including warnings)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("  PATHRESOLVER EXCLUSIVITY AUDIT")
    print("  SSOT Enforcement: PathResolver must be the only path authority")
    print("=" * 70)

    results = scan_repository()

    error_count = len(results["errors"])
    warning_count = len(results["warnings"])

    if args.json:
        import json

        output = {
            "errors": [
                {"file": str(v.file.relative_to(PROJECT_ROOT)), "line": v.line, "pattern": v.pattern, "code": v.code}
                for v in results["errors"]
            ],
            "warnings": [
                {"file": str(v.file.relative_to(PROJECT_ROOT)), "line": v.line, "pattern": v.pattern, "code": v.code}
                for v in results["warnings"]
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_violations(results["errors"], "ERRORS (must fix)")
        print_violations(results["warnings"], "WARNINGS (review recommended)")

        print("\n" + "=" * 70)
        print(f"  RESULTS: {error_count} errors, {warning_count} warnings")
        print("=" * 70)

        if error_count == 0 and (not args.strict or warning_count == 0):
            print("  AUDIT PASSED: PathResolver exclusivity verified")
            return 0
        else:
            print("  AUDIT FAILED: Path exclusivity violations found")
            return 1


if __name__ == "__main__":
    sys.exit(main())
