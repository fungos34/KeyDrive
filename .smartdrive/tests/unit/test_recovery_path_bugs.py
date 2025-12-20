"""
Unit tests for recovery path handling bugs.

Tests:
- BUG-20251219-010: Path double-prefix (.smartdrive/.smartdrive)
- BUG-20251219-011: Windows popup error in webbrowser.open
- BUG-20251219-012: Terminal hang (caused by BUG-010's path issue)

These tests verify that:
1. Recovery paths are correctly constructed without double-prefixing
2. webbrowser.open uses .as_uri() instead of f"file://{path}" for Windows
3. Path resolution in recovery module follows SSOT patterns
"""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBUG010PathDoublePrefix:
    """Tests for BUG-20251219-010: Path double-prefix fix."""

    def test_config_path_parent_gives_smartdrive_dir(self):
        """
        config_path.parent should be .smartdrive/, not the launcher root.

        Given config_path = H:/.smartdrive/config.json
        Then config_path.parent = H:/.smartdrive
        And config_path.parent.parent = H: (launcher root)
        """
        # Simulate a config path structure
        config_path = Path("H:") / ".smartdrive" / "config.json"

        # Parent is .smartdrive/ directory
        assert config_path.parent.name == ".smartdrive"

        # Parent.parent is the launcher root (drive letter)
        # Note: On Windows, this would be "H:", on Unix the behavior differs
        launcher_root = config_path.parent.parent
        assert launcher_root != config_path.parent

    def test_paths_recovery_dir_requires_launcher_root(self):
        """
        Paths.recovery_dir() expects launcher_root (drive letter), not .smartdrive/.

        If passed .smartdrive/, it would create .smartdrive/.smartdrive/recovery (WRONG).
        If passed H:, it correctly creates H:/.smartdrive/recovery (CORRECT).
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive" / "core"))
        try:
            from paths import Paths

            # Correct usage: pass launcher root (drive letter)
            launcher_root = Path("H:")
            recovery_dir = Paths.recovery_dir(launcher_root)

            # Should be H:/.smartdrive/recovery, not H:/.smartdrive/.smartdrive/recovery
            assert recovery_dir.parts[-1] == "recovery"
            assert recovery_dir.parts[-2] == ".smartdrive"
            # Should NOT have double .smartdrive
            path_str = str(recovery_dir)
            assert ".smartdrive\\.smartdrive" not in path_str
            assert ".smartdrive/.smartdrive" not in path_str

        finally:
            sys.path.pop(0)

    def test_recovery_module_uses_parent_parent_for_launcher_root(self):
        """
        Verify recovery.py uses config_path.parent.parent to get launcher root.

        This is an AST-based test that verifies the source code pattern.
        """
        recovery_py = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "recovery.py"

        if not recovery_py.exists():
            pytest.skip("recovery.py not found")

        source = recovery_py.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Find assignments like: launcher_mount = config_path.parent.parent
        found_correct_pattern = False
        found_incorrect_pattern = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and "launcher" in target.id.lower():
                        # Check if RHS is config_path.parent.parent
                        if isinstance(node.value, ast.Attribute):
                            if node.value.attr == "parent":
                                # Check for .parent.parent chain
                                if isinstance(node.value.value, ast.Attribute):
                                    if node.value.value.attr == "parent":
                                        found_correct_pattern = True
                                # Check for just .parent (incorrect)
                                elif isinstance(node.value.value, ast.Name):
                                    if "config_path" in node.value.value.id.lower():
                                        # This would be config_path.parent (wrong)
                                        found_incorrect_pattern = True

        # Should have at least one correct pattern
        assert found_correct_pattern, "Expected launcher_mount = config_path.parent.parent pattern"
        # Should NOT have the incorrect single-parent pattern
        assert not found_incorrect_pattern, "Found incorrect config_path.parent pattern for launcher_mount"


class TestBUG011WebBrowserOpen:
    """Tests for BUG-20251219-011: Windows popup error fix."""

    def test_webbrowser_open_uses_as_uri(self):
        """
        Verify webbrowser.open calls use .as_uri() for proper Windows path handling.

        f"file://{path}" breaks on Windows due to backslashes.
        path.as_uri() correctly handles all platforms.
        """
        recovery_py = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "recovery.py"

        if not recovery_py.exists():
            pytest.skip("recovery.py not found")

        source = recovery_py.read_text(encoding="utf-8")

        # Should NOT have f"file://{...}" pattern
        # This pattern breaks on Windows due to backslashes
        import re

        bad_pattern = re.compile(r'webbrowser\.open\s*\(\s*f["\']file://')
        matches = bad_pattern.findall(source)
        assert not matches, f"Found unsafe webbrowser.open pattern: {matches}"

        # Should have .as_uri() pattern instead
        # This correctly handles Windows paths with backslashes
        good_pattern = re.compile(r"webbrowser\.open\s*\([^)]*\.as_uri\s*\(\s*\)")
        matches = good_pattern.findall(source)
        assert len(matches) >= 1, "Expected webbrowser.open(...as_uri()) pattern"

    def test_path_as_uri_escapes_correctly(self):
        """Verify Path.as_uri() produces valid file:// URIs."""
        # Test with Windows-style path
        win_path = Path("C:/Users/test/recovery.html")
        uri = win_path.as_uri()
        assert uri.startswith("file://")
        # Should NOT contain backslashes
        assert "\\" not in uri

        # Test with absolute path containing spaces (platform-specific)
        import platform

        if platform.system() == "Windows":
            space_path = Path("C:/path/with spaces/file.html")
        else:
            space_path = Path("/path/with spaces/file.html")
        uri = space_path.as_uri()
        assert uri.startswith("file://")
        # Spaces should be URL-encoded
        assert " " not in uri


