#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures for KeyDrive tests.

This module sets up the Python path correctly for all tests.
Tests are now located at .smartdrive/tests/ with all code in .smartdrive/.
"""

import sys
from pathlib import Path

# =============================================================================
# Path Setup - Execute BEFORE any test imports
# =============================================================================

# tests/conftest.py → tests/ → .smartdrive/
_tests_dir = Path(__file__).resolve().parent
_smartdrive_root = _tests_dir.parent  # .smartdrive/
_repo_root = _smartdrive_root.parent  # Repository root (contains launchers)

# Add paths in correct order
if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "scripts"))

# Export for tests that need these paths
SMARTDRIVE_ROOT = _smartdrive_root
REPO_ROOT = _repo_root
SCRIPTS_DIR = _smartdrive_root / "scripts"
CORE_DIR = _smartdrive_root / "core"
TESTS_DIR = _tests_dir


def pytest_configure(config):
    """Configure pytest with project paths."""
    # Ensure paths are set up
    pass


# =============================================================================
# Shared Fixtures
# =============================================================================

import pytest


@pytest.fixture
def smartdrive_root():
    """Return the .smartdrive root path."""
    return SMARTDRIVE_ROOT


@pytest.fixture
def repo_root():
    """Return the repository root path."""
    return REPO_ROOT


@pytest.fixture
def scripts_dir():
    """Return the scripts directory path."""
    return SCRIPTS_DIR
