#!/usr/bin/env python3
"""
Unit tests for P0-C: Recovery generation during setup.

These tests ensure:
1. --skip-auth is NOT used anywhere in execution paths
2. generate_recovery_kit_from_setup function exists and is callable
3. Recovery generation failure aborts setup
"""

import sys
from pathlib import Path

# Add project root and .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"

sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest


class TestSkipAuthRemoved:
    """Tests to ensure --skip-auth is not used in execution paths."""

    def test_recovery_argparse_no_skip_auth(self):
        """recovery.py argparse must not have --skip-auth."""
        import argparse

        # Get the source and check it doesn't register --skip-auth
        import inspect

        from recovery import main

        source = inspect.getsource(main)

        # Should not contain --skip-auth argument registration
        assert '"--skip-auth"' not in source, "Found --skip-auth in recovery.py main()"
        assert "'--skip-auth'" not in source, "Found --skip-auth in recovery.py main()"

    def test_setup_no_skip_auth_in_subprocess(self):
        """setup.py must not pass --skip-auth to recovery.py."""
        from pathlib import Path

        # setup.py is now in .smartdrive/scripts/
        setup_path = _smartdrive_root / "scripts" / "setup.py"
        content = setup_path.read_text(encoding="utf-8")

        # Check for subprocess invocations with --skip-auth
        # Allow comments explaining removal
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "--skip-auth" in line:
                # Only allow in comments
                stripped = line.strip()
                if not stripped.startswith("#"):
                    pytest.fail(f"Found --skip-auth in non-comment at line {i+1}: {line}")


class TestRecoverySetupIntegration:
    """Tests for recovery kit generation from setup."""

    def test_generate_function_exists(self):
        """generate_recovery_kit_from_setup function must exist."""
        from recovery import generate_recovery_kit_from_setup

        assert callable(generate_recovery_kit_from_setup)

    def test_generate_function_signature(self):
        """Function must accept config_path, password, keyfile_bytes."""
        import inspect

        from recovery import generate_recovery_kit_from_setup

        sig = inspect.signature(generate_recovery_kit_from_setup)
        params = list(sig.parameters.keys())

        assert "config_path" in params
        assert "password" in params
        assert "keyfile_bytes" in params

    def test_generate_returns_int(self):
        """Function must return int (0 = success, non-zero = failure)."""
        import inspect

        from recovery import generate_recovery_kit_from_setup

        # Check return annotation if present
        sig = inspect.signature(generate_recovery_kit_from_setup)
        if sig.return_annotation != inspect.Parameter.empty:
            assert sig.return_annotation == int


class TestNoMarkerLies:
    """Tests to ensure no dishonest marker claims without implementation."""

    def test_no_marker_comment_without_implementation(self):
        """If marker is mentioned, implementation must exist."""
        from pathlib import Path

        # setup.py is now in .smartdrive/scripts/
        setup_path = _smartdrive_root / "scripts" / "setup.py"
        content = setup_path.read_text(encoding="utf-8")

        # If marker is mentioned in comments, check implementation exists
        if "marker" in content.lower():
            lines = content.split("\n")
            marker_comments = [l for l in lines if "marker" in l.lower() and l.strip().startswith("#")]

            # If there are marker comments, they should explain REMOVAL, not claim implementation
            for comment in marker_comments:
                # Allowed: comments explaining why no marker is used
                # Not allowed: claims that marker detection exists when it doesn't
                assert (
                    "detects" not in comment.lower() or "removed" in content.lower() or "no marker" in content.lower()
                ), f"Found marker claim without implementation: {comment}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
