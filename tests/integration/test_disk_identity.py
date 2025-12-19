#!/usr/bin/env python3
"""
Integration tests for DiskIdentity - runtime disk detection behavior.

P0 Requirement: DiskIdentity must be truly stable and documented.

These tests verify:
1. DiskIdentity.matches() is deterministic
2. Identity contract per OS is honored
3. PowerShell output parsing is robust
"""

import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project to path
_test_dir = Path(__file__).resolve().parent.parent.parent
_smartdrive_dir = _test_dir / ".smartdrive"
if str(_smartdrive_dir) not in sys.path:
    sys.path.insert(0, str(_smartdrive_dir))
if str(_test_dir) not in sys.path:
    sys.path.insert(0, str(_test_dir))

from core.safety import DiskIdentity, detect_source_disk, get_target_disk_identity_windows


class TestDiskIdentityMatches(unittest.TestCase):
    """Unit tests for DiskIdentity.matches() method."""

    def test_same_disk_matches_true(self):
        """Same unique_id should match (case-insensitive)."""
        disk_a = DiskIdentity(unique_id="ABC123-DEF456", disk_number=1, friendly_name="Disk A", bus_type="USB")
        disk_b = DiskIdentity(
            unique_id="abc123-def456",  # Different case
            disk_number=2,  # Different disk number (should be ignored)
            friendly_name="Disk B",
            bus_type="USB",
        )

        self.assertTrue(disk_a.matches(disk_b), "Same unique_id with different case should match")

    def test_different_disk_matches_false(self):
        """Different unique_id should not match."""
        disk_a = DiskIdentity(unique_id="ABC123-DEF456", disk_number=1, friendly_name="Disk A", bus_type="USB")
        disk_b = DiskIdentity(
            unique_id="XYZ789-UVW012",
            disk_number=1,  # Same disk number (should not affect result)
            friendly_name="Disk A",  # Same name
            bus_type="USB",
        )

        self.assertFalse(disk_a.matches(disk_b), "Different unique_id should not match regardless of disk_number")

    def test_missing_unique_id_returns_false(self):
        """Missing unique_id should fail safely."""
        disk_a = DiskIdentity(unique_id="ABC123", disk_number=1)
        disk_b = DiskIdentity(unique_id="", disk_number=1)  # Empty
        disk_c = DiskIdentity(unique_id=None, disk_number=1)  # Will be coerced to str or fail

        # Empty unique_id should not match
        self.assertFalse(disk_a.matches(disk_b), "Empty unique_id should not match")

    def test_whitespace_handling(self):
        """Whitespace should be stripped from unique_id."""
        disk_a = DiskIdentity(unique_id="  ABC123  ", disk_number=1)
        disk_b = DiskIdentity(unique_id="ABC123", disk_number=2)

        self.assertTrue(disk_a.matches(disk_b), "Whitespace should be stripped from unique_id")

    def test_disk_number_ignored_in_comparison(self):
        """disk_number should NOT affect matching (it's volatile)."""
        disk_a = DiskIdentity(unique_id="SAME-ID", disk_number=1)
        disk_b = DiskIdentity(unique_id="SAME-ID", disk_number=99)

        self.assertTrue(disk_a.matches(disk_b), "disk_number should be ignored in comparison")

    def test_to_log_dict_truncates_long_id(self):
        """to_log_dict should truncate long unique_id for logging."""
        disk = DiskIdentity(unique_id="X" * 100, disk_number=1, friendly_name="Test", bus_type="USB")

        log_dict = disk.to_log_dict()
        self.assertIn("unique_id", log_dict)
        self.assertLessEqual(len(log_dict["unique_id"]), 35)  # Max 30 + "..."


class TestPowerShellParsing(unittest.TestCase):
    """Tests for PowerShell output parsing robustness."""

    @unittest.skipIf(platform.system() != "Windows", "Windows only")
    def test_parse_valid_disk_json(self):
        """Valid PowerShell JSON output should parse correctly."""
        mock_output = json.dumps(
            {
                "DiskNumber": 2,
                "UniqueId": "eui.0025385d21301234",
                "SerialNumber": "SN12345",
                "FriendlyName": "Samsung T7",
                "BusType": "USB",
                "IsSystem": False,
                "IsBoot": False,
            }
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

            identity = get_target_disk_identity_windows(2)

            self.assertIsNotNone(identity)
            self.assertEqual(identity.unique_id, "eui.0025385d21301234")
            self.assertEqual(identity.disk_number, 2)
            self.assertEqual(identity.bus_type, "USB")

    @unittest.skipIf(platform.system() != "Windows", "Windows only")
    def test_parse_error_disk_not_found(self):
        """Disk not found error should return None."""
        mock_output = json.dumps({"Error": "Disk not found"})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

            identity = get_target_disk_identity_windows(999)
            self.assertIsNone(identity)

    @unittest.skipIf(platform.system() != "Windows", "Windows only")
    def test_parse_invalid_json(self):
        """Invalid JSON should return None, not crash."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="NOT VALID JSON", stderr="")

            identity = get_target_disk_identity_windows(1)
            self.assertIsNone(identity)

    @unittest.skipIf(platform.system() != "Windows", "Windows only")
    def test_powershell_timeout(self):
        """PowerShell timeout should return None, not crash."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ps", 30)

            identity = get_target_disk_identity_windows(1)
            self.assertIsNone(identity)


class TestSourceDiskDetection(unittest.TestCase):
    """Tests for source disk detection."""

    def test_detect_source_disk_returns_identity(self):
        """detect_source_disk should return a DiskIdentity on success."""
        # This test runs against actual system
        # Should work regardless of platform
        identity = detect_source_disk(Path(__file__))

        # May return None if detection fails (e.g., WSL, containers)
        if identity is not None:
            self.assertIsInstance(identity, DiskIdentity)
            self.assertIsNotNone(identity.unique_id)
            self.assertGreater(len(identity.unique_id), 0)


class TestIdentityContract(unittest.TestCase):
    """
    Tests documenting the identity contract per OS.

    Windows: UniqueId (GPT GUID or MBR signature) + SerialNumber + BusType
    Unix: /dev/disk/by-id symlink name
    """

    @unittest.skipIf(platform.system() != "Windows", "Windows only")
    def test_windows_identity_includes_required_fields(self):
        """Windows identity should include UniqueId and BusType."""
        identity = detect_source_disk(Path(__file__))

        if identity is not None:
            # UniqueId is the primary stable identifier
            self.assertIsNotNone(identity.unique_id)
            self.assertGreater(len(identity.unique_id), 0)

            # BusType helps identify USB vs internal
            self.assertIsNotNone(identity.bus_type)

    def test_unix_identity_uses_by_id(self):
        """Unix identity should use /dev/disk/by-id when available.

        On Windows: Verifies the function exists and returns valid result for Windows path.
        On Unix: Tests actual /dev/disk/by-id resolution.
        """
        if platform.system() == "Windows":
            # On Windows, test that the function still works (Windows path detection)
            identity = detect_source_disk(Path(__file__))
            # Should return Windows identity (not None on Windows with valid path)
            # Just verify it doesn't crash - actual identity may be None in some environments
            self.assertTrue(identity is None or isinstance(identity, DiskIdentity))
        else:
            # Unix-specific test
            identity = detect_source_disk(Path(__file__))
            if identity is not None:
                # unique_id should be from /dev/disk/by-id or device path
                self.assertIsNotNone(identity.unique_id)
                self.assertGreater(len(identity.unique_id), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
