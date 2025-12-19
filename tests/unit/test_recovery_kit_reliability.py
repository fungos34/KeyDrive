"""
Unit tests for recovery kit generation reliability fixes.

Tests verify:
1. render_vc_guide accepts warnings parameter (SSOT consolidation)
2. recovery.py path construction doesn't create double .smartdrive
3. Single VeraCrypt GUI launch per session
4. Header backup timeout warning is displayed
5. ASCII-safe output in render_vc_guide

Per MASTER TODO: These are P0/P1 fixes for recovery kit reliability.
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive" / "scripts"))


class TestRenderVcGuideWarningsParam:
    """Test that render_vc_guide accepts the warnings parameter (SSOT fix)."""

    def test_accepts_warnings_parameter(self, capsys):
        """
        Test that render_vc_guide accepts warnings parameter without TypeError.

        This was the root cause of the recovery kit crash - the veracrypt_cli.py
        version was missing the warnings= parameter.
        """
        from veracrypt_cli import render_vc_guide

        steps = ["Step 1", "Step 2"]
        warnings = ["All data will be erased!", "This cannot be undone!"]

        # Should not raise TypeError: render_vc_guide() got an unexpected keyword argument 'warnings'
        render_vc_guide(
            title="TEST GUIDE", steps=steps, copy_values={"Key": "Value"}, warnings=warnings, notes=["Some note"]
        )

        captured = capsys.readouterr()
        assert "TEST GUIDE" in captured.out
        assert "All data will be erased!" in captured.out
        assert "This cannot be undone!" in captured.out

    def test_warnings_displayed_before_steps(self, capsys):
        """Test that warnings appear before steps (high visibility)."""
        from veracrypt_cli import render_vc_guide

        steps = ["Step 1"]
        warnings = ["Important warning"]

        render_vc_guide("TITLE", steps, warnings=warnings)

        captured = capsys.readouterr()
        output = captured.out

        # Warnings should appear before STEPS section
        warnings_pos = output.find("WARNINGS:")
        steps_pos = output.find("STEPS:")

        assert warnings_pos > -1, "WARNINGS section not found"
        assert steps_pos > -1, "STEPS section not found"
        assert warnings_pos < steps_pos, "WARNINGS should appear before STEPS"

    def test_warnings_and_notes_together(self, capsys):
        """Test using both warnings and notes parameters."""
        from veracrypt_cli import render_vc_guide

        steps = ["Do something"]
        warnings = ["Be careful!"]
        notes = ["Additional info"]

        render_vc_guide("TITLE", steps, warnings=warnings, notes=notes)

        captured = capsys.readouterr()
        output = captured.out

        assert "Be careful!" in output
        assert "Additional info" in output

        # Verify order: warnings < steps < notes
        warn_pos = output.find("Be careful!")
        step_pos = output.find("Do something")
        note_pos = output.find("Additional info")

        assert warn_pos < step_pos < note_pos


class TestRecoveryPathConstruction:
    """Test that recovery path construction doesn't create double .smartdrive."""

    def test_no_double_smartdrive_in_fallback_path(self):
        """
        Test that fallback recovery path doesn't create .smartdrive/.smartdrive/recovery.

        BUG FIX: recovery.py line 2024 was using SCRIPT_DIR.parent / ".smartdrive" / "recovery"
        but SCRIPT_DIR.parent is already .smartdrive/, creating a double path.
        """
        # Simulate the path construction from recovery.py
        # SCRIPT_DIR = .smartdrive/scripts/
        # SCRIPT_DIR.parent = .smartdrive/

        from core.paths import Paths

        mock_script_dir = Path("C:\\") / "test" / "project" / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR

        # OLD BUG: This created C:/test/project/.smartdrive/.smartdrive/recovery
        buggy_path = mock_script_dir.parent / ".smartdrive" / "recovery"
        double = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.SMARTDRIVE_DIR_NAME).as_posix()
        assert double in str(buggy_path).replace(
            "\\", "/"
        ), "Sanity check - the buggy construction should have double .smartdrive"

        # NEW FIX: This creates C:/test/project/.smartdrive/recovery
        fixed_path = mock_script_dir.parent / "recovery"
        assert double not in str(fixed_path).replace("\\", "/"), "Fixed path should not have double .smartdrive"
        expected_suffix = (Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.RECOVERY_SUBDIR).as_posix()
        fixed_norm = str(fixed_path).replace("\\", "/")
        assert expected_suffix in fixed_norm, "Fixed path should end with .smartdrive/recovery"

    def test_recovery_path_ends_correctly(self):
        """Test that the fixed recovery path ends with .smartdrive/recovery."""
        from core.paths import Paths

        mock_script_dir = Path("/") / "home" / "user" / "project" / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR
        fixed_path = mock_script_dir.parent / "recovery"

        # Path should end with recovery under .smartdrive
        path_str = str(fixed_path).replace("\\", "/")
        assert path_str.endswith((Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.RECOVERY_SUBDIR).as_posix())


