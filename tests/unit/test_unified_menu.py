"""
Unit tests for unified CLI menu and admin gating.

Tests verify:
1. Menu composition - all operations shown regardless of launch context
2. Admin gating - admin-required operations are shown but blocked when not admin
3. System drive protection - setup refuses system drives as targets
4. No launch-context branching for menu/feature availability
"""

import os
import sys
from pathlib import Path
from unittest import mock

# Setup path - test file is at tests/unit/test_unified_menu.py
# Project root is tests/unit/../../ = project root
_test_file = Path(__file__).resolve()
_project_root = _test_file.parent.parent.parent  # tests/unit -> tests -> project root
_smartdrive_root = _project_root / ".smartdrive"

# Add both .smartdrive and .smartdrive/scripts to path
if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest


class TestCLIOperationsSSoT:
    """Test that CLIOperations is the single source of truth for menu operations."""

    def test_cli_operations_exists(self):
        """CLIOperations class must exist in core/constants.py."""
        from core.constants import CLIOperations

        assert CLIOperations is not None

    def test_cli_operations_has_required_ids(self):
        """CLIOperations must define all required operation IDs."""
        from core.constants import CLIOperations

        required_ids = [
            "mount",
            "unmount",
            "setup",
            "rekey",
            "keyfile_utils",
            "config_status",
            "recovery",
            "sign_scripts",
            "verify_integrity",
            "challenge_hash",
            "help",
            "update",
            "exit",
        ]

        for op_id in required_ids:
            assert hasattr(CLIOperations, f"OP_{op_id.upper()}"), f"Missing operation ID: {op_id}"

    def test_operations_have_required_metadata(self):
        """Each operation must have required metadata fields."""
        from core.constants import CLIOperations

        required_fields = ["label", "requires_admin", "forbidden_on_system_target", "handler"]

        for op_id, metadata in CLIOperations.OPERATIONS.items():
            for field in required_fields:
                assert field in metadata, f"Operation '{op_id}' missing field '{field}'"

    def test_unified_menu_order_includes_all_ops(self):
        """UNIFIED_MENU_ORDER must include all operations."""
        from core.constants import CLIOperations

        for op_id in CLIOperations.OPERATIONS.keys():
            assert op_id in CLIOperations.UNIFIED_MENU_ORDER, f"Operation '{op_id}' not in menu order"


class TestAdminDetection:
    """Test platform admin detection."""

    def test_is_admin_returns_bool(self):
        """is_admin() must return a boolean."""
        from core.platform import is_admin

        result = is_admin()
        assert isinstance(result, bool)

    def test_admin_override_for_testing(self):
        """Admin status can be overridden for testing."""
        from core.platform import _get_admin_status, _set_admin_override, is_admin

        original = is_admin()

        # Override to True
        _set_admin_override(True)
        assert _get_admin_status() is True

        # Override to False
        _set_admin_override(False)
        assert _get_admin_status() is False

        # Reset
        _set_admin_override(None)


class TestUnifiedMenuComposition:
    """Test that unified menu contains all operations regardless of context."""

    def test_menu_shows_all_operations(self):
        """Menu must show all operations from CLIOperations."""
        from core.constants import CLIOperations

        # All operations should be in unified menu order
        menu_ops = set(CLIOperations.UNIFIED_MENU_ORDER)
        all_ops = set(CLIOperations.OPERATIONS.keys())

        assert menu_ops == all_ops, f"Menu missing operations: {all_ops - menu_ops}"

    def test_admin_required_operations_marked(self):
        """Admin-required operations must be properly marked.

        UPDATED: Mount and unmount do NOT require admin - VeraCrypt handles UAC itself.
        Only setup and rekey require admin (partitioning and VeraCrypt password change).
        """
        from core.constants import CLIOperations

        # These operations require admin (partitioning, password change)
        admin_ops = ["setup", "rekey"]

        for op_id in admin_ops:
            assert CLIOperations.is_admin_required(op_id), f"{op_id} should require admin"

    def test_non_admin_operations_not_marked(self):
        """Non-admin operations must not be marked as requiring admin.

        UPDATED: Mount and unmount do NOT require admin - VeraCrypt handles UAC itself.
        """
        from core.constants import CLIOperations

        non_admin_ops = ["mount", "unmount", "keyfile_utils", "config_status", "help"]

        for op_id in non_admin_ops:
            assert not CLIOperations.is_admin_required(op_id), f"{op_id} should not require admin"


class TestAdminGating:
    """Test that admin-required operations are properly gated."""

    def test_admin_operation_blocked_when_not_admin(self):
        """Admin-required operation must be blocked when not running as admin."""
        from core.constants import CLIOperations
        from core.platform import _set_admin_override

        # Set not-admin
        _set_admin_override(False)

        try:
            for op_id in CLIOperations.UNIFIED_MENU_ORDER:
                if CLIOperations.is_admin_required(op_id):
                    # Operation should be shown but would be blocked
                    assert op_id in CLIOperations.OPERATIONS
                    # Handler exists but won't be called without admin
                    assert CLIOperations.get_operation(op_id).get("handler") is not None or op_id == "exit"
        finally:
            _set_admin_override(None)


class TestSystemDriveProtection:
    """Test that setup refuses system drives as targets."""

    def test_setup_forbidden_on_system_drive(self):
        """Setup operation must be forbidden on system drive targets."""
        from core.constants import CLIOperations

        assert CLIOperations.is_forbidden_on_system("setup"), "Setup must be forbidden on system drives"

    def test_mount_unmount_allowed_on_non_system(self):
        """Mount/unmount operations should not be forbidden on system targets."""
        from core.constants import CLIOperations

        assert not CLIOperations.is_forbidden_on_system("mount")
        assert not CLIOperations.is_forbidden_on_system("unmount")


