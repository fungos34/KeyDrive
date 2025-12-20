#!/usr/bin/env python3
"""
Tests that theme/language switching cannot crash silently.

These tests verify:
1. No silent exception swallowing in critical paths
2. Global exception hooks are installed
3. Logging is properly configured
4. Logo does NOT use i18n (must be static asset)
5. apply_styles() bridges to apply_styling() correctly
"""

import re
from pathlib import Path

from core.paths import Paths


def _read_file(relative_path: Path) -> str:
    """Read a file relative to .smartdrive root."""
    # tests/unit/test_*.py -> tests/unit -> tests -> .smartdrive
    smartdrive_root = Path(__file__).resolve().parent.parent.parent
    file_path = smartdrive_root / relative_path
    return file_path.read_text(encoding="utf-8")


def _read_gui() -> str:
    return _read_file(Path(Paths.SCRIPTS_SUBDIR) / "gui.py")


def _read_launcher() -> str:
    return _read_file(Path(Paths.SCRIPTS_SUBDIR) / "gui_launcher.py")


class TestNoSilentExceptions:
    """Verify no silent exception swallowing in GUI code."""

    def test_no_bare_except_pass_in_gui(self):
        """Ensure no 'except: pass' or 'except Exception: pass' without logging."""
        content = _read_gui()

        # Pattern for silent exception handling
        silent_patterns = [
            r"except\s*:\s*\n\s*pass",  # except: pass
            r"except\s+Exception\s*:\s*\n\s*pass",  # except Exception: pass
        ]

        for pattern in silent_patterns:
            matches = re.findall(pattern, content)
            assert len(matches) == 0, f"Found silent exception swallowing: {pattern}"

    def test_log_exception_helper_exists(self):
        """Verify log_exception helper function exists."""
        content = _read_gui()
        assert "def log_exception(" in content
        assert "_gui_logger" in content


class TestGlobalExceptionHooks:
    """Verify global exception handling is set up in launcher."""

    def test_sys_excepthook_installed(self):
        """Verify sys.excepthook is installed in gui_launcher.py."""
        content = _read_launcher()
        assert "sys.excepthook = " in content
        assert "create_exception_hook" in content

    def test_qt_message_handler_installed(self):
        """Verify Qt message handler is installed."""
        content = _read_launcher()
        assert "qInstallMessageHandler" in content
        assert "qt_message_handler" in content

    def test_logging_setup_exists(self):
        """Verify rotating log file setup exists."""
        content = _read_launcher()
        assert "setup_logging" in content
        assert "RotatingFileHandler" in content
        assert "gui.log" in content or "gui_log_file" in content


class TestLogoPaths:
    """Verify logo is loaded from static assets, NOT i18n."""

    def test_apply_language_does_not_change_logo(self):
        """apply_language() must NOT call tr('icon_drive') to change logo."""
        content = _read_gui()

        # Find the apply_language method
        match = re.search(r"def apply_language\(self.*?\n(.*?)(?=\n    def |\nclass )", content, re.DOTALL)
        assert match, "apply_language method not found"

        method_body = match.group(1)

        # Verify we don't have the problematic line that changes logo text
        # The old code had: self.title_icon_label.setText(tr("icon_drive", lang=lang_code))
        assert 'title_icon_label.setText(tr("icon_drive"' not in method_body

    def test_logo_uses_static_asset(self):
        """Logo must be loaded from static asset, not emoji from i18n."""
        content = _read_gui()
        assert 'get_static_asset("LOGO_main.png")' in content
        assert "title_icon_label.setPixmap(" in content


class TestApplyStylesBridge:
    """Verify apply_styles() properly bridges to apply_styling()."""

    def test_apply_styles_calls_apply_styling(self):
        """apply_styles() must call apply_styling()."""
        content = _read_gui()

        # Find the apply_styles method
        match = re.search(r"def apply_styles\(self\).*?\n(.*?)(?=\n    def |\n\nclass )", content, re.DOTALL)
        assert match, "apply_styles method not found"

        method_body = match.group(1)
        assert "self.apply_styling()" in method_body

    def test_apply_styles_called_in_apply_theme(self):
        """apply_theme() must call apply_styles() (not apply_styling directly)."""
        content = _read_gui()

        # Find the apply_theme method
        match = re.search(r"def apply_theme\(self.*?\n(.*?)(?=\n    def |\n\nclass )", content, re.DOTALL)
        assert match, "apply_theme method not found"

        method_body = match.group(1)
        assert "self.apply_styles()" in method_body


class TestPopupHelper:
    """Verify popup helper exists and uses tr() at render time."""

    def test_show_popup_helper_exists(self):
        """show_popup helper function must exist."""
        content = _read_gui()
        assert "def show_popup(" in content

    def test_show_popup_uses_tr_at_render_time(self):
        """show_popup must call tr() within the function, not accept pre-translated strings."""
        content = _read_gui()

        # Find show_popup function
        match = re.search(r"def show_popup\(.*?\n(.*?)(?=\ndef |\nclass )", content, re.DOTALL)
        assert match, "show_popup function not found"

        func_body = match.group(1)
        # Should call tr() inside the function
        assert "tr(title_key" in func_body or "tr(body_key" in func_body


class TestPathsModule:
    """Verify Paths module has logs directory helper."""

    def test_logs_dir_exists_in_paths(self):
        """Paths class must have logs_dir method."""
        content = _read_file(Path("core") / "paths.py")
        assert "def logs_dir(" in content
        assert "def gui_log_file(" in content


class TestComboBoxSignalBlocking:
    """Verify combo box signal blocking to prevent recursion crashes."""

    def test_theme_combo_blocks_signals_in_on_theme_changed(self):
        """on_theme_changed must block signals when repopulating theme combo."""
        content = _read_gui()

        # Find on_theme_changed method
        match = re.search(r"def on_theme_changed\(self.*?\n(.*?)(?=\n    def |\nclass )", content, re.DOTALL)
        assert match, "on_theme_changed method not found"

        method_body = match.group(1)
        assert (
            "theme_combo.blockSignals(True)" in method_body
        ), "on_theme_changed must call blockSignals(True) before repopulating"
        assert (
            "theme_combo.blockSignals(False)" in method_body
        ), "on_theme_changed must call blockSignals(False) after repopulating"

    def test_theme_combo_blocks_signals_in_refresh_dialog_labels(self):
        """refresh_dialog_labels must block signals when repopulating theme combo."""
        content = _read_gui()

        # Find refresh_dialog_labels method
        match = re.search(r"def refresh_dialog_labels\(self.*?\n(.*?)(?=\n    def |\nclass )", content, re.DOTALL)
        assert match, "refresh_dialog_labels method not found"

        method_body = match.group(1)
        assert (
            "theme_combo.blockSignals(True)" in method_body
        ), "refresh_dialog_labels must call blockSignals(True) before repopulating"
        assert (
            "theme_combo.blockSignals(False)" in method_body
        ), "refresh_dialog_labels must call blockSignals(False) after repopulating"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
