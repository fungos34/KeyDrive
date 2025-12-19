#!/usr/bin/env python3
"""
Quarantine Pipeline - Move obsolete files to dated archive with documentation.

This script automates the obsolete file workflow defined in AGENT_ARCHITECTURE.md Section 15.3.

Usage:
    python scripts/quarantine.py <file_or_dir> --reason "Why this is obsolete"
    python scripts/quarantine.py path/to/file.py --reason "Replaced by new_file.py" --replacement "new_file.py"

The script will:
1. Create date-stamped directory: obsolete/YYYY-MM-DD/
2. Move file(s) to quarantine directory
3. Create/update WHY.md with documentation
4. Verify no broken imports after move
5. Output verification checklist
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Get project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Protected paths that cannot be quarantined
PROTECTED_PATTERNS = [
    "core/",  # SSOT modules
    "check_no_string_paths.py",
    "check_single_source_of_truth.py",
    "AGENT_ARCHITECTURE.md",
    "README.md",
]


def is_protected(path: Path) -> bool:
    """Check if a path is protected from quarantine."""
    rel_str = str(path.relative_to(PROJECT_ROOT))
    for pattern in PROTECTED_PATTERNS:
        if pattern in rel_str:
            return True
    return False


def find_references(filename: str) -> List[dict]:
    """Find all references to a file in the codebase."""
    references = []

    for path in PROJECT_ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".json", ".bat", ".sh", ".ps1", ".spec"}:
            if "obsolete" in str(path):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                if filename in content:
                    # Count occurrences
                    count = content.count(filename)
                    references.append({"file": str(path.relative_to(PROJECT_ROOT)), "count": count})
            except Exception:
                pass

    return references


def create_why_md(quarantine_dir: Path, files: List[Path], reason: str, replacement: Optional[str] = None) -> Path:
    """Create or update WHY.md in quarantine directory."""
    why_file = quarantine_dir / "WHY.md"

    content = f"""# Obsolete Files - {datetime.now().strftime("%Y-%m-%d")}

## Reason for Obsolescence

{reason}

"""

    if replacement:
        content += f"""## Replacement

- New file: `{replacement}`
- Migration: Functionality moved to replacement file(s)

"""

    content += """## Files Quarantined

| File | Original Path | Status |
|------|---------------|--------|
"""

    for f in files:
        rel_path = f.relative_to(PROJECT_ROOT) if f.is_relative_to(PROJECT_ROOT) else f
        content += f"| `{f.name}` | `{rel_path}` | Quarantined |\n"

    content += """

## Verification Checklist

Before permanent deletion, verify:

- [ ] All tests pass (`python -m pytest tests/ -v`)
- [ ] No broken imports (`python scripts/check_single_source_of_truth.py`)
- [ ] No path violations (`python scripts/check_no_string_paths.py`)
- [ ] Documentation updated (README.md, AGENT_ARCHITECTURE.md)
- [ ] No active references in codebase (run `grep -r "<filename>" .`)

## Safe to Delete After

- Date: {(datetime.now().replace(day=1) + timedelta(days=32)).replace(day=1).strftime("%Y-%m-%d")} (30 days from quarantine)
- Or: After next major release
- Condition: All verification checks pass

## Notes

