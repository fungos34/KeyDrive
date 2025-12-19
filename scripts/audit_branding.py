#!/usr/bin/env python3
"""
Branding Audit Script - Enforces branding consistency

Fails if forbidden terms appear in documentation.
Per AGENT_ARCHITECTURE.md: README-first, consistent branding.

Exit codes:
  0: All checks pass
  1: Forbidden branding found
"""

import sys
from pathlib import Path

# Forbidden terms (case-insensitive)
FORBIDDEN_TERMS = [
    "SmartDrive",
]

# Allowed file patterns
DOC_PATTERNS = [
    "*.md",
    "*.txt",
    "README*",
]

# Excluded paths (may contain legacy terms or meta-references)
EXCLUDED_PATHS = [
    "obsolete/",
    ".git/",
    "__pycache__/",
    "*.pyc",
    "reports/",
    "*COMPLETION_REPORT*",
    "*VERIFICATION_REPORT*",
    "PART*.md",  # Part documentation may reference branding changes
]


def should_check_file(file_path: Path) -> bool:
    """Determine if file should be checked."""
    # Check excluded paths
    for excluded in EXCLUDED_PATHS:
        if excluded.endswith("/"):
            if excluded.rstrip("/") in file_path.parts:
                return False
        elif file_path.match(excluded):
            return False

    # Check if matches doc patterns
    for pattern in DOC_PATTERNS:
        if file_path.match(pattern):
            return True

    return False


def check_file(file_path: Path) -> list:
    """Check file for forbidden terms. Returns list of violations."""
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        for term in FORBIDDEN_TERMS:
            if term.lower() in content.lower():
                # Find line numbers
                lines = content.splitlines()
                for i, line in enumerate(lines, 1):
                    if term.lower() in line.lower():
                        violations.append(
                            {"file": str(file_path), "line": i, "term": term, "context": line.strip()[:80]}
                        )

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")

    return violations


def audit_branding(root_dir: Path) -> int:
    """Audit all documentation for branding violations."""
    violations = []

    for file_path in root_dir.rglob("*"):
        if file_path.is_file() and should_check_file(file_path):
            file_violations = check_file(file_path)
            violations.extend(file_violations)

    if violations:
        print("=" * 70)
        print("BRANDING AUDIT FAILED")
        print("=" * 70)
        print(f"\nFound {len(violations)} forbidden term(s):\n")

        for v in violations:
            print(f"  {v['file']}:{v['line']}")
            print(f"    Term: {v['term']}")
            print(f"    Context: {v['context']}")
            print()

        print("Resolution: Replace forbidden terms with approved branding.")
        return 1

    print("[PASS] Branding audit passed (no forbidden terms found)")
    return 0


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    sys.exit(audit_branding(project_root))
