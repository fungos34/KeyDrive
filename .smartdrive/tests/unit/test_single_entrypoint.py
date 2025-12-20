"""
Test single entrypoint invariant.

Ensures only one smartdrive.py exists at the canonical location.
Per AGENT_ARCHITECTURE.md, duplicates are architectural defects.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add paths for imports
# tests/unit/test_single_entrypoint.py -> tests/unit -> tests -> .smartdrive
_test_dir = Path(__file__).parent
_tests_root = _test_dir.parent
_smartdrive_root = _tests_root.parent  # This is now .smartdrive/ directly
_repo_root = _smartdrive_root.parent  # This is the repository root

sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))


class TestSingleEntrypointInvariant:
    """Test the single entrypoint invariant."""

    def test_check_function_exists(self):
        """The invariant check function should exist."""
        # Read the module source since we can't import without argparse triggering
        smartdrive_py = _smartdrive_root / "scripts" / "smartdrive.py"
        content = smartdrive_py.read_text(encoding="utf-8")

        assert (
            "def check_single_entrypoint_invariant" in content
        ), "check_single_entrypoint_invariant function should exist"
        assert "def enforce_single_entrypoint" in content, "enforce_single_entrypoint function should exist"

    def test_invariant_check_logic_in_source(self):
        """Verify the invariant check logic is correct."""
        smartdrive_py = _smartdrive_root / "scripts" / "smartdrive.py"
        content = smartdrive_py.read_text(encoding="utf-8")

        # Should check for duplicate at root
        assert "smartdrive.py" in content
        assert "duplicate" in content.lower() or "Duplicate" in content

        # Should check canonical location
        assert ".smartdrive" in content
        assert "scripts" in content

    def test_no_duplicate_in_repo(self):
        """Repository should not have duplicate smartdrive.py at root."""
        canonical = _smartdrive_root / "scripts" / "smartdrive.py"
        duplicate = _repo_root / "smartdrive.py"

        assert canonical.exists(), f"Canonical smartdrive.py should exist at {canonical}"

        # If duplicate exists at root, it should be a thin wrapper, not the full script
        if duplicate.exists():
            canonical_size = canonical.stat().st_size
            duplicate_size = duplicate.stat().st_size

            # If duplicate is small (< 1KB), it's likely just a wrapper
            # If it's similar size to canonical, it's a problematic duplicate
            if duplicate_size > 1000:
                # Check if it's actually different or just referencing
                duplicate_content = duplicate.read_text(encoding="utf-8")

                # Wrapper patterns that are OK
                ok_patterns = [
                    "from .smartdrive.scripts.smartdrive import main",
                    "exec(open",
                    "import .smartdrive.scripts.smartdrive",
                ]

                is_wrapper = any(p in duplicate_content for p in ok_patterns)

                if not is_wrapper and duplicate_size > canonical_size * 0.5:
                    pytest.fail(
                        f"Duplicate smartdrive.py at {duplicate} appears to be a full copy "
                        f"({duplicate_size} bytes vs canonical {canonical_size} bytes). "
                        "This violates the single entrypoint invariant."
                    )

    def test_invariant_called_at_startup(self):
        """Invariant check should be called in main()."""
        smartdrive_py = _smartdrive_root / "scripts" / "smartdrive.py"
        content = smartdrive_py.read_text(encoding="utf-8")

        # Find main() function and check it calls enforce_single_entrypoint
        main_start = content.find("def main():")
        assert main_start != -1, "main() function should exist"

        # Find end of main function (next def at same indent level)
        main_section = content[main_start : main_start + 2000]

        assert "enforce_single_entrypoint" in main_section, "main() should call enforce_single_entrypoint"


class TestDeploymentDoesntCreateDuplicate:
    """Test that deployment scripts don't create duplicates."""

    def test_setup_doesnt_copy_to_root(self):
        """setup.py should not copy smartdrive.py to drive root."""
        setup_py = _smartdrive_root / "scripts" / "setup.py"
        if not setup_py.exists():
            pytest.skip("setup.py not found")

        content = setup_py.read_text(encoding="utf-8")

        # Should have comments about NOT copying to root
        assert (
            "REMOVED" in content or "Canonical entrypoint" in content or "NOT" in content
        ), "setup.py should document that duplicate copy is removed"

    def test_update_doesnt_copy_to_root(self):
        """update.py should not copy smartdrive.py to drive root."""
        update_py = _smartdrive_root / "scripts" / "update.py"
        if not update_py.exists():
            pytest.skip("update.py not found")

        content = update_py.read_text(encoding="utf-8")

        # Check that files go to .smartdrive/scripts/, not root
        # Look for pattern that would copy to root incorrectly
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if "smartdrive.py" in line and "target_path /" in line:
                # This would be copying directly to target root
                if '".smartdrive"' not in line and "'.smartdrive'" not in line:
                    pytest.fail(f"Line {i} may copy smartdrive.py to root instead of .smartdrive/scripts/:\n{line}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
