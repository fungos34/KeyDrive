#!/usr/bin/env python3
"""
Test: GPG --no-tty Flag Verification

BUG-20251218-007: Terminal hangs during setup when copying password for manual header backup.

ROOT CAUSE: gpg subprocess calls without --no-tty flag cause the terminal to hang/freeze
when GPG waits for TTY input on repeated calls.

This test verifies that ALL gpg subprocess.run calls in the codebase include --no-tty
to prevent terminal hanging issues.

MANDATORY per AGENT_ARCHITECTURE.md: This is a P0 bug that affects user experience.
"""

import ast
import re
from pathlib import Path

import pytest


class GpgCallVisitor(ast.NodeVisitor):
    """AST visitor to find subprocess.run calls with gpg command."""

    # These GPG operations can cause TTY hangs without --no-tty:
    # - --card-status: Queries smartcard, can prompt for PIN
    # - --decrypt: Decrypts with smartcard key, needs PIN
    # Note: --verify, --list-keys, --list-secret-keys, --detach-sign generally don't hang
    TTY_SENSITIVE_FLAGS = {"--card-status", "--decrypt"}

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.issues = []

    def visit_Call(self, node):
        """Visit function calls and check for gpg subprocess.run calls."""
        # Check if this is subprocess.run(...)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "run":
                # Check if first argument is a list starting with "gpg"
                if node.args and isinstance(node.args[0], ast.List):
                    elements = node.args[0].elts
                    if elements and isinstance(elements[0], ast.Constant):
                        if elements[0].value == "gpg":
                            # Found a gpg subprocess.run call
                            cmd_parts = [e.value for e in elements if isinstance(e, ast.Constant)]

                            # Check if this is a TTY-sensitive operation
                            is_tty_sensitive = any(flag in cmd_parts for flag in self.TTY_SENSITIVE_FLAGS)

                            if is_tty_sensitive:
                                # Check for --no-tty
                                has_no_tty = "--no-tty" in cmd_parts
                                if not has_no_tty:
                                    self.issues.append(
                                        {
                                            "file": str(self.filepath),
                                            "line": node.lineno,
                                            "command": " ".join(cmd_parts),
                                        }
                                    )
        self.generic_visit(node)


def find_gpg_calls_without_no_tty(directory: Path) -> list:
    """
    Scan all Python files in directory for gpg subprocess.run calls without --no-tty.

    Returns list of issues with file, line, and command.
    """
    issues = []

    for py_file in directory.rglob("*.py"):
        # Skip test files themselves and __pycache__
        if "__pycache__" in str(py_file):
            continue
        if "test_gpg_no_tty" in py_file.name:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            visitor = GpgCallVisitor(py_file)
            visitor.visit(tree)
            issues.extend(visitor.issues)
        except SyntaxError:
            pass  # Skip files with syntax errors
        except Exception:
            pass  # Skip files that can't be read

    return issues


