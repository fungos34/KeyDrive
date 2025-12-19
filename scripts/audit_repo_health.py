#!/usr/bin/env python3
"""
Repository Health Audit Script

Cross-platform, deterministic JSON reporting for:
- Unused files and folders
- References to deprecated files
- Modules not being imported or used
- Payload drift detection (files not needed in deployment)

Output: reports/repo_health_YYYY-MM-DD_HHMMSS.json

Usage:
    python scripts/audit_repo_health.py [--output reports/] [--verbose]
"""

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

# Get project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Directories to exclude from analysis
EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "*.egg-info",
    "obsolete",  # Already obsolete - don't flag again
    "helper",  # Development utilities - excluded per AGENT_ARCHITECTURE.md
    "reference_scripts",  # Legacy reference code - excluded per AGENT_ARCHITECTURE.md
}

# Files to exclude from analysis
EXCLUDED_FILES = {
    ".gitignore",
    ".DS_Store",
    "Thumbs.db",
    "*.pyc",
    "*.pyo",
    "*.pyd",
}

# Core SSOT modules that MUST NOT be flagged as unused
PROTECTED_MODULES = {
    "core/__init__.py",
    "core/version.py",
    "core/constants.py",
    "core/config.py",
    "core/paths.py",
    "core/limits.py",
    "core/modes.py",
    "core/platform.py",
    "core/safety.py",
}

# Files that are entry points (may not be imported but are used)
ENTRY_POINTS = {
    "setup.py",
    "mount.py",
    "unmount.py",
    "recovery.py",
    "smartdrive.py",
    "gui.py",
    "gui_launcher.py",
    "deploy.py",
    "update.py",
    "rekey.py",
    "keyfile.py",
}

# Scripts that are standalone checks (entry points)
CHECK_SCRIPTS = {
    "check_no_string_paths.py",
    "check_single_source_of_truth.py",
    "audit_repo_health.py",
}


def is_excluded_path(path: Path) -> bool:
    """Check if path should be excluded from analysis."""
    parts = path.parts
    for excluded in EXCLUDED_DIRS:
        if excluded in parts:
            return True
    for excluded in EXCLUDED_FILES:
        if path.name == excluded or (excluded.startswith("*") and path.name.endswith(excluded[1:])):
            return True
    return False


def find_all_python_files(root: Path) -> List[Path]:
    """Find all Python files in the project."""
    python_files = []
    for path in root.rglob("*.py"):
        if not is_excluded_path(path.relative_to(root)):
            python_files.append(path)
    return python_files


def extract_imports(file_path: Path) -> Set[str]:
    """Extract all imported modules from a Python file."""
    imports = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except (SyntaxError, UnicodeDecodeError) as e:
        # Can't parse - skip
        pass
    return imports


def find_string_references(root: Path, filename: str) -> List[Dict[str, Any]]:
    """Find all string references to a filename across the project."""
    references = []
    pattern = re.compile(rf"\b{re.escape(filename)}\b")

    for path in root.rglob("*"):
        if path.is_file() and not is_excluded_path(path.relative_to(root)):
            if path.suffix in {".py", ".md", ".json", ".txt", ".sh", ".bat", ".ps1", ".spec"}:
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for match in pattern.finditer(content):
                        line_no = content[: match.start()].count("\n") + 1
                        references.append(
                            {
                                "file": str(path.relative_to(root)),
                                "line": line_no,
                                "context": content[max(0, match.start() - 30) : match.end() + 30].strip(),
                            }
                        )
                except Exception:
                    pass
    return references


def analyze_module_usage(root: Path, python_files: List[Path]) -> Dict[str, Any]:
    """Analyze which modules are imported and which are potentially unused."""
    # Build import graph
    all_imports: Set[str] = set()
    file_imports: Dict[str, Set[str]] = {}

    for py_file in python_files:
        rel_path = str(py_file.relative_to(root))
        imports = extract_imports(py_file)
        file_imports[rel_path] = imports
        all_imports.update(imports)

    # Find local modules that are never imported
    local_modules: Set[str] = set()
    for py_file in python_files:
        rel_path = py_file.relative_to(root)
        # Module name is filename without .py
        module_name = py_file.stem
        # Also track parent package
        if len(rel_path.parts) > 1:
            package = rel_path.parts[0]
            local_modules.add(package)
        local_modules.add(module_name)

    # Identify potentially unused modules
    unused_modules = []
    for py_file in python_files:
        rel_path = py_file.relative_to(root)
        rel_str = str(rel_path)
        module_name = py_file.stem

        # Skip protected and entry point files
        if rel_str in PROTECTED_MODULES:
            continue
        if module_name in ENTRY_POINTS:
            continue
        if module_name in CHECK_SCRIPTS:
            continue

        # Check if this module is imported anywhere
        is_imported = False
        for other_file, imports in file_imports.items():
            if other_file == rel_str:
                continue
            if module_name in imports:
                is_imported = True
                break
            # Check for package imports (e.g., "from core.paths import Paths")
            for imp in imports:
                if module_name in imp:
                    is_imported = True
                    break

        # Also check string references
        string_refs = find_string_references(root, py_file.name)

        if not is_imported and len(string_refs) <= 1:  # Only self-reference
            unused_modules.append(
                {
                    "file": rel_str,
                    "module": module_name,
                    "string_references": len(string_refs),
                    "reason": "Module not imported by any other Python file",
                }
            )

    return {"total_modules": len(python_files), "potentially_unused": unused_modules}