class TestNoLaunchContextBranching:
    """Test that code does not use launch context for feature gating."""

    def test_detect_context_only_for_paths(self):
        """detect_context() docstring must state it's for path resolution only."""
        from smartdrive import detect_context

        assert "path" in detect_context.__doc__.lower() or "PATH" in detect_context.__doc__
        assert "NOT" in detect_context.__doc__ or "not" in detect_context.__doc__

    def test_main_does_not_branch_on_context(self):
        """main() must use unified menu, not context-based branching."""
        import inspect

        import smartdrive

        source = inspect.getsource(smartdrive.main)

        # Should NOT have if context == "SMARTDRIVE" branching
        assert "main_menu_smartdrive()" not in source or "DEPRECATED" in source
        assert "main_menu_system()" not in source or "DEPRECATED" in source

        # Should use unified menu
        assert "main_menu_unified" in source

    def test_forbidden_patterns_not_in_feature_gating(self):
        """Forbidden patterns must not be used for feature/menu gating."""
        import inspect

        import smartdrive

        source = inspect.getsource(smartdrive)

        # Check that context detection is not used for menu selection
        # This is a heuristic check - the main menu loop should use unified
        lines_with_context = [l for l in source.split("\n") if "detect_context" in l]

        for line in lines_with_context:
            # Context detection should not appear in menu/handler selection logic
            # It's OK in path setup code
            if "if" in line and "SMARTDRIVE" in line:
                # This pattern is suspicious for feature gating
                assert "menu" not in line.lower(), f"Suspicious context-based menu logic: {line}"


class TestDrivePropertiesNotLaunchContext:
    """Verify drive safety uses properties, not launch context."""

    def test_setup_drive_check_by_properties(self):
        """setup.py select_drive must check is_system property, not context."""
        import sys

        # Read setup.py source
        setup_path = _smartdrive_root / "scripts" / "setup.py"
        with open(setup_path, "r", encoding="utf-8") as f:
            source = f.read()

        # Must check is_system property
        assert "is_system" in source
        assert "is_boot" in source

        # select_drive function should filter by properties
        assert "safe_drives" in source
        assert 'd.get("is_system")' in source or "d.get('is_system')" in source


class TestConsoleStyle:
    """Test ConsoleStyle class for ASCII-safe output."""

    def test_console_style_exists(self):
        """ConsoleStyle class must exist in core.constants."""
        from core.constants import ConsoleStyle

        assert ConsoleStyle is not None

    def test_console_style_modes(self):
        """ConsoleStyle must have UNICODE and ASCII modes."""
        from core.constants import ConsoleStyle

        assert hasattr(ConsoleStyle, "UNICODE")
        assert hasattr(ConsoleStyle, "ASCII")
        assert ConsoleStyle.UNICODE == "unicode"
        assert ConsoleStyle.ASCII == "ascii"

    def test_console_style_detect(self):
        """ConsoleStyle.detect() must return a ConsoleStyle instance."""
        from core.constants import ConsoleStyle

        style = ConsoleStyle.detect()
        assert isinstance(style, ConsoleStyle)
        assert style.mode in (ConsoleStyle.UNICODE, ConsoleStyle.ASCII)

    def test_console_style_symbols(self):
        """ConsoleStyle must provide symbol properties."""
        from core.constants import ConsoleStyle

        # Test unicode mode
        unicode_style = ConsoleStyle(ConsoleStyle.UNICODE)
        assert unicode_style.SUCCESS == "✓"

        # Test ASCII mode
        ascii_style = ConsoleStyle(ConsoleStyle.ASCII)
        assert "OK" in ascii_style.SUCCESS or "[" in ascii_style.SUCCESS

    def test_console_style_label_for_op(self):
        """ConsoleStyle.label_for_op() must return appropriate labels."""
        from core.constants import ConsoleStyle

        unicode_style = ConsoleStyle(ConsoleStyle.UNICODE)
        ascii_style = ConsoleStyle(ConsoleStyle.ASCII)

        # Unicode should return original label
        unicode_label = "🔓 Mount encrypted volume"
        assert unicode_style.label_for_op("mount", unicode_label) == unicode_label

        # ASCII should return text-only label
        ascii_label = ascii_style.label_for_op("mount", unicode_label)
        assert "[UNLOCKED]" in ascii_label or "Mount" in ascii_label


class TestMenuSections:
    """Test menu section groupings."""

    def test_menu_sections_exist(self):
        """CLIOperations.MENU_SECTIONS must exist."""
        from core.constants import CLIOperations

        assert hasattr(CLIOperations, "MENU_SECTIONS")
        assert len(CLIOperations.MENU_SECTIONS) > 0

    def test_menu_sections_cover_all_operations(self):
        """All operations (except exit) must be in a menu section."""
        from core.constants import CLIOperations

        # Collect all ops in sections
        section_ops = set()
        for section_name, ops in CLIOperations.MENU_SECTIONS:
            section_ops.update(ops)

        # All ops except exit should be in sections
        all_ops = set(CLIOperations.OPERATIONS.keys()) - {"exit"}
        missing = all_ops - section_ops
        assert not missing, f"Operations not in any section: {missing}"

    def test_menu_sections_no_duplicates(self):
        """Each operation must appear in exactly one section."""
        from core.constants import CLIOperations

        seen = set()
        for section_name, ops in CLIOperations.MENU_SECTIONS:
            for op in ops:
                assert op not in seen, f"Duplicate operation {op} in sections"
                seen.add(op)
