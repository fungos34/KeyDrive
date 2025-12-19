"""
Test path display correctness.

Ensures no double .smartdrive paths appear in user-facing output.
"""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.paths import Paths

# Add paths for imports
_test_dir = Path(__file__).parent
_tests_root = _test_dir.parent
_repo_root = _tests_root.parent
_smartdrive_dir = _repo_root / ".smartdrive"

sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_smartdrive_dir))
sys.path.insert(0, str(_smartdrive_dir / "scripts"))


class TestPathDisplayCorrectness:
    """Ensure displayed paths don't contain double .smartdrive."""

    def test_recovery_dir_name_is_just_folder_name(self):
        """RECOVERY_DIR_NAME should be 'recovery', not '.smartdrive/recovery'."""
        # Import specific module components without triggering main()
        import importlib.util

        spec = importlib.util.spec_from_file_location("recovery_module", _smartdrive_dir / "scripts" / "recovery.py")

        # Read the file and extract RECOVERY_DIR_NAME
        recovery_py = _smartdrive_dir / "scripts" / "recovery.py"
        content = recovery_py.read_text(encoding="utf-8")

        # Check that RECOVERY_DIR_NAME is defined correctly
        # Look for: RECOVERY_DIR_NAME = "recovery"
        import re

        match = re.search(r'RECOVERY_DIR_NAME\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            value = match.group(1)
            assert value == "recovery", f"RECOVERY_DIR_NAME should be 'recovery', got '{value}'"

        # Also check that fallback doesn't have .smartdrive
        forbidden = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.RECOVERY_SUBDIR).as_posix()
        assert (
            f'RECOVERY_DIR_NAME = "{forbidden}"' not in content
        ), "Fallback RECOVERY_DIR_NAME should not contain .smartdrive"

    def test_get_recovery_dir_produces_correct_path(self):
        """get_recovery_dir should produce V:/.smartdrive/recovery, not V:/.smartdrive/.smartdrive/recovery."""
        # Import the function directly
        recovery_py = _smartdrive_dir / "scripts" / "recovery.py"

        # We need to test the logic, read and parse
        content = recovery_py.read_text(encoding="utf-8")

        # Find the get_recovery_dir function - use simpler pattern
        import re

        # Look for the function definition
        assert "def get_recovery_dir" in content, "get_recovery_dir function not found"

        # Extract everything from function def to next function
        start_idx = content.find("def get_recovery_dir")
        next_def = content.find("\ndef ", start_idx + 1)
        if next_def == -1:
            func_body = content[start_idx:]
        else:
            func_body = content[start_idx:next_def]

        # Should use Paths.recovery_dir OR manual ".smartdrive" / RECOVERY_DIR_NAME
        # Should NOT just be: Path(volume_mount) / RECOVERY_DIR_NAME (without .smartdrive)
        assert (
            "Paths.recovery_dir" in func_body or '".smartdrive"' in func_body or "'.smartdrive'" in func_body
        ), f"get_recovery_dir should include .smartdrive prefix in path construction:\n{func_body[:500]}"

    def test_no_double_smartdrive_in_paths_module(self):
        """Paths module constants should not produce double .smartdrive."""
        from core.paths import Paths

        # RECOVERY_SUBDIR should be just 'recovery'
        assert Paths.RECOVERY_SUBDIR == "recovery"

        # Test recovery_dir builder
        test_root = Path("V:\\")
        recovery_path = Paths.recovery_dir(test_root)
        path_str = str(recovery_path)

        count = path_str.count(".smartdrive")
        assert count == 1, f"Paths.recovery_dir should contain '.smartdrive' exactly once, got {count}: {path_str}"

    def test_smartdrive_dir_computation_in_source(self):
        """_SMARTDRIVE_DIR logic should not create double .smartdrive paths."""
        recovery_py = _smartdrive_dir / "scripts" / "recovery.py"
        content = recovery_py.read_text(encoding="utf-8")

        # Check for proper _SMARTDRIVE_DIR computation
        # Should be: SCRIPT_DIR.parent if SCRIPT_DIR.parent.name == ".smartdrive"
        # Not: SCRIPT_DIR.parent / ".smartdrive" always

        # Bad pattern: always appending .smartdrive without checking
        bad_pattern = r'_SMARTDRIVE_DIR\s*=\s*SCRIPT_DIR\.parent\s*/\s*["\']\.smartdrive["\']'
        import re

        # This would be wrong - should be conditional
        assert not re.search(bad_pattern, content) or (
            'SCRIPT_DIR.parent.name == ".smartdrive"' in content
        ), "Should conditionally append .smartdrive only when needed"