class TestBUG012TerminalHang:
    """Tests for BUG-20251219-012: Terminal hang after header verification.

    The root cause of this bug was BUG-010's path double-prefix issue.
    When the wrong path was used:
    1. Header backup instructions showed the wrong path
    2. User saved to the displayed (wrong) path
    3. Code expected file at different location
    4. Verification loop or subsequent operations failed

    With BUG-010 fixed, the correct paths are used throughout.
    """

    def test_export_header_receives_correct_path(self):
        """
        Verify that export_header receives the correct header_path.

        The header_path should be under recovery_dir, which should be
        <launcher_root>/.smartdrive/recovery/, not double-prefixed.
        """
        # This is a documentation test that verifies the fix
        # The actual path is computed from Paths.recovery_dir(launcher_root)

        sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive" / "core"))
        try:
            from paths import Paths

            launcher_root = Path("H:")
            recovery_dir = Paths.recovery_dir(launcher_root)
            header_path = recovery_dir / "header_backup.hdr"

            # Verify path structure
            path_str = str(header_path)

            # Should have single .smartdrive, not double
            assert path_str.count(".smartdrive") == 1, f"Expected single .smartdrive in path: {path_str}"

            # Should end with correct filename
            assert header_path.name == "header_backup.hdr"

        finally:
            sys.path.pop(0)

    def test_verification_loop_exits_on_success(self):
        """
        Verify that the verification loop properly exits when file exists.

        This is a code structure test - the while True loop in
        render_header_export_gui_guide should have a return statement
        when verification succeeds.
        """
        veracrypt_cli_py = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "veracrypt_cli.py"

        if not veracrypt_cli_py.exists():
            pytest.skip("veracrypt_cli.py not found")

        source = veracrypt_cli_py.read_text(encoding="utf-8")

        # Find the render_header_export_gui_guide function
        # It should have: if output_path.exists(): ... return True
        import re

        # Pattern: if ... exists(): followed by return True in same block
        # This ensures the loop exits properly
        pattern = re.compile(r"if\s+output_path\.exists\s*\(\s*\)\s*:.*?return\s+True", re.DOTALL)
        matches = pattern.findall(source)
        assert len(matches) >= 1, "Expected output_path.exists() check with return True"


class TestPathSSoTCompliance:
    """Tests for SSOT path handling compliance."""

    def test_no_hardcoded_smartdrive_paths_in_recovery(self):
        """
        Verify recovery.py doesn't use hardcoded '.smartdrive' path concatenation.

        All .smartdrive paths should come from Paths class or SSOT constants.
        Exception: The fallback logic `SCRIPT_DIR.parent / ".smartdrive"` is allowed
        for cases where the script location detection needs normalization.
        """
        recovery_py = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "recovery.py"

        if not recovery_py.exists():
            pytest.skip("recovery.py not found")

        source = recovery_py.read_text(encoding="utf-8")

        # Pattern that would indicate double-prefix bug:
        # Path(...) / ".smartdrive" / ".smartdrive" or similar chained usage
        # But NOT: SCRIPT_DIR.parent / ".smartdrive" (this is valid fallback)
        import re

        # Look for actual double-concatenation bug:
        # e.g., something / ".smartdrive" / "recovery" / ".smartdrive"
        # This would be wrong
        double_prefix_pattern = re.compile(r'/ ["\']\.smartdrive["\'] / ["\']recovery["\'] / ["\']\.smartdrive["\']')

        matches = double_prefix_pattern.findall(source)
        assert not matches, f"Found double-prefix patterns: {matches}"

        # Also verify no Path() / ".smartdrive" / ".smartdrive" pattern
        another_bad_pattern = re.compile(r'/ ["\']\.smartdrive["\'] / ["\']\.smartdrive["\']')
        matches = another_bad_pattern.findall(source)
        assert not matches, f"Found double .smartdrive concatenation: {matches}"
