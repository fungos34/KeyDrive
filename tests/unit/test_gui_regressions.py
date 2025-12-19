#!/usr/bin/env python3
"""
Regression tests for recent GUI fixes.
Tests rely on static analysis of gui.py to avoid Qt requirements.
"""

from pathlib import Path


def _read_gui() -> str:
    project_root = Path(__file__).resolve().parent.parent.parent
    gui_path = project_root / ".smartdrive" / "scripts" / "gui.py"
    return gui_path.read_text(encoding="utf-8")


def test_apply_styles_exists_and_used():
    content = _read_gui()
    assert "def apply_styles(self):" in content
    assert "self.apply_styles()" in content


def test_position_window_respects_user_move():
    content = _read_gui()
    assert "def position_window(self, force: bool = False):" in content
    assert "if self._user_moved and not force:" in content


def test_static_asset_helper_is_deterministic():
    content = _read_gui()
    assert "def get_static_asset" in content
    assert "Paths.static_file" in content
    assert "self._launcher_root" in content


def test_unmount_slot_signature_accepts_dict_args():
    content = _read_gui()
    assert "@pyqtSlot(bool, str, dict)" in content


def test_logo_loads_from_static_helper():
    content = _read_gui()
    assert 'self.get_static_asset("LOGO_main.png")' in content


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
