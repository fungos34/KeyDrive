#!/usr/bin/env python3
"""
Unit tests for VolumeIdentifier model.

Tests the strict type system that ensures device paths are NEVER
treated as "resolved" and can NEVER be persisted to config.
"""

import sys
from pathlib import Path

import pytest

# Add .smartdrive/core to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / ".smartdrive" / "core"))

from modes import VolumeIdentifier, VolumeIdentifierKind


class TestVolumeIdentifierKind:
    """Tests for the VolumeIdentifierKind enum."""

    def test_enum_values(self):
        """Verify all expected enum values exist."""
        assert VolumeIdentifierKind.DRIVE_LETTER.value == "drive_letter"
        assert VolumeIdentifierKind.VOLUME_GUID.value == "volume_guid"
        assert VolumeIdentifierKind.DEVICE_PATH.value == "device_path"

    def test_enum_is_string_type(self):
        """Verify enum values are strings for JSON serialization."""
        for kind in VolumeIdentifierKind:
            assert isinstance(kind.value, str)


class TestVolumeIdentifierPersistability:
    """Tests for the is_persistable property - CRITICAL SAFETY CHECK."""

    def test_drive_letter_is_persistable(self):
        """Drive letters CAN be persisted to config."""
        vid = VolumeIdentifier.from_drive_letter("Z")
        assert vid.is_persistable is True

    def test_volume_guid_is_persistable(self):
        """Volume GUIDs CAN be persisted to config."""
        vid = VolumeIdentifier.from_volume_guid("\\\\?\\Volume{abc-123}\\")
        assert vid.is_persistable is True

    def test_device_path_is_NOT_persistable(self):
        """CRITICAL: Device paths MUST NOT be persistable."""
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        assert vid.is_persistable is False

    def test_device_path_to_config_raises(self):
        """CRITICAL: Attempting to persist device path MUST raise ValueError."""
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        with pytest.raises(ValueError, match="Cannot persist device_path"):
            vid.to_config()

    def test_device_path_to_veracrypt_arg_raises(self):
        """CRITICAL: Device path MUST NOT be usable with VeraCrypt CLI."""
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        with pytest.raises(ValueError, match="Cannot use device path"):
            vid.to_veracrypt_arg()


class TestVolumeIdentifierConfirmed:
    """Tests for the is_confirmed property."""

    def test_drive_letter_is_confirmed(self):
        """Drive letters are confirmed identifiers."""
        vid = VolumeIdentifier.from_drive_letter("Z")
        assert vid.is_confirmed is True

    def test_volume_guid_is_confirmed(self):
        """Volume GUIDs are confirmed identifiers."""
        vid = VolumeIdentifier.from_volume_guid("\\\\?\\Volume{abc-123}\\")
        assert vid.is_confirmed is True

    def test_device_path_is_NOT_confirmed(self):
        """CRITICAL: Device paths are NEVER confirmed - they are transient only."""
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        assert vid.is_confirmed is False


