#!/usr/bin/env python3
"""
Enforcement script: Check Single Source of Truth (SSOT) compliance.

This script verifies that:
1. VERSION is only defined in core/version.py
2. Constants are not duplicated across files
3. Security modes are only defined in core/modes.py
4. Config keys are only defined in core/constants.py
5. Limits are only defined in core/limits.py

Exit codes:
    0 - No violations found
    1 - Violations found

Usage:
    python scripts/check_single_source_of_truth.py
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# =============================================================================
# Core module paths (where definitions ARE allowed)
# After restructure: canonical location is .smartdrive/core/
# =============================================================================

CORE_MODULES = {
    "version": ".smartdrive/core/version.py",
    "constants": ".smartdrive/core/constants.py",
    "paths": ".smartdrive/core/paths.py",
    "limits": ".smartdrive/core/limits.py",
    "modes": ".smartdrive/core/modes.py",
}

# Legacy core module paths (for transition compatibility)
LEGACY_CORE_PATHS = {
    "version": "core/version.py",
    "constants": "core/constants.py",
    "paths": "core/paths.py",
    "limits": "core/limits.py",
    "modes": "core/modes.py",
}

# Enforcement scripts (excluded from checks)
ENFORCEMENT_SCRIPTS = [
    "scripts/check_no_string_paths.py",
    "scripts/check_single_source_of_truth.py",
]

# =============================================================================
# Patterns to detect violations
# =============================================================================

# VERSION definitions outside core/version.py
VERSION_PATTERNS = [
    (r'^VERSION\s*=\s*["\']', "VERSION constant definition"),
    (r'^__version__\s*=\s*["\']', "__version__ constant definition"),
    (r'VERSION\s*=\s*["\'][0-9]+\.[0-9]+', "VERSION string assignment"),
]

# Security mode string literals outside core/modes.py
SECURITY_MODE_LITERALS = [
    '"pw_only"',
    '"pw_keyfile"',
    '"pw_gpg_keyfile"',
    '"gpg_pw_only"',
    "'pw_only'",
    "'pw_keyfile'",
    "'pw_gpg_keyfile'",
    "'gpg_pw_only'",
]

# Config key literals that should use ConfigKeys class
CONFIG_KEY_LITERALS = [
    '"schema_version"',
    '"drive_name"',
    '"volume_path"',
    '"mount_letter"',
    '"mount_point"',
    '"veracrypt_path"',
    '"keyfile"',
    '"encrypted_keyfile"',
    '"seed_gpg_path"',
    '"last_password_change"',
    '"setup_date"',
]

# Timeout/retry literals that should use Limits class
LIMIT_LITERALS = [
    (r"\btimeout\s*=\s*(?:10|30|60)\b", "Hardcoded timeout (use Limits class)"),
    (r"\bmax_attempts\s*=\s*3\b", "Hardcoded max_attempts (use Limits class)"),
    (r"^TIMEOUT\s*=\s*\d+", "TIMEOUT constant (should be in Limits)"),
]

# User input confirmation strings that should use UserInputs class
USER_INPUT_LITERALS = [
    '"YES"',
    '"ERASE"',
    '"RECOVER"',
    '"REKEY"',
    '"I ACCEPT UNVERIFIED PASSWORD"',
]


def is_core_module(filepath: Path, repo_root: Path) -> bool:
    """Check if file is a core module (where definitions are allowed)."""
    rel_path = str(filepath.relative_to(repo_root)).replace("\\", "/")
    # Check both canonical (.smartdrive/core/) and legacy (core/) locations
    return rel_path.startswith(".smartdrive/core/") or rel_path.startswith("core/")


def is_excluded(filepath: Path, repo_root: Path) -> bool:
    """Check if file should be excluded from checking."""
    rel_path = str(filepath.relative_to(repo_root)).replace("\\", "/")

    # Exclude enforcement scripts
    if rel_path in ENFORCEMENT_SCRIPTS:
        return True

    # Excluded directories (third-party, reference code, caches)
    excluded_dirs = [
        "venv/",
        ".venv/",
        ".venv-win/",  # BUG-20260102-012: OS-specific venv
        ".venv-linux/",  # BUG-20260102-012: OS-specific venv
        ".venv-mac/",  # BUG-20260102-012: OS-specific venv
        "env/",
        ".env/",
        "__pycache__",
        ".git/",
        "node_modules/",
        "reference_scripts/",  # Legacy reference code
        "helper/",  # Utility scripts not part of core
    ]

    for excl_dir in excluded_dirs:
        if excl_dir in rel_path:
            return True

    return False


def check_version_violations(filepath: Path, content: str) -> List[Tuple[int, str]]:
    """Check for VERSION definitions outside core/version.py."""
    violations = []
    lines = content.split("\n")

    # Track if we're in an except block (fallback is allowed)
    in_except_block = False
    except_indent = 0

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Skip import statements (but not "except ImportError")
        if stripped.startswith(("import ", "from ")) or (" import " in stripped and not stripped.startswith("except")):
            continue

        # Track except blocks for fallback patterns
        if stripped.startswith("except"):
            in_except_block = True
            except_indent = len(line) - len(line.lstrip())
            continue

        # Exit except block when indentation decreases to or below except level
        if in_except_block and stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            # We're inside except block as long as indent is GREATER than except line
            if current_indent <= except_indent:
                in_except_block = False

        # Skip if in except block (these are fallbacks)
        if in_except_block:
            continue

        for pattern, description in VERSION_PATTERNS:
            if re.search(pattern, stripped):
                violations.append((line_num, f"{description}: {stripped[:60]}"))
                break

    return violations


def check_security_mode_violations(filepath: Path, content: str) -> List[Tuple[int, str]]:
    """Check for hardcoded security mode strings."""
    violations = []
    lines = content.split("\n")

    # Track if we're in an except block (fallback is allowed)
    in_except_block = False
    except_indent = 0

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Skip imports
        if "import" in stripped and "SecurityMode" in stripped:
            continue

        # Track except blocks for fallback patterns
        if stripped.startswith("except"):
            in_except_block = True
            except_indent = len(line) - len(line.lstrip())
            continue

        # Exit except block when indentation decreases to or below except level
        if in_except_block and stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            # We're inside except block as long as indent is GREATER than except line
            if current_indent <= except_indent:
                in_except_block = False

        # Skip if in except block (these are fallbacks)
        if in_except_block:
            continue

        # Skip enum definitions in modes.py (checked separately)
        if "SecurityMode." in stripped:
            continue

        for literal in SECURITY_MODE_LITERALS:
            if literal in line:
                # Check if it's an assignment (definition) vs usage
                if "=" in line and "SecurityMode" not in line:
                    violations.append((line_num, f"Hardcoded security mode: {literal}"))
                    break

    return violations


def check_config_key_violations(filepath: Path, content: str) -> List[Tuple[int, str]]:
    """Check for hardcoded config key strings."""
    violations = []
    lines = content.split("\n")

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Skip if using ConfigKeys class
        if "ConfigKeys." in line:
            continue

        for literal in CONFIG_KEY_LITERALS:
            if literal in line:
                # Check if accessing dict with literal key
                if f"[{literal}]" in line or f".get({literal}" in line:
                    violations.append((line_num, f"Hardcoded config key: {literal} (use ConfigKeys class)"))
                    break

    return violations


def check_limit_violations(filepath: Path, content: str) -> List[Tuple[int, str]]:
    """Check for hardcoded limit values."""
    violations = []
    lines = content.split("\n")

    # Track if we're in an except block (fallback is allowed)
    in_except_block = False
    except_indent = 0

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Track except blocks for fallback patterns
        if stripped.startswith("except"):
            in_except_block = True
            except_indent = len(line) - len(line.lstrip())
            continue

        # Exit except block when indentation decreases
        if in_except_block and stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= except_indent and not stripped.startswith("except"):
                in_except_block = False

        # Skip if in except block (these are fallbacks)
        if in_except_block:
            continue

        # Skip if using Limits class
        if "Limits." in line:
            continue

        for pattern, description in LIMIT_LITERALS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append((line_num, description))
                break

    return violations


def check_user_input_violations(filepath: Path, content: str) -> List[Tuple[int, str]]:
    """Check for hardcoded user input confirmation strings."""
    violations = []
    lines = content.split("\n")

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Skip if using UserInputs class
        if "UserInputs." in line:
            continue

        for literal in USER_INPUT_LITERALS:
            if literal in line:
                # Check if it's a comparison (validation)
                if "==" in line or "!=" in line or ".strip()" in line:
                    violations.append((line_num, f"Hardcoded user input: {literal} (use UserInputs class)"))
                    break

    return violations


def main() -> int:
    """Main entry point."""
    # Find repository root
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent

    # Verify core modules exist (check canonical .smartdrive/core/ location)
    print("Verifying core modules exist...")
    for name, path in CORE_MODULES.items():
        full_path = repo_root / path
        if not full_path.exists():
            # Check legacy location as fallback during transition
            legacy_path = repo_root / LEGACY_CORE_PATHS[name]
            if legacy_path.exists():
                print(f"  OK {LEGACY_CORE_PATHS[name]} (legacy location)")
            else:
                print(f"X Missing core module: {path}")
                return 1
        else:
            print(f"  OK {path}")
    print()

    # Find all Python files
    python_files = list(repo_root.glob("**/*.py"))

    total_violations = 0
    files_with_violations: Dict[Path, List[Tuple[int, str]]] = {}

    print("Checking for SSOT violations...")
    print(f"Repository root: {repo_root}")
    print(f"Files to check: {len(python_files)}")
    print()

    for filepath in sorted(python_files):
        rel_path = filepath.relative_to(repo_root)
        rel_str = str(rel_path).replace("\\", "/")

        # Skip excluded files
        if is_excluded(filepath, repo_root):
            continue

        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
            continue

        file_violations = []

        # VERSION check (only in non-core files, and not in core/version.py)
        if rel_str != CORE_MODULES["version"] and not is_core_module(filepath, repo_root):
            file_violations.extend(check_version_violations(filepath, content))

        # Security mode check (only in non-modes files)
        if rel_str != CORE_MODULES["modes"] and not is_core_module(filepath, repo_root):
            file_violations.extend(check_security_mode_violations(filepath, content))

        # Config key check (only in non-constants files)
        if rel_str != CORE_MODULES["constants"] and not is_core_module(filepath, repo_root):
            file_violations.extend(check_config_key_violations(filepath, content))

        # Limits check (only in non-limits files)
        if rel_str != CORE_MODULES["limits"] and not is_core_module(filepath, repo_root):
            file_violations.extend(check_limit_violations(filepath, content))

        # User input check (only in non-constants files)
        if rel_str != CORE_MODULES["constants"] and not is_core_module(filepath, repo_root):
            file_violations.extend(check_user_input_violations(filepath, content))

        if file_violations:
            files_with_violations[rel_path] = file_violations
            total_violations += len(file_violations)

    # Report violations
    if files_with_violations:
        for rel_path, violations in sorted(files_with_violations.items()):
            print(f"X {rel_path}")
            for line_num, description in violations:
                print(f"   Line {line_num}: {description}")
            print()

    # Summary
    print("=" * 70)
    if total_violations == 0:
        print("OK No SSOT violations found.")
        print("=" * 70)
        return 0
    else:
        print(f"X Found {total_violations} violation(s) in {len(files_with_violations)} file(s).")
        print()
        print("To fix these violations:")
        print("  1. Import constants from core.constants")
        print("  2. Import Limits from core.limits")
        print("  3. Import SecurityMode from core.modes")
        print("  4. Import VERSION from core.version")
        print("  5. Use imported constants instead of string literals")
        return 1


if __name__ == "__main__":
    sys.exit(main())
