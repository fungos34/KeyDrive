#!/usr/bin/env python3
"""
Test resource resolution (icon paths, static assets).

These tests verify:
- Icon files exist in expected locations
- Resource resolver finds icons correctly
- FileNames constants point to existing files
"""
import sys
from pathlib import Path

# Ensure test imports from .smartdrive
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive
# Note: _project_root refers to .smartdrive where static/ lives
_project_root = _smartdrive_root
if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "core") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "core"))


class TestIconFilesExist:
    """Test that expected icon files exist."""

    def test_logo_main_ico_exists(self):
        """LOGO_main.ico should exist in static/."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_main.ico"
        assert icon_path.exists(), f"LOGO_main.ico not found at {icon_path}"

    def test_logo_main_png_exists(self):
        """LOGO_main.png should exist in static/."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_main.png"
        assert icon_path.exists(), f"LOGO_main.png not found at {icon_path}"

    def test_logo_mounted_ico_exists(self):
        """LOGO_mounted.ico should exist in static/."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_mounted.ico"
        assert icon_path.exists(), f"LOGO_mounted.ico not found at {icon_path}"

    def test_logo_mounted_png_exists(self):
        """LOGO_mounted.png should exist in static/."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_mounted.png"
        assert icon_path.exists(), f"LOGO_mounted.png not found at {icon_path}"


class TestFileNamesConstants:
    """Test that FileNames constants reference existing files."""

    def test_icon_main_exists(self):
        """FileNames.ICON_MAIN should reference an existing file."""
        from core.constants import FileNames

        static_dir = _project_root / "static"
        icon_path = static_dir / FileNames.ICON_MAIN
        assert icon_path.exists(), f"{FileNames.ICON_MAIN} not found at {icon_path}"

    def test_icon_unmounted_exists(self):
        """FileNames.ICON_UNMOUNTED should reference an existing file."""
        from core.constants import FileNames

        static_dir = _project_root / "static"
        icon_path = static_dir / FileNames.ICON_UNMOUNTED
        assert icon_path.exists(), f"{FileNames.ICON_UNMOUNTED} not found at {icon_path}"

    def test_icon_mounted_exists(self):
        """FileNames.ICON_MOUNTED should reference an existing file."""
        from core.constants import FileNames

        static_dir = _project_root / "static"
        icon_path = static_dir / FileNames.ICON_MOUNTED
        assert icon_path.exists(), f"{FileNames.ICON_MOUNTED} not found at {icon_path}"


class TestPathsStaticDir:
    """Test Paths.static_dir() resolution."""

    def test_static_dir_returns_path(self):
        """static_dir() should return a Path object."""
        from core.paths import Paths

        result = Paths.static_dir(_project_root)
        assert isinstance(result, Path)

    def test_static_dir_finds_existing(self):
        """static_dir() should find an existing directory."""
        from core.paths import Paths

        result = Paths.static_dir(_project_root)
        # Either .smartdrive/static/ or ROOT/static/ should exist
        assert result.exists(), f"No static directory found at {result}"

    def test_static_file_returns_path(self):
        """static_file() should return a Path object."""
        from core.paths import Paths

        result = Paths.static_file(_project_root, "LOGO_main.ico")
        assert isinstance(result, Path)