class TestNoDoublePathsInOutput:
    """Test that printed output doesn't contain double .smartdrive paths."""

    def test_path_string_detection_pattern(self):
        """Verify our detection pattern works."""
        double_unix = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.SMARTDRIVE_DIR_NAME).as_posix()
        double_win = double_unix.replace("/", "\\")

        # These should be detected as problematic
        bad_paths = [
            str(Path("V:\\") / Paths.SMARTDRIVE_DIR_NAME / Paths.SMARTDRIVE_DIR_NAME / Paths.RECOVERY_SUBDIR),
            (Path("V:\\") / Paths.SMARTDRIVE_DIR_NAME / Paths.SMARTDRIVE_DIR_NAME / Paths.RECOVERY_SUBDIR).as_posix(),
            (
                Path("/") / "mnt" / "volume" / Paths.SMARTDRIVE_DIR_NAME / Paths.SMARTDRIVE_DIR_NAME / Paths.KEYS_SUBDIR
            ).as_posix(),
        ]
        for p in bad_paths:
            assert double_win in p or double_unix in p, f"Test pattern should match: {p}"

        # These should be OK (single .smartdrive)
        good_paths = [
            str(Path("V:\\") / Paths.SMARTDRIVE_DIR_NAME / Paths.RECOVERY_SUBDIR),
            (Path("V:\\") / Paths.SMARTDRIVE_DIR_NAME / Paths.RECOVERY_SUBDIR).as_posix(),
            (Path("/") / "mnt" / "volume" / Paths.SMARTDRIVE_DIR_NAME / Paths.KEYS_SUBDIR).as_posix(),
        ]
        for p in good_paths:
            assert double_win not in p, f"Should be OK: {p}"
            assert double_unix not in p, f"Should be OK: {p}"

    def test_no_double_smartdrive_in_recovery_source(self):
        """Scan recovery.py for double .smartdrive patterns in string literals."""
        recovery_py = _smartdrive_dir / "scripts" / "recovery.py"
        content = recovery_py.read_text(encoding="utf-8")

        # Check for double .smartdrive in string literals
        double_unix = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.SMARTDRIVE_DIR_NAME).as_posix()
        double_win = double_unix.replace("/", "\\")
        assert double_unix not in content, "Found double .smartdrive in recovery.py"
        assert double_win not in content, "Found double .smartdrive in recovery.py"
        # Also check for Path concat that could produce double
        forbidden = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.RECOVERY_SUBDIR).as_posix()
        assert (
            f'"{forbidden}"' not in content or "Fallback" in content
        ), "RECOVERY_DIR_NAME should be a plain folder name (no smartdrive prefix)"


def assert_no_double_smartdrive(text: str, context: str = ""):
    """
    Assert that text doesn't contain double .smartdrive paths.

    This is a helper for other tests to use when validating output.
    """
    # Check both Windows and Unix path separators
    double_unix = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.SMARTDRIVE_DIR_NAME).as_posix()
    double_win = double_unix.replace("/", "\\")

    if double_win in text or double_unix in text:
        # Find the line containing the issue for better error message
        for i, line in enumerate(text.splitlines(), 1):
            if double_win in line or double_unix in line:
                pytest.fail(f"Double .smartdrive path found in {context or 'output'} at line {i}:\n{line}")
        pytest.fail(f"Double .smartdrive path found in {context or 'output'}:\n{text[:500]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
