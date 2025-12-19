#!/usr/bin/env python3
"""
Test script for mount status detection
"""

import sys
from pathlib import Path

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from gui import check_mount_status_veracrypt


def test_mount_status():
    """Test the mount status detection."""
    print("Testing mount status detection...")
    is_mounted = check_mount_status_veracrypt()
    print(f"Mount status: {'MOUNTED' if is_mounted else 'NOT MOUNTED'}")
    return is_mounted


if __name__ == "__main__":
    test_mount_status()
