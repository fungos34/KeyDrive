#!/usr/bin/env python3
"""
Unit tests for P0-A: normalize_mount_letter and VeraCrypt command building.

These tests ensure:
1. normalize_mount_letter returns canonical "Z" format (uppercase single letter)
2. The /letter value NEVER starts with "/" or "-"
3. No empty arguments in command arrays
"""

import sys
from pathlib import Path

# Add project root and .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"

sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_smartdrive_root))

import pytest
from core.paths import normalize_mount_letter


class TestNormalizeMountLetter:
    """Tests for normalize_mount_letter function."""

    def test_uppercase_single_letter(self):
        """Test uppercase single letter input."""
        assert normalize_mount_letter("Z") == "Z"
        assert normalize_mount_letter("A") == "A"
        assert normalize_mount_letter("M") == "M"

    def test_lowercase_single_letter(self):
        """Test lowercase single letter input."""
        assert normalize_mount_letter("z") == "Z"
        assert normalize_mount_letter("a") == "A"

    def test_letter_with_colon(self):
        """Test letter with colon (Windows path style)."""
        assert normalize_mount_letter("Z:") == "Z"
        assert normalize_mount_letter("z:") == "Z"
        assert normalize_mount_letter("A:") == "A"

    def test_letter_with_leading_slash(self):
        """Test letter with leading slash (should be stripped)."""
        assert normalize_mount_letter("/Z") == "Z"
        assert normalize_mount_letter("/z") == "Z"
        assert normalize_mount_letter("/Z:") == "Z"

    def test_letter_with_whitespace(self):
        """Test letter with whitespace (should be trimmed)."""
        assert normalize_mount_letter(" Z ") == "Z"
        assert normalize_mount_letter("  z:  ") == "Z"
        assert normalize_mount_letter(" /Z: ") == "Z"

    def test_never_returns_slash_prefix(self):
        """CRITICAL: Result must NEVER start with '/' or '-'."""
        test_inputs = ["Z", "z", "Z:", "z:", "/Z", "/z", " /Z: ", "-Z"]
        for inp in test_inputs:
            result = normalize_mount_letter(inp)
            assert not result.startswith("/"), f"Result '{result}' starts with '/'"
            assert not result.startswith("-"), f"Result '{result}' starts with '-'"

    def test_result_is_single_uppercase_alpha(self):
        """Result must be single uppercase alphabetic character."""
        test_inputs = ["Z", "z", "Z:", "/z", " A: "]
        for inp in test_inputs:
            result = normalize_mount_letter(inp)
            assert len(result) == 1, f"Result '{result}' is not single char"
            assert result.isalpha(), f"Result '{result}' is not alphabetic"
            assert result.isupper(), f"Result '{result}' is not uppercase"

    def test_empty_string_raises(self):
        """Empty string must raise ValueError."""
        with pytest.raises(ValueError):
            normalize_mount_letter("")

    def test_whitespace_only_raises(self):
        """Whitespace-only string must raise ValueError."""
        with pytest.raises(ValueError):
            normalize_mount_letter("   ")

    def test_multi_char_raises(self):
        """Multi-character (after cleanup) must raise ValueError."""
        with pytest.raises(ValueError):
            normalize_mount_letter("AB")
        with pytest.raises(ValueError):
            normalize_mount_letter("ZZ")

    def test_non_alpha_raises(self):
        """Non-alphabetic character must raise ValueError."""
        with pytest.raises(ValueError):
            normalize_mount_letter("1")
        with pytest.raises(ValueError):
            normalize_mount_letter("@")

    def test_regression_no_slash_z(self):
        """REGRESSION TEST: Must never return '/z' or similar."""
        test_inputs = ["Z", "z", "Z:", "z:", "/Z", "/z", " /Z: "]
        for inp in test_inputs:
            result = normalize_mount_letter(inp)
            assert result != "/z", f"REGRESSION: Got '/z' from input '{inp}'"
            assert result != "/Z", f"REGRESSION: Got '/Z' from input '{inp}'"
            assert "/" not in result, f"REGRESSION: Result '{result}' contains '/'"


class TestVeraCryptCommandBuilder:
    """Tests for VeraCrypt command building."""

    def test_letter_value_format(self):
        """Test that /letter value is in canonical format."""
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        # Use SSOT for VeraCrypt path
        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        cmd = build_veracrypt_mount_cmd_windows(vc_exe=vc_exe, volume="E:", mount_letter="Z", password="testpw123")

        # Find /letter index
        letter_idx = cmd.index("/letter")
        letter_value = cmd[letter_idx + 1]

        # Value must NOT start with "/" or "-"
        assert not letter_value.startswith("/"), f"Letter value '{letter_value}' starts with '/'"
        assert not letter_value.startswith("-"), f"Letter value '{letter_value}' starts with '-'"

        # Must be canonical format (single uppercase letter)
        assert len(letter_value) == 1 or (len(letter_value) == 2 and letter_value[1] == ":")
        assert letter_value[0].isalpha()
        assert letter_value[0].isupper()

    def test_no_empty_arguments(self):
        """Test that command has no empty arguments."""
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        cmd = build_veracrypt_mount_cmd_windows(vc_exe=vc_exe, volume="E:", mount_letter="Z", password="testpw123")

        for i, arg in enumerate(cmd):
            assert arg, f"Empty argument at position {i}"
            assert len(arg) > 0, f"Zero-length argument at position {i}"

    def test_regression_slash_z_never_appears(self):
        """REGRESSION: /z must never appear in command."""
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        # Test various input formats
        for letter_input in ["Z", "z", "Z:", "/Z", " z: "]:
            cmd = build_veracrypt_mount_cmd_windows(
                vc_exe=vc_exe, volume="E:", mount_letter=letter_input, password="testpw123"
            )

            # Check that "/z" or similar never appears
            for arg in cmd:
                assert arg != "/z", f"REGRESSION: '/z' in command from input '{letter_input}'"
                assert arg != "/Z", f"REGRESSION: '/Z' in command from input '{letter_input}'"
                assert (
                    not arg.startswith("/")
                    or arg.startswith("/v")
                    or arg.startswith("/l")
                    or arg.startswith("/p")
                    or arg.startswith("/q")
                    or arg.startswith("/s")
                    or arg.startswith("/k")
                ), f"Unexpected slash-prefixed arg: {arg}"


