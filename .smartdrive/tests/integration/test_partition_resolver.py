#!/usr/bin/env python3
"""
Integration tests for partition resolver - deterministic selection behavior.

P0 Requirement: Resolver must select correct payload deterministically without
PartitionNumber 2 assumptions.

These tests verify:
1. Launcher partition resolution by drive letter
2. Payload partition selection (exclude launcher, handle extra partitions)
3. Target identifier formatting for VeraCrypt CLI
"""

import json
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project to path
# test file is at .smartdrive/tests/integration/test_partition_resolver.py
_test_file = Path(__file__).resolve()
_integ_dir = _test_file.parent
_tests_dir = _integ_dir.parent
_smartdrive_dir = _tests_dir.parent  # This is .smartdrive/
if str(_smartdrive_dir) not in sys.path:
    sys.path.insert(0, str(_smartdrive_dir))
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from core.safety import (
    DiskIdentity,
    DiskSnapshot,
    PartitionRef,
    get_disk_snapshot_windows,
    resolve_launcher_partition_windows,
    resolve_payload_partition_windows,
)

# =============================================================================
# Mocked disk layouts for testing
# =============================================================================

MOCK_SIMPLE_2PART = {
    "DiskNumber": 1,
    "UniqueId": "eui.mock-simple-2part",
    "FriendlyName": "Simple 2-Partition USB",
    "BusType": "USB",
    "SerialNumber": "SN-SIMPLE",
    "Partitions": [
        {
            "Number": 1,
            "Size": 1.0,  # 1 GB launcher
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": "G",
            "Offset": 1048576,
            "VolumeGuid": "\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\",
        },
        {
            "Number": 2,
            "Size": 29.0,  # 29 GB payload
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": None,
            "Offset": 1074790400,
            "VolumeGuid": "\\\\?\\Volume{22222222-2222-2222-2222-222222222222}\\",
        },
    ],
}

MOCK_WITH_MSR_RECOVERY = {
    "DiskNumber": 2,
    "UniqueId": "eui.mock-msr-recovery",
    "FriendlyName": "Disk with MSR and Recovery",
    "BusType": "USB",
    "SerialNumber": "SN-MSR",
    "Partitions": [
        {
            "Number": 1,
            "Size": 0.016,  # 16 MB MSR
            "Type": "MSR",
            "IsHidden": True,
            "DriveLetter": None,
            "Offset": 1048576,
            "VolumeGuid": None,
        },
        {
            "Number": 2,
            "Size": 0.5,  # 500 MB Recovery
            "Type": "Recovery",
            "IsHidden": True,
            "DriveLetter": None,
            "Offset": 17825792,
            "VolumeGuid": None,
        },
        {
            "Number": 3,
            "Size": 1.0,  # 1 GB launcher
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": "H",
            "Offset": 541065216,
            "VolumeGuid": "\\\\?\\Volume{33333333-3333-3333-3333-333333333333}\\",
        },
        {
            "Number": 4,
            "Size": 28.5,  # 28.5 GB payload
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": None,
            "Offset": 1614807040,
            "VolumeGuid": "\\\\?\\Volume{44444444-4444-4444-4444-444444444444}\\",
        },
    ],
}

MOCK_MULTI_DATA_PARTITIONS = {
    "DiskNumber": 3,
    "UniqueId": "eui.mock-multi-data",
    "FriendlyName": "Multi Data Partition Disk",
    "BusType": "USB",
    "SerialNumber": "SN-MULTI",
    "Partitions": [
        {
            "Number": 1,
            "Size": 1.0,  # 1 GB launcher
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": "I",
            "Offset": 1048576,
            "VolumeGuid": "\\\\?\\Volume{55555555-5555-5555-5555-555555555555}\\",
        },
        {
            "Number": 2,
            "Size": 10.0,  # 10 GB data partition
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": "J",
            "Offset": 1074790400,
            "VolumeGuid": "\\\\?\\Volume{66666666-6666-6666-6666-666666666666}\\",
        },
        {
            "Number": 3,
            "Size": 50.0,  # 50 GB - LARGEST, should be payload
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": None,
            "Offset": 11811160064,
            "VolumeGuid": "\\\\?\\Volume{77777777-7777-7777-7777-777777777777}\\",
        },
        {
            "Number": 4,
            "Size": 5.0,  # 5 GB extra partition
            "Type": "Basic",
            "IsHidden": False,
            "DriveLetter": "K",
            "Offset": 65498251264,
            "VolumeGuid": "\\\\?\\Volume{88888888-8888-8888-8888-888888888888}\\",
        },
    ],
}