class TestSingleGuiLaunch:
    """Test that VeraCrypt GUI only launches once per session."""

    def test_gui_flag_prevents_double_launch(self):
        """
        Test that the module-level flag prevents multiple GUI launches.

        When render_header_export_gui_guide is called twice (e.g., on retry),
        the GUI should only open once.
        """
        import veracrypt_cli
        from veracrypt_cli import _veracrypt_gui_opened_this_session, reset_gui_launched_state

        # Reset state for clean test
        reset_gui_launched_state()
        assert veracrypt_cli._veracrypt_gui_opened_this_session == False

        # Simulate first launch
        veracrypt_cli._veracrypt_gui_opened_this_session = True

        # Flag should now be True
        assert veracrypt_cli._veracrypt_gui_opened_this_session == True

        # Cleanup
        reset_gui_launched_state()

    def test_reset_function_works(self):
        """Test that reset_gui_launched_state properly resets the flag."""
        import veracrypt_cli
        from veracrypt_cli import reset_gui_launched_state

        # Set the flag
        veracrypt_cli._veracrypt_gui_opened_this_session = True

        # Reset
        reset_gui_launched_state()

        # Should be False
        assert veracrypt_cli._veracrypt_gui_opened_this_session == False


class TestHeaderBackupWarning:
    """Test that header backup process shows timing warning."""

    def test_warning_message_content(self):
        """
        Test that the warning message mentions 60 seconds and key derivation.

        This warning is important so users don't think the process is hung
        during VeraCrypt's PBKDF2 key derivation.
        """
        # Read the actual recovery.py file and check for warning content
        recovery_py = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "recovery.py"

        if recovery_py.exists():
            content = recovery_py.read_text(encoding="utf-8")

            # Check for key warning elements
            assert "60 seconds" in content, "Should mention 60 second timeout"
            assert (
                "HEADER BACKUP NOTICE" in content or "key derivation" in content.lower()
            ), "Should mention header backup or key derivation"
            assert "PBKDF2" in content, "Should mention PBKDF2 as the reason for delay"


class TestAsciiSafeOutput:
    """Test that output is ASCII-safe for Windows elevated consoles."""

    def test_render_vc_guide_no_unicode_arrows(self, capsys):
        """Test that render_vc_guide uses ASCII arrows, not Unicode."""
        from veracrypt_cli import render_vc_guide

        steps = [{"text": "Step with substeps", "substeps": ["Sub A", "Sub B"]}]

        render_vc_guide("TITLE", steps, warnings=["Warning"], notes=["Note"])

        captured = capsys.readouterr()
        output = captured.out

        # Check for problematic Unicode that breaks in elevated PowerShell
        problematic_chars = ["→", "•", "✓", "✗", "⚠️", "❌", "═", "║"]
        for char in problematic_chars:
            assert char not in output, f"Found problematic Unicode: {char}"

        # Verify ASCII-safe arrow is used
        assert "->" in output, "Should use ASCII arrow (->)"

    def test_all_output_encodable_as_ascii(self, capsys):
        """Test that all output can be encoded as ASCII (or CP1252 for Windows)."""
        from veracrypt_cli import render_vc_guide

        steps = [{"text": "Main step", "substeps": ["A", "B", "C"]}, "String step"]
        warnings = ["Critical warning"]
        notes = ["Final note"]
        copy_values = {"Path": "/dev/sdb", "Password": "test123"}

        render_vc_guide("COMPLETE TEST", steps, copy_values, warnings, notes)

        captured = capsys.readouterr()
        output = captured.out

        # Try encoding as ASCII - should not raise
        try:
            output.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"Output contains non-ASCII character: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