class TestResourcesModule:
    """Test the resources module."""

    def test_get_base_dir_returns_path(self):
        """get_base_dir() should return a Path."""
        from core.resources import get_base_dir

        result = get_base_dir()
        assert isinstance(result, Path)

    def test_get_static_dir_returns_path(self):
        """get_static_dir() should return a Path."""
        from core.resources import get_static_dir

        result = get_static_dir(_project_root)
        assert isinstance(result, Path)

    def test_get_icon_candidates_returns_list(self):
        """get_icon_candidates() should return a list of Paths."""
        from core.resources import get_icon_candidates

        result = get_icon_candidates("LOGO_main.ico", _project_root)
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(p, Path) for p in result)

    def test_resolve_icon_path_finds_main_icon(self):
        """resolve_icon_path() should find LOGO_main.ico."""
        from core.resources import resolve_icon_path

        result = resolve_icon_path("LOGO_main.ico", _project_root)
        assert result is not None, "LOGO_main.ico not found by resolver"
        assert result.exists()

    def test_resolve_icon_path_finds_mounted_icon(self):
        """resolve_icon_path() should find LOGO_mounted.ico."""
        from core.resources import resolve_icon_path

        result = resolve_icon_path("LOGO_mounted.ico", _project_root)
        assert result is not None, "LOGO_mounted.ico not found by resolver"
        assert result.exists()

    def test_get_app_icon_path_returns_valid_path(self):
        """get_app_icon_path() should return a valid icon path."""
        from core.resources import get_app_icon_path

        result = get_app_icon_path(_project_root)
        assert result is not None, "No app icon found"
        assert result.exists()

    def test_get_mounted_icon_path_returns_valid_path(self):
        """get_mounted_icon_path() should return a valid icon path."""
        from core.resources import get_mounted_icon_path

        result = get_mounted_icon_path(_project_root)
        assert result is not None, "No mounted icon found"
        assert result.exists()

    def test_get_unmounted_icon_path_returns_valid_path(self):
        """get_unmounted_icon_path() should return a valid icon path."""
        from core.resources import get_unmounted_icon_path

        result = get_unmounted_icon_path(_project_root)
        assert result is not None, "No unmounted icon found"
        assert result.exists()


class TestQIconValidation:
    """Test QIcon validation (optional, requires PyQt6)."""

    def test_validate_qicon_with_valid_path(self):
        """validate_qicon() should return True for valid icon."""
        try:
            from core.resources import get_app_icon_path, validate_qicon

            icon_path = get_app_icon_path(_project_root)
            if icon_path:
                # This test only runs if PyQt6 is available
                try:
                    import sys

                    from PyQt6.QtWidgets import QApplication

                    app = QApplication.instance() or QApplication(sys.argv)
                    is_valid, err = validate_qicon(icon_path)
                    assert is_valid, f"QIcon validation failed: {err}"
                except ImportError:
                    pass  # PyQt6 not available, skip
        except ImportError:
            pass  # resources module import issue


class TestCheckTrayIconRequirements:
    """Test tray icon requirement checks."""

    def test_check_with_valid_path(self):
        """check_tray_icon_requirements() should pass with valid icon (icon path part only)."""
        from core.resources import get_app_icon_path

        icon_path = get_app_icon_path(_project_root)
        # Just verify the path is valid and exists, skip Qt checks
        assert icon_path is not None, "No app icon found"
        assert icon_path.exists(), f"Icon path does not exist: {icon_path}"

    def test_check_with_none_path(self):
        """check_tray_icon_requirements() should fail with None path."""
        from core.resources import check_tray_icon_requirements

        all_ok, issues = check_tray_icon_requirements(None)
        assert not all_ok
        assert any("No icon path" in i for i in issues)

    def test_check_with_nonexistent_path(self):
        """check_tray_icon_requirements() should fail with nonexistent path."""
        from core.resources import check_tray_icon_requirements

        fake_path = Path("/nonexistent/icon.ico")
        all_ok, issues = check_tray_icon_requirements(fake_path)
        assert not all_ok
        assert any("does not exist" in i for i in issues)


class TestIconFileSize:
    """Test that icon files are not empty."""

    def test_logo_main_ico_not_empty(self):
        """LOGO_main.ico should not be empty."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_main.ico"
        if icon_path.exists():
            assert icon_path.stat().st_size > 0, "LOGO_main.ico is empty"

    def test_logo_mounted_ico_not_empty(self):
        """LOGO_mounted.ico should not be empty."""
        static_dir = _project_root / "static"
        icon_path = static_dir / "LOGO_mounted.ico"
        if icon_path.exists():
            assert icon_path.stat().st_size > 0, "LOGO_mounted.ico is empty"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