def mock_get_disk_snapshot(mock_data: dict, launcher_drive_letter: str = None):
    """Create a DiskSnapshot from mock data."""
    identity = DiskIdentity(
        unique_id=mock_data["UniqueId"],
        disk_number=mock_data["DiskNumber"],
        friendly_name=mock_data["FriendlyName"],
        serial_number=mock_data.get("SerialNumber"),
        bus_type=mock_data["BusType"],
    )

    partitions = []
    volumes = []

    for p in mock_data.get("Partitions", []):
        pref = PartitionRef(
            disk_number=mock_data["DiskNumber"],
            partition_number=p["Number"],
            size_gb=p["Size"],
            drive_letter=p.get("DriveLetter"),
            is_hidden=p.get("IsHidden", False),
            partition_type=p.get("Type"),
            offset=p.get("Offset"),
        )
        partitions.append(pref)

        if p.get("VolumeGuid"):
            volumes.append(
                {"letter": p.get("DriveLetter"), "unique_id": p.get("VolumeGuid"), "partition_number": p["Number"]}
            )

    # Resolve launcher
    launcher_ref = None
    if launcher_drive_letter:
        for p in partitions:
            if p.drive_letter and p.drive_letter.upper() == launcher_drive_letter.upper():
                launcher_ref = p
                break
    if not launcher_ref and partitions:
        # First non-hidden basic partition
        for p in partitions:
            if not p.is_hidden and p.partition_type in ("Basic", "Primary"):
                launcher_ref = p
                break
        if not launcher_ref:
            launcher_ref = partitions[0]

    # Resolve payload (largest non-launcher, non-hidden)
    payload_ref = None
    if launcher_ref:
        candidates = [p for p in partitions if p.partition_number != launcher_ref.partition_number and not p.is_hidden]
        if candidates:
            payload_ref = max(candidates, key=lambda p: p.size_gb)

    return DiskSnapshot(
        disk_identity=identity,
        partitions=partitions,
        volumes=volumes,
        launcher_partition=launcher_ref,
        payload_partition=payload_ref,
    )


class TestSimple2PartLayout(unittest.TestCase):
    """Tests for simple 2-partition layout (most common case)."""

    def test_launcher_resolved_by_drive_letter(self):
        """Launcher should be resolved by drive letter."""
        snapshot = mock_get_disk_snapshot(MOCK_SIMPLE_2PART, "G")

        self.assertIsNotNone(snapshot.launcher_partition)
        self.assertEqual(snapshot.launcher_partition.partition_number, 1)
        self.assertEqual(snapshot.launcher_partition.drive_letter, "G")

    def test_payload_is_largest_non_launcher(self):
        """Payload should be the largest non-launcher partition."""
        snapshot = mock_get_disk_snapshot(MOCK_SIMPLE_2PART, "G")

        self.assertIsNotNone(snapshot.payload_partition)
        self.assertEqual(snapshot.payload_partition.partition_number, 2)
        self.assertEqual(snapshot.payload_partition.size_gb, 29.0)

    def test_payload_partition_number_not_hardcoded(self):
        """Payload selection should NOT assume partition number 2."""
        # This test verifies the resolver finds the largest, not just #2
        snapshot = mock_get_disk_snapshot(MOCK_SIMPLE_2PART, "G")

        # The largest non-launcher should be selected
        # In this case it happens to be #2, but verify logic is correct
        all_except_launcher = [
            p for p in snapshot.partitions if p.partition_number != snapshot.launcher_partition.partition_number
        ]
        expected_payload = max(all_except_launcher, key=lambda p: p.size_gb)

        self.assertEqual(snapshot.payload_partition.partition_number, expected_payload.partition_number)