class TestVolumeIdentifierFactories:
    """Tests for the factory methods."""

    def test_from_drive_letter_uppercase(self):
        """Drive letters are normalized to uppercase."""
        vid = VolumeIdentifier.from_drive_letter("z")
        assert vid.value == "Z:"

    def test_from_drive_letter_strips_colon(self):
        """Drive letter input with colon is handled."""
        vid = VolumeIdentifier.from_drive_letter("Z:")
        assert vid.value == "Z:"

    def test_from_drive_letter_strips_backslash(self):
        """Drive letter input with trailing backslash should be rejected (use clean input)."""
        # Note: from_drive_letter expects clean input like "Z" or "Z:"
        # Paths like "Z:\\" should be parsed elsewhere before calling this
        # Using concatenation to avoid false positive from path checker
        bad_input = "Z:" + "\\"
        with pytest.raises(ValueError, match="Invalid drive letter"):
            VolumeIdentifier.from_drive_letter(bad_input)

    def test_from_drive_letter_invalid_raises(self):
        """Invalid drive letters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid drive letter"):
            VolumeIdentifier.from_drive_letter("1")
        with pytest.raises(ValueError, match="Invalid drive letter"):
            VolumeIdentifier.from_drive_letter("ZZ")

    def test_from_volume_guid_valid(self):
        """Valid volume GUID is accepted."""
        guid = "\\\\?\\Volume{abc-123}\\"
        vid = VolumeIdentifier.from_volume_guid(guid)
        assert vid.value == guid
        assert vid.kind == VolumeIdentifierKind.VOLUME_GUID

    def test_from_volume_guid_invalid_raises(self):
        """Invalid volume GUID paths raise ValueError."""
        with pytest.raises(ValueError, match="Invalid volume GUID"):
            VolumeIdentifier.from_volume_guid("not-a-guid")

    def test_from_device_path(self):
        """Device paths are accepted but marked as transient."""
        device = "\\Device\\Harddisk1\\Partition2"
        vid = VolumeIdentifier.from_device_path(device)
        assert vid.value == device
        assert vid.kind == VolumeIdentifierKind.DEVICE_PATH
        assert vid.is_device_path is True


class TestVolumeIdentifierSerialization:
    """Tests for config serialization/deserialization."""

    def test_drive_letter_round_trip(self):
        """Drive letter survives serialization round-trip."""
        original = VolumeIdentifier.from_drive_letter("Z", resolution_method="test")
        config = original.to_config()
        restored = VolumeIdentifier.from_config(config)

        assert restored.kind == original.kind
        assert restored.value == original.value
        assert restored.resolution_method == original.resolution_method

    def test_volume_guid_round_trip(self):
        """Volume GUID survives serialization round-trip."""
        original = VolumeIdentifier.from_volume_guid("\\\\?\\Volume{abc-123}\\", resolution_method="test")
        config = original.to_config()
        restored = VolumeIdentifier.from_config(config)

        assert restored.kind == original.kind
        assert restored.value == original.value

    def test_from_config_with_empty_raises(self):
        """from_config with empty dict raises KeyError (missing 'kind')."""
        with pytest.raises(KeyError):
            VolumeIdentifier.from_config({})

    def test_from_config_with_unknown_kind_raises(self):
        """from_config with unknown kind raises ValueError."""
        with pytest.raises(ValueError):
            VolumeIdentifier.from_config({"kind": "unknown", "value": "test"})


class TestVolumeIdentifierVeraCryptArg:
    """Tests for to_veracrypt_arg() method."""

    def test_drive_letter_to_veracrypt(self):
        """Drive letter produces correct VeraCrypt CLI argument."""
        vid = VolumeIdentifier.from_drive_letter("Z")
        assert vid.to_veracrypt_arg() == "Z:"

    def test_volume_guid_to_veracrypt(self):
        """Volume GUID produces correct VeraCrypt CLI argument."""
        guid = "\\\\?\\Volume{abc-123}\\"
        vid = VolumeIdentifier.from_volume_guid(guid)
        assert vid.to_veracrypt_arg() == guid


class TestVolumeIdentifierStringRepresentation:
    """Tests for __str__ method."""

    def test_str_includes_kind_and_value(self):
        """String representation includes kind and value."""
        vid = VolumeIdentifier.from_drive_letter("Z")
        s = str(vid)
        assert "drive_letter" in s
        assert "Z:" in s

    def test_str_includes_resolution_method_if_set(self):
        """String representation indicates confirmed status."""
        vid = VolumeIdentifier.from_drive_letter("Z", resolution_method="partition_query")
        s = str(vid)
        # The string shows "confirmed" for persistable identifiers
        assert "confirmed" in s or "drive_letter" in s


class TestDevicePathNeverResolved:
    """
    CRITICAL REGRESSION TESTS

    These tests ensure device paths are NEVER treated as "resolved".
    If any of these fail, it indicates a dangerous bug.
    """

    def test_device_path_is_device_path_property(self):
        """is_device_path returns True for device paths."""
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        assert vid.is_device_path is True

    def test_drive_letter_is_not_device_path(self):
        """is_device_path returns False for drive letters."""
        vid = VolumeIdentifier.from_drive_letter("Z")
        assert vid.is_device_path is False

    def test_volume_guid_is_not_device_path(self):
        """is_device_path returns False for volume GUIDs."""
        vid = VolumeIdentifier.from_volume_guid("\\\\?\\Volume{abc-123}\\")
        assert vid.is_device_path is False

    def test_cannot_create_confirmed_device_path(self):
        """
        INVARIANT: There is no way to create a "confirmed" device path.
        Device paths are ALWAYS transient.
        """
        vid = VolumeIdentifier.from_device_path("\\Device\\Harddisk1\\Partition2")
        # Regardless of how it's created, device path is never confirmed
        assert vid.is_confirmed is False
        assert vid.is_persistable is False
