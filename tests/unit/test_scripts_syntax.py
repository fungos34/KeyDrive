#!/usr/bin/env python3
"""
Unit tests to ensure all Python scripts in .smartdrive/scripts/ have valid syntax
and can be imported without errors.

This test validates:
1. Python syntax is valid (no SyntaxError)
2. All imports can be resolved (no ImportError for local modules)
3. Scripts can be imported without runtime errors

Per AGENT_ARCHITECTURE.md:
- Uses pathlib.Path for all file operations
- No hardcoded paths
- Platform-independent
"""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

# Add project root and .smartdrive to path
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"
_scripts_dir = _smartdrive_root / "scripts"

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


def get_all_script_files():
    """Get all Python files in .smartdrive/scripts/ directory."""
    if not _scripts_dir.exists():
        pytest.skip(f"Scripts directory not found: {_scripts_dir}")

    # Get all .py files, excluding __pycache__ and test files
    script_files = [f for f in _scripts_dir.glob("*.py") if f.is_file() and not f.name.startswith("_")]

    return sorted(script_files)


@pytest.mark.parametrize("script_path", get_all_script_files())
def test_script_syntax_valid(script_path):
    """
    Test that each script has valid Python syntax.

    This uses ast.parse() to validate syntax without executing code.
    """
    with open(script_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    try:
        ast.parse(source_code, filename=str(script_path))
    except SyntaxError as e:
        pytest.fail(f"Syntax error in {script_path.name}:\n" f"  Line {e.lineno}: {e.msg}\n" f"  {e.text}")


@pytest.mark.parametrize("script_path", get_all_script_files())
def test_script_importable(script_path):
    """
    Test that each script can be imported without errors.

    This validates that:
    - All imports resolve correctly
    - No import-time code crashes
    - Module structure is valid

    Note: Scripts with argparse/main() won't execute, only import.
    """
    script_name = script_path.stem

    # Scripts that execute at top level - verify syntax only (no import)
    syntax_only_scripts = {
        "gui_launcher",  # Calls main() at top level which launches GUI
        "recovery",  # Has optional dependencies (mnemonic, argon2-cffi) that may not be installed
    }

    if script_name in syntax_only_scripts:
        # Verify syntax without importing (avoids GUI launch)
        import ast

        try:
            source = script_path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(script_path))
            # Syntax is valid - test passes
            return
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {script_name}:\n" f"  Line {e.lineno}: {e.msg}")

    try:
        # Load module spec
        spec = importlib.util.spec_from_file_location(f"scripts.{script_name}", script_path)

        if spec is None or spec.loader is None:
            pytest.fail(f"Could not load module spec for {script_name}")

        # Create module
        module = importlib.util.module_from_spec(spec)

        # Add to sys.modules to allow imports to find it
        sys.modules[f"scripts.{script_name}"] = module

        # Execute module (import it)
        spec.loader.exec_module(module)

    except SyntaxError as e:
        pytest.fail(f"Syntax error importing {script_name}:\n" f"  Line {e.lineno}: {e.msg}\n" f"  {e.text}")
    except ImportError as e:
        pytest.fail(
            f"Import error in {script_name}:\n"
            f"  {e}\n"
            f"  This usually means missing core modules or circular imports."
        )
    except Exception as e:
        pytest.fail(f"Runtime error importing {script_name}:\n" f"  {type(e).__name__}: {e}")


def test_all_scripts_found():
    """
    Sanity check that we found a reasonable number of scripts.

    This prevents test from silently passing if script directory is empty.
    """
    scripts = get_all_script_files()

    assert len(scripts) > 0, f"No scripts found in {_scripts_dir}"

    # We expect at least these core scripts
    expected_scripts = {
        "mount.py",
        "unmount.py",
        "setup.py",
        "recovery.py",
        "smartdrive.py",
        "gui.py",
    }

    found_names = {s.name for s in scripts}
    missing = expected_scripts - found_names

    if missing:
        pytest.fail(f"Expected scripts not found: {missing}\n" f"Found: {found_names}")


def test_no_syntax_errors_in_core():
    """
    Test that all core modules also have valid syntax.

    Core modules are dependencies for scripts, so they must be valid.
    """
    core_dir = _smartdrive_root / "core"

    if not core_dir.exists():
        pytest.skip(f"Core directory not found: {core_dir}")

    core_files = [f for f in core_dir.glob("*.py") if f.is_file() and not f.name.startswith("_")]

    for core_file in core_files:
        with open(core_file, "r", encoding="utf-8") as f:
            source_code = f.read()

        try:
            ast.parse(source_code, filename=str(core_file))
        except SyntaxError as e:
            pytest.fail(f"Syntax error in core/{core_file.name}:\n" f"  Line {e.lineno}: {e.msg}\n" f"  {e.text}")


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v"])