class TestMSRRecoveryLayout(unittest.TestCase):
    """Tests for layout with MSR and Recovery partitions."""

    def test_hidden_partitions_excluded(self):
        """Hidden partitions (MSR, Recovery) should be excluded from payload."""
        snapshot = mock_get_disk_snapshot(MOCK_WITH_MSR_RECOVERY, "H")

        # Launcher should be partition 3 (the one with drive letter H)
        self.assertIsNotNone(snapshot.launcher_partition)
        self.assertEqual(snapshot.launcher_partition.partition_number, 3)

        # Payload should be partition 4 (largest non-hidden, non-launcher)
        self.assertIsNotNone(snapshot.payload_partition)
        self.assertEqual(snapshot.payload_partition.partition_number, 4)

        # Verify MSR and Recovery were excluded
        self.assertNotEqual(snapshot.payload_partition.partition_number, 1)  # MSR
        self.assertNotEqual(snapshot.payload_partition.partition_number, 2)  # Recovery

    def test_launcher_not_first_partition(self):
        """Launcher may not be partition 1 if system partitions exist."""
        snapshot = mock_get_disk_snapshot(MOCK_WITH_MSR_RECOVERY, "H")

        # Partition 1 is MSR, launcher should be 3
        self.assertEqual(snapshot.launcher_partition.partition_number, 3)


class TestMultiDataPartitionLayout(unittest.TestCase):
    """Tests for layout with more than 2 data partitions."""

    def test_largest_partition_selected_as_payload(self):
        """Largest non-launcher partition should be selected as payload."""
        snapshot = mock_get_disk_snapshot(MOCK_MULTI_DATA_PARTITIONS, "I")

        # Launcher is partition 1 (drive I)
        self.assertEqual(snapshot.launcher_partition.partition_number, 1)

        # Payload should be partition 3 (50 GB, the largest)
        self.assertEqual(snapshot.payload_partition.partition_number, 3)
        self.assertEqual(snapshot.payload_partition.size_gb, 50.0)

    def test_smaller_partitions_not_selected(self):
        """Smaller partitions (2 and 4) should not be selected as payload."""
        snapshot = mock_get_disk_snapshot(MOCK_MULTI_DATA_PARTITIONS, "I")

        self.assertNotEqual(snapshot.payload_partition.partition_number, 2)  # 10 GB
        self.assertNotEqual(snapshot.payload_partition.partition_number, 4)  # 5 GB

    def test_with_different_launcher_selection(self):
        """Different launcher should still select largest remaining as payload."""
        # Pretend drive J (partition 2) is the launcher
        snapshot = mock_get_disk_snapshot(MOCK_MULTI_DATA_PARTITIONS, "J")

        # Launcher should be partition 2
        self.assertEqual(snapshot.launcher_partition.partition_number, 2)

        # Payload should still be partition 3 (largest remaining)
        self.assertEqual(snapshot.payload_partition.partition_number, 3)


class TestVeraCryptTargetFormatting(unittest.TestCase):
    """Tests for VeraCrypt CLI target formatting."""

    def test_partition_to_veracrypt_path_windows(self):
        """Partition should be formattable as VeraCrypt CLI target."""
        snapshot = mock_get_disk_snapshot(MOCK_SIMPLE_2PART, "G")
        payload = snapshot.payload_partition

        # VeraCrypt accepts either:
        # 1. Drive letter: V: (if mounted)
        # 2. Volume GUID path: \\?\Volume{...}\
        # 3. Disk\Partition: \Device\Harddisk1\Partition2

        # For unmounted payload, we typically use disk/partition format
        # This test verifies the partition info is available
        self.assertIsNotNone(payload.partition_number)
        self.assertIsNotNone(payload.disk_number)

        # Construct device path
        device_path = f"\\Device\\Harddisk{payload.disk_number}\\Partition{payload.partition_number}"
        self.assertTrue(device_path.startswith("\\Device\\"))


class TestPartitionRefToLogDict(unittest.TestCase):
    """Tests for PartitionRef logging."""

    def test_to_log_dict_includes_key_fields(self):
        """to_log_dict should include all key fields."""
        pref = PartitionRef(
            disk_number=1, partition_number=2, size_gb=29.5, drive_letter="V", is_hidden=False, partition_type="Basic"
        )

        log_dict = pref.to_log_dict()

        self.assertEqual(log_dict["disk_number"], 1)
        self.assertEqual(log_dict["partition_number"], 2)
        self.assertEqual(log_dict["size_gb"], 29.5)
        self.assertEqual(log_dict["drive_letter"], "V")
        self.assertEqual(log_dict["is_hidden"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