- These files were moved using `scripts/quarantine.py`
- Review AGENT_ARCHITECTURE.md Section 15.3 for obsolete file policy
- Do NOT delete without completing verification checklist
"""

    # Import timedelta for the safe delete date
    from datetime import timedelta

    # Recompute safe delete date properly
    safe_date = datetime.now() + timedelta(days=30)
    content = content.replace(
        f"{(datetime.now().replace(day=1) + timedelta(days=32)).replace(day=1).strftime('%Y-%m-%d')}",
        safe_date.strftime("%Y-%m-%d"),
    )

    why_file.write_text(content, encoding="utf-8")
    return why_file


def quarantine_file(file_path: Path, reason: str, replacement: Optional[str] = None) -> bool:
    """Move a file to the quarantine directory."""
    if not file_path.exists():
        print(f"❌ Error: File not found: {file_path}")
        return False

    if is_protected(file_path):
        print(f"❌ Error: Cannot quarantine protected file: {file_path}")
        print("   Protected files include: core/* modules, enforcement scripts, README.md")
        return False

    # Check for active references
    references = find_references(file_path.name)
    if references:
        print(f"⚠️  Warning: Found {len(references)} reference(s) to {file_path.name}:")
        for ref in references:
            print(f"   - {ref['file']} ({ref['count']} occurrence(s))")
        print()
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            print("Aborted.")
            return False

    # Create quarantine directory
    date_str = datetime.now().strftime("%Y-%m-%d")
    quarantine_dir = PROJECT_ROOT / "obsolete" / date_str
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    # Move file
    dest = quarantine_dir / file_path.name
    if dest.exists():
        # Add suffix to avoid collision
        base = file_path.stem
        ext = file_path.suffix
        counter = 1
        while dest.exists():
            dest = quarantine_dir / f"{base}_{counter}{ext}"
            counter += 1

    shutil.move(str(file_path), str(dest))
    print(f"✓ Moved: {file_path} -> {dest}")

    # Create WHY.md
    why_file = create_why_md(quarantine_dir, [file_path], reason, replacement)
    print(f"✓ Created: {why_file}")

    return True


def verify_no_broken_imports() -> bool:
    """Run enforcement scripts to verify no broken imports."""
    print("\n" + "=" * 60)
    print("VERIFICATION: Running enforcement scripts...")
    print("=" * 60)

    scripts = [
        ("check_no_string_paths.py", "Path purity check"),
        ("check_single_source_of_truth.py", "SSOT compliance check"),
    ]

    all_passed = True
    for script, description in scripts:
        script_path = PROJECT_ROOT / "scripts" / script
        if script_path.exists():
            print(f"\n→ {description}...")
            result = subprocess.run(
                [sys.executable, str(script_path)], cwd=PROJECT_ROOT, capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"  ✓ {script}: PASSED")
            else:
                print(f"  ❌ {script}: FAILED")
                print(result.stdout)
                print(result.stderr)
                all_passed = False

    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Quarantine obsolete files with proper documentation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/quarantine.py old_module.py --reason "Replaced by new_module.py"
    python scripts/quarantine.py legacy/ --reason "Legacy code no longer needed" --replacement "scripts/"
        """,
    )
    parser.add_argument("path", type=str, help="File or directory to quarantine")
    parser.add_argument("--reason", "-r", type=str, required=True, help="Reason for obsolescence (required)")
    parser.add_argument("--replacement", type=str, default=None, help="Replacement file/module (optional)")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification after quarantine")
    args = parser.parse_args()

    target = PROJECT_ROOT / args.path
    if not target.exists():
        # Try relative to current directory
        target = Path(args.path).resolve()

    print("=" * 60)
    print("QUARANTINE PIPELINE")
    print("=" * 60)
    print(f"Target: {target}")
    print(f"Reason: {args.reason}")
    if args.replacement:
        print(f"Replacement: {args.replacement}")
    print()

    if target.is_file():
        success = quarantine_file(target, args.reason, args.replacement)
    elif target.is_dir():
        print(f"Processing directory: {target}")
        files = list(target.rglob("*"))
        files = [f for f in files if f.is_file()]
        if not files:
            print("No files found in directory.")
            return 1

        print(f"Found {len(files)} file(s) to quarantine:")
        for f in files:
            print(f"  - {f.relative_to(PROJECT_ROOT)}")
        print()
        response = input("Proceed? (y/N): ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

        success = True
        for f in files:
            if not quarantine_file(f, args.reason, args.replacement):
                success = False
    else:
        print(f"❌ Error: Path not found: {target}")
        return 1

    if success and not args.skip_verify:
        verify_no_broken_imports()

    print("\n" + "=" * 60)
    print("QUARANTINE COMPLETE")
    print("=" * 60)
    print(
        """
Next steps:
1. Update AGENT_ARCHITECTURE.md canonical tree (Section 15.2)
2. Update any imports that referenced the moved file(s)
3. Run full test suite: python -m pytest tests/ -v
4. Review WHY.md and complete verification checklist
    """
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