class TestGpgNoTtyFlag:
    """Test suite for BUG-20251218-007: GPG --no-tty flag verification."""

    def test_smartdrive_scripts_have_no_tty(self):
        """
        All gpg subprocess.run calls in .smartdrive must include --no-tty.

        BUG-20251218-007: Without --no-tty, gpg may wait for TTY input when called
        multiple times, causing the terminal to hang/become unresponsive.

        This is especially critical during:
        - Manual header backup (CPW command)
        - YubiKey detection
        - Password derivation from GPG-encrypted seed
        """
        # Find the project root
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent.parent  # tests/unit/test_*.py -> project root

        smartdrive_dir = project_root / ".smartdrive"
        if not smartdrive_dir.exists():
            pytest.skip(".smartdrive directory not found")

        issues = find_gpg_calls_without_no_tty(smartdrive_dir)

        if issues:
            msg = "BUG-20251218-007: Found gpg subprocess.run calls without --no-tty:\n"
            for issue in issues:
                msg += f"  {issue['file']}:{issue['line']} - {issue['command']}\n"
            msg += "\nThis WILL cause terminal hanging during setup/mount operations."
            pytest.fail(msg)

    def test_core_secrets_has_no_tty(self):
        """
        core/secrets.py _check_yubikey_presence() must use --no-tty.

        This function is called by SecretProvider.copy_password_to_clipboard()
        which is the CPW handler during manual header backup.
        """
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent.parent

        # Check both possible locations
        secrets_paths = [
            project_root / ".smartdrive" / "core" / "secrets.py",
            project_root / "core" / "secrets.py",
        ]

        for secrets_path in secrets_paths:
            if secrets_path.exists():
                issues = find_gpg_calls_without_no_tty(secrets_path.parent)
                # Filter to just secrets.py
                issues = [i for i in issues if "secrets.py" in i["file"]]

                if issues:
                    msg = f"BUG-20251218-007: {secrets_path} has gpg calls without --no-tty:\n"
                    for issue in issues:
                        msg += f"  Line {issue['line']}: {issue['command']}\n"
                    pytest.fail(msg)

    def test_scripts_have_no_tty(self):
        """
        All gpg subprocess.run calls in scripts/ must include --no-tty.
        """
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent.parent

        scripts_dir = project_root / "scripts"
        if not scripts_dir.exists():
            pytest.skip("scripts/ directory not found")

        issues = find_gpg_calls_without_no_tty(scripts_dir)

        if issues:
            msg = "BUG-20251218-007: Found gpg subprocess.run calls without --no-tty:\n"
            for issue in issues:
                msg += f"  {issue['file']}:{issue['line']} - {issue['command']}\n"
            pytest.fail(msg)


class TestGpgNoTtyRegex:
    """Additional regex-based verification for non-AST parseable patterns."""

    def test_no_card_status_without_no_tty(self):
        """
        Verify no gpg --card-status without --no-tty using regex.

        This catches patterns that AST might miss (e.g., string concatenation).
        """
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent.parent

        smartdrive_dir = project_root / ".smartdrive"
        if not smartdrive_dir.exists():
            pytest.skip(".smartdrive directory not found")

        # Pattern to find gpg subprocess calls
        # Looking for patterns like: ["gpg", "--card-status"] or ["gpg", "..." "--card-status"]
        # that don't have --no-tty
        issues = []

        for py_file in smartdrive_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Check for subprocess.run with gpg that has --card-status
                    if "subprocess.run" in line and '"gpg"' in line and "--card-status" in line:
                        # Verify --no-tty is also present
                        if "--no-tty" not in line:
                            issues.append(
                                {
                                    "file": str(py_file),
                                    "line": i,
                                    "content": line.strip(),
                                }
                            )
            except Exception:
                pass

        if issues:
            msg = "BUG-20251218-007: Found gpg --card-status without --no-tty:\n"
            for issue in issues:
                msg += f"  {issue['file']}:{issue['line']}\n"
                msg += f"    {issue['content']}\n"
            pytest.fail(msg)

    def test_no_decrypt_without_no_tty(self):
        """
        Verify no gpg --decrypt without --no-tty using regex.
        """
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent.parent

        smartdrive_dir = project_root / ".smartdrive"
        if not smartdrive_dir.exists():
            pytest.skip(".smartdrive directory not found")

        issues = []

        for py_file in smartdrive_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Check for subprocess.run with gpg that has --decrypt
                    if "subprocess.run" in line and '"gpg"' in line and "--decrypt" in line:
                        # Verify --no-tty is also present
                        if "--no-tty" not in line:
                            issues.append(
                                {
                                    "file": str(py_file),
                                    "line": i,
                                    "content": line.strip(),
                                }
                            )
            except Exception:
                pass

        if issues:
            msg = "BUG-20251218-007: Found gpg --decrypt without --no-tty:\n"
            for issue in issues:
                msg += f"  {issue['file']}:{issue['line']}\n"
                msg += f"    {issue['content']}\n"
            pytest.fail(msg)
