#!/usr/bin/env python3
"""
Unit tests for post-setup "Next steps" menu functionality.

Tests ensure:
1. Menu accepts [R] for Rekey option
2. Phase 8 calls success screen in interactive mode
3. auto_exit bypasses all prompts
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root and .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"

sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest

# Import SSOT constants
from core.modes import SecurityMode


class TestSuccessMenuAcceptsRekey:
    """Test that the success menu accepts R for Rekey."""

    def test_menu_accepts_r(self):
        """Menu should accept R and return it."""
        from setup import show_setup_success_screen

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)

            with patch("builtins.input", return_value="R"):
                choice = show_setup_success_screen(
                    launcher_mount=launcher_mount,
                    target_drive="TestDrive",
                    use_gpg=False,
                    use_keyfile=False,
                    fingerprints=[],
                    recovery_generated=False,
                )

                assert choice == "R", "Menu should return R when user enters R"

    def test_menu_rejects_invalid_choice(self):
        """Menu should reject invalid choices and re-prompt."""
        from setup import show_setup_success_screen

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)

            # First input invalid, second valid
            with patch("builtins.input", side_effect=["X", "Q"]):
                choice = show_setup_success_screen(
                    launcher_mount=launcher_mount,
                    target_drive="TestDrive",
                    use_gpg=False,
                    use_keyfile=False,
                    fingerprints=[],
                    recovery_generated=False,
                )

                assert choice == "Q", "Menu should eventually accept valid choice"

    def test_menu_accepts_all_valid_options(self):
        """Menu should accept M, G, P, R, Q."""
        from setup import show_setup_success_screen

        valid_options = ["M", "G", "P", "R", "Q"]

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)

            for option in valid_options:
                with patch("builtins.input", return_value=option):
                    choice = show_setup_success_screen(
                        launcher_mount=launcher_mount,
                        target_drive="TestDrive",
                        use_gpg=False,
                        use_keyfile=False,
                        fingerprints=[],
                        recovery_generated=False,
                    )

                    assert choice == option, f"Menu should return {option}"


class TestPhase8InteractiveMode:
    """Test Phase 8 interactive menu flow."""

    def test_phase_8_calls_success_screen_and_exits_on_quit(self):
        """Phase 8 interactive should show menu, accept Q, show log prompt, and exit."""
        from setup import PagedSetupState, run_phase_8_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal deployment structure
            launcher_mount = Path(tmpdir)
            smartdrive_dir = launcher_mount / ".smartdrive"
            scripts_dir = smartdrive_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            config_path = smartdrive_dir / "config.json"
            config_path.write_text("{}")

            # Create minimal state
            state = PagedSetupState()
            state.launcher_mount = launcher_mount
            state.payload_device = "TestPayload"
            state.mount_letter = "V"
            state.use_gpg = False
            state.use_keyfile = False
            state.fingerprints = []
            state.password = "test"
            state.security_mode = SecurityMode.PW_ONLY.value

            # Mock show_setup_success_screen to return Q immediately
            with patch("setup.show_setup_success_screen", return_value="Q"):
                # Mock log review prompt (Enter to exit)
                with patch("builtins.input", return_value=""):
                    # Mock show_log_review (not called since user presses Enter)
                    with patch("setup.show_log_review"):
                        result = run_phase_8_summary(state, auto_exit=False)

                        assert result == 0, "Phase 8 should return 0 on successful exit"

    def test_phase_8_interactive_menu_loop_returns_to_menu(self):
        """Phase 8 should return to menu after actions until Q is chosen."""
        from setup import PagedSetupState, run_phase_8_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)
            smartdrive_dir = launcher_mount / ".smartdrive"
            scripts_dir = smartdrive_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            config_path = smartdrive_dir / "config.json"
            config_path.write_text("{}")

            state = PagedSetupState()
            state.launcher_mount = launcher_mount
            state.payload_device = "TestPayload"
            state.mount_letter = "V"
            state.use_gpg = False
            state.use_keyfile = False
            state.fingerprints = []
            state.password = "test"
            state.security_mode = SecurityMode.PW_ONLY.value

            # Mock: user chooses G (GUI), then Q
            menu_choices = ["G", "Q"]
            choice_iter = iter(menu_choices)

            with patch("setup.show_setup_success_screen", side_effect=choice_iter):
                with patch("veracrypt_cli.open_veracrypt_gui", return_value=True):
                    # Mock input for "press enter to continue" and log prompt
                    with patch("builtins.input", return_value=""):
                        result = run_phase_8_summary(state, auto_exit=False)

                        assert result == 0, "Phase 8 should exit cleanly after Q"


class TestPhase8AutoExitBypass:
    """Test that auto_exit bypasses all prompts."""

    def test_auto_exit_true_bypasses_prompts(self):
        """When auto_exit=True, no prompts should be shown."""
        from setup import PagedSetupState, run_phase_8_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)

            state = PagedSetupState()
            state.launcher_mount = launcher_mount
            state.payload_device = "TestPayload"
            state.mount_letter = "V"

            # Patch input to raise if called (should never be called)
            with patch("builtins.input") as mock_input:
                mock_input.side_effect = AssertionError("input() should not be called in auto_exit mode")

                result = run_phase_8_summary(state, auto_exit=True)

                assert result == 0, "auto_exit should return 0"
                mock_input.assert_not_called()

    def test_auto_exit_false_requires_prompts(self):
        """When auto_exit=False, prompts are required."""
        from setup import PagedSetupState, run_phase_8_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_mount = Path(tmpdir)
            smartdrive_dir = launcher_mount / ".smartdrive"
            scripts_dir = smartdrive_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            config_path = smartdrive_dir / "config.json"
            config_path.write_text("{}")

            state = PagedSetupState()
            state.launcher_mount = launcher_mount
            state.payload_device = "TestPayload"
            state.mount_letter = "V"
            state.use_gpg = False
            state.use_keyfile = False
            state.fingerprints = []
            state.password = "test"
            state.security_mode = SecurityMode.PW_ONLY.value

            # Mock success screen to return Q
            with patch("setup.show_setup_success_screen", return_value="Q"):
                # input() should be called for log review prompt
                with patch("builtins.input", return_value="") as mock_input:
                    result = run_phase_8_summary(state, auto_exit=False)

                    assert result == 0
                    # Verify input was called (for log review prompt)
                    assert mock_input.call_count > 0, "input() should be called in interactive mode"


class TestRecoveryDetection:
    """Test recovery kit detection helper."""

    def test_detect_recovery_with_html(self):
        """Detect recovery when HTML kit exists."""
        from core.paths import Paths
        from setup import detect_recovery_generated

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_root = Path(tmpdir)
            recovery_dir = Paths.recovery_dir(launcher_root)
            recovery_dir.mkdir(parents=True)

            # Create HTML kit
            html = recovery_dir / "SmartDrive_Recovery_Kit.html"
            html.write_text("<html></html>")

            assert detect_recovery_generated(launcher_root), "Should detect HTML kit"

    def test_detect_recovery_with_container_and_header(self):
        """Detect recovery when both container and header exist."""
        from core.paths import Paths
        from setup import detect_recovery_generated

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_root = Path(tmpdir)
            recovery_dir = Paths.recovery_dir(launcher_root)
            recovery_dir.mkdir(parents=True)

            # Create container and header
            container = recovery_dir / "recovery_container.bin"
            header = recovery_dir / "header_backup.hdr"
            container.write_bytes(b"test")
            header.write_bytes(b"test")

            assert detect_recovery_generated(launcher_root), "Should detect container + header"

    def test_detect_no_recovery(self):
        """Return False when no recovery artifacts exist."""
        from setup import detect_recovery_generated

        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_root = Path(tmpdir)

            assert not detect_recovery_generated(launcher_root), "Should return False when no recovery exists"


class TestOpenFolderCLI:
    """Test CLI folder opener."""

    def test_open_folder_nonexistent_path(self):
        """Opening nonexistent path should return False."""
        from setup import open_folder_cli

        fake_path = Path("/definitely/does/not/exist/xyz999")
        result = open_folder_cli(fake_path)

        assert result is False, "Should return False for nonexistent path"

    def test_open_folder_accepts_path_object(self):
        """Function should accept Path objects."""
        from setup import open_folder_cli

        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir)

            # Mock platform-specific call
            with patch("setup.get_platform", return_value="linux"):
                with patch("subprocess.run") as mock_run:
                    result = open_folder_cli(test_path)

                    # Should have called subprocess.run
                    mock_run.assert_called_once()
                    assert result is True