def find_deprecated_references(root: Path) -> List[Dict[str, Any]]:
    """Find references to deprecated or obsolete files."""
    deprecated_refs = []

    # Check obsolete directory for filenames to search for
    obsolete_dir = root / "obsolete"
    if obsolete_dir.exists():
        for obsolete_file in obsolete_dir.rglob("*.py"):
            filename = obsolete_file.name
            refs = find_string_references(root, filename)
            # Filter out references in obsolete dir itself
            refs = [r for r in refs if not r["file"].startswith("obsolete/")]
            if refs:
                deprecated_refs.append(
                    {"obsolete_file": str(obsolete_file.relative_to(root)), "active_references": refs}
                )

    return deprecated_refs


def analyze_deployment_drift(root: Path) -> Dict[str, Any]:
    """Analyze files that may cause deployment payload drift."""
    smartdrive_dir = root / ".smartdrive"
    if not smartdrive_dir.exists():
        return {"error": ".smartdrive directory not found"}

    # Files that should be deployed
    deployed_files = set()
    for path in smartdrive_dir.rglob("*"):
        if path.is_file() and not is_excluded_path(path.relative_to(root)):
            deployed_files.add(str(path.relative_to(smartdrive_dir)))

    # Check deploy.py for file list (if exists)
    deploy_script = root / ".smartdrive" / "scripts" / "deploy.py"
    if deploy_script.exists():
        # Just report the deployed files count
        pass

    return {"deployed_file_count": len(deployed_files), "smartdrive_files": sorted(list(deployed_files))}


def find_orphaned_tests(root: Path) -> List[Dict[str, Any]]:
    """Find test files that reference non-existent modules."""
    orphaned = []
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return orphaned

    for test_file in tests_dir.rglob("test_*.py"):
        imports = extract_imports(test_file)
        for imp in imports:
            # Check if the imported module exists
            if imp not in {
                "os",
                "sys",
                "pytest",
                "unittest",
                "pathlib",
                "json",
                "tempfile",
                "datetime",
                "re",
                "shutil",
                "subprocess",
                "collections",
                "typing",
                "functools",
                "contextlib",
                "io",
                "copy",
                "hashlib",
                "base64",
                "secrets",
                "uuid",
                "platform",
                "argparse",
                "logging",
                "warnings",
                "textwrap",
                "time",
                "threading",
                "queue",
                "dataclasses",
                "enum",
            }:
                # Check local modules
                possible_paths = [
                    root / f"{imp}.py",
                    root / imp / "__init__.py",
                    root / ".smartdrive" / f"{imp}.py",
                    root / ".smartdrive" / imp / "__init__.py",
                    root / ".smartdrive" / "scripts" / f"{imp}.py",
                    root / ".smartdrive" / "core" / f"{imp}.py",
                ]
                exists = any(p.exists() for p in possible_paths)
                if not exists and imp not in {"core", "scripts", "PyQt6", "cryptography"}:
                    orphaned.append({"test_file": str(test_file.relative_to(root)), "missing_import": imp})

    return orphaned


def generate_report(root: Path, verbose: bool = False) -> Dict[str, Any]:
    """Generate comprehensive repository health report."""
    python_files = find_all_python_files(root)

    report = {
        "timestamp": datetime.now().isoformat(),
        "project_root": str(root),
        "summary": {"total_python_files": len(python_files), "issues_found": 0},
        "module_analysis": analyze_module_usage(root, python_files),
        "deprecated_references": find_deprecated_references(root),
        "deployment_drift": analyze_deployment_drift(root),
        "orphaned_tests": find_orphaned_tests(root),
    }

    # Count issues
    issues = 0
    issues += len(report["module_analysis"].get("potentially_unused", []))
    issues += len(report["deprecated_references"])
    issues += len(report["orphaned_tests"])
    report["summary"]["issues_found"] = issues

    if verbose:
        report["all_python_files"] = [str(f.relative_to(root)) for f in python_files]

    return report


def main():
    parser = argparse.ArgumentParser(description="Repository Health Audit")
    parser.add_argument(
        "--output", "-o", type=str, default="reports/", help="Output directory for reports (default: reports/)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Include verbose file listings")
    parser.add_argument("--stdout", action="store_true", help="Print report to stdout instead of file")
    args = parser.parse_args()

    print("=" * 60)
    print("REPOSITORY HEALTH AUDIT")
    print("=" * 60)
    print(f"Project root: {PROJECT_ROOT}")
    print()

    report = generate_report(PROJECT_ROOT, verbose=args.verbose)

    # Summary output
    print(f"Total Python files: {report['summary']['total_python_files']}")
    print(f"Issues found: {report['summary']['issues_found']}")
    print()

    if report["module_analysis"]["potentially_unused"]:
        print("[!] Potentially unused modules:")
        for mod in report["module_analysis"]["potentially_unused"]:
            print(f"   - {mod['file']}: {mod['reason']}")
        print()

    if report["deprecated_references"]:
        print("[!] References to obsolete files:")
        for ref in report["deprecated_references"]:
            print(f"   - {ref['obsolete_file']} referenced in:")
            for r in ref["active_references"]:
                print(f"     * {r['file']}:{r['line']}")
        print()

    if report["orphaned_tests"]:
        print("[!] Orphaned test imports:")
        for orphan in report["orphaned_tests"]:
            print(f"   - {orphan['test_file']}: missing {orphan['missing_import']}")
        print()

    if args.stdout:
        print(json.dumps(report, indent=2))
    else:
        # Save to file
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = output_dir / f"repo_health_{timestamp}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"[OK] Report saved to: {output_file}")

    print("=" * 60)

    # Exit with error code if issues found
    return 1 if report["summary"]["issues_found"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