class TestWindowsVeraCryptArgvInspection:
    """
    End-to-end verification of Windows VeraCrypt CLI argv.

    Per AGENT_ARCHITECTURE.md:
    - Windows uses ONLY: /volume /letter /password /quit /silent /keyfile
    - Linux uses ONLY: --text --password --keyfiles --mount --dismount
    - NEVER mix Windows and Linux flags
    - NEVER produce empty arguments
    """

    # Windows-only VeraCrypt flags
    WINDOWS_FLAGS = {"/volume", "/letter", "/password", "/quit", "/silent", "/keyfile", "/ro"}

    # Linux-only VeraCrypt flags (MUST NOT appear on Windows)
    LINUX_FLAGS = {
        "--text",
        "--password",
        "--keyfiles",
        "--mount",
        "--dismount",
        "--non-interactive",
        "--stdin",
        "--protect-hidden=no",
        "-t",
        "-p",
        "-k",
    }

    def test_windows_only_flags_used(self):
        """Verify only Windows flags are used in command."""
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        cmd = build_veracrypt_mount_cmd_windows(vc_exe=vc_exe, volume="E:", mount_letter="Z", password="testpw123")

        # Check each flag-like argument
        for arg in cmd:
            if arg.startswith("-"):
                # Must be a Windows flag (starts with /)
                assert False, f"Linux-style flag '{arg}' found in Windows command"
            elif arg.startswith("/"):
                # Must be known Windows flag
                flag = "/" + arg[1:].split()[0]  # Handle /flag value
                assert any(arg.startswith(wf) for wf in self.WINDOWS_FLAGS), f"Unknown Windows flag: {arg}"

    def test_no_linux_flags_in_windows_command(self):
        """CRITICAL: No Linux flags must appear in Windows command."""
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        cmd = build_veracrypt_mount_cmd_windows(vc_exe=vc_exe, volume="E:", mount_letter="Z", password="testpw123")

        cmd_str = " ".join(cmd)
        for linux_flag in self.LINUX_FLAGS:
            assert linux_flag not in cmd_str, f"Linux flag '{linux_flag}' found in Windows command: {cmd_str}"

    def test_argv_structure_is_valid(self):
        """
        Validate complete argv structure for Windows VeraCrypt.

        Expected format:
        [VeraCrypt.exe, /volume, <path>, /letter, <letter>, /password, <pw>, /quit, /silent]
        """
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        cmd = build_veracrypt_mount_cmd_windows(vc_exe=vc_exe, volume="E:", mount_letter="Z", password="secret123")

        # Validate structure
        assert len(cmd) >= 9, f"Command too short: {len(cmd)} args"

        # First arg is VeraCrypt.exe path
        assert "veracrypt" in cmd[0].lower() or "VeraCrypt" in cmd[0]

        # Must contain required flags
        assert "/volume" in cmd, "Missing /volume flag"
        assert "/letter" in cmd, "Missing /letter flag"
        assert "/password" in cmd, "Missing /password flag"
        assert "/quit" in cmd, "Missing /quit flag"
        assert "/silent" in cmd, "Missing /silent flag"

        # /letter value must be single uppercase letter
        letter_idx = cmd.index("/letter")
        letter_val = cmd[letter_idx + 1]
        assert (
            len(letter_val) == 1 and letter_val.isalpha() and letter_val.isupper()
        ), f"/letter value must be single uppercase letter, got: '{letter_val}'"

    def test_argv_dry_run_inspection(self):
        """
        DRY-RUN: Print the final argv for visual inspection.
        This test always passes but outputs the command for verification.
        """
        from core.paths import Paths
        from setup import build_veracrypt_mount_cmd_windows

        vc_exe = Paths.veracrypt_exe()
        if vc_exe is None:
            pytest.skip("VeraCrypt not installed")

        # Use a relative path pattern for volume (test data, not real path)
        test_volume = "E:"  # Drive letter only, not absolute path

        cmd = build_veracrypt_mount_cmd_windows(
            vc_exe=vc_exe, volume=test_volume, mount_letter="Z", password="test_password_123"
        )

        # Print for inspection
        print("\n=== Windows VeraCrypt argv (DRY-RUN) ===")
        for i, arg in enumerate(cmd):
            # Mask password
            if i > 0 and cmd[i - 1] == "/password":
                print(f"  [{i}] ********")
            else:
                print(f"  [{i}] {arg}")
        print("=========================================")

        # Test passes - this is for inspection
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
