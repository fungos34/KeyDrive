#!/usr/bin/env python3
"""
Unit tests for CLI terminal placement behavior.

P0 Requirement: Terminal placement must be deterministic and clamp to monitor bounds.

These tests verify:
1. Terminal placed adjacent to GUI (right side by default)
2. Terminal placed on left when GUI is near right edge
3. Multi-monitor bounds clamping
4. Terminal never placed off-screen
"""

import sys
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


class MockQRect:
    """Mock Qt QRect for testing without PyQt6."""

    def __init__(self, x, y, width, height):
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._width

    def height(self):
        return self._height

    def center(self):
        return MagicMock()


class MockScreen:
    """Mock Qt screen for testing."""

    def __init__(self, x, y, width, height):
        self._geo = MockQRect(x, y, width, height)

    def availableGeometry(self):
        return self._geo


def compute_terminal_rect(gui_geo, terminal_cols, terminal_rows, screen_geo=None):
    """
    Pure function version of _compute_terminal_rect_windows for testing.

    This mirrors the logic in gui.py but without PyQt6 dependencies.
    """
    # Estimate terminal pixel size
    char_width = 8
    char_height = 16
    terminal_width = terminal_cols * char_width + 40
    terminal_height = terminal_rows * char_height + 60

    gui_right = gui_geo.x() + gui_geo.width()
    gui_top = gui_geo.y()

    # Default position: right of GUI
    x = gui_right + 10
    y = gui_top

    if screen_geo:
        screen_right = screen_geo.x() + screen_geo.width()
        screen_bottom = screen_geo.y() + screen_geo.height()

        # If terminal would go off right edge, put it on left of GUI
        if x + terminal_width > screen_right:
            x = gui_geo.x() - terminal_width - 10
            if x < screen_geo.x():
                x = screen_geo.x()

        # Clamp vertical position
        if y + terminal_height > screen_bottom:
            y = screen_bottom - terminal_height
        if y < screen_geo.y():
            y = screen_geo.y()

    return (x, y, terminal_width, terminal_height)


class TestTerminalPlacementBasic(unittest.TestCase):
    """Basic terminal placement tests."""

    def test_terminal_placed_right_of_gui(self):
        """Terminal should be placed to the right of GUI by default."""
        gui = MockQRect(100, 100, 800, 600)
        screen = MockQRect(0, 0, 1920, 1080)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Terminal should be to the right of GUI (gui_right + 10)
        self.assertEqual(x, 100 + 800 + 10)  # 910
        self.assertEqual(y, 100)  # Same top as GUI

    def test_terminal_sized_by_cols_rows(self):
        """Terminal size should be based on cols/rows."""
        gui = MockQRect(100, 100, 800, 600)
        screen = MockQRect(0, 0, 1920, 1080)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Width = 100 * 8 + 40 = 840
        # Height = 35 * 16 + 60 = 620
        self.assertEqual(w, 840)
        self.assertEqual(h, 620)


class TestTerminalPlacementEdgeCases(unittest.TestCase):
    """Edge case tests for terminal placement."""

    def test_gui_near_right_edge_terminal_placed_left(self):
        """Terminal should be placed left when GUI is near right screen edge."""
        # GUI positioned near right edge (leaves only 100px)
        gui = MockQRect(1000, 100, 800, 600)
        screen = MockQRect(0, 0, 1920, 1080)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Terminal would go off right (1810 + 840 > 1920)
        # So it should be placed on the LEFT of GUI
        expected_x = 1000 - 840 - 10  # gui.x - terminal_width - 10 = 150
        self.assertEqual(x, expected_x)

    def test_gui_near_left_edge_terminal_clamped(self):
        """Terminal should clamp to left edge when GUI is at far left."""
        # GUI at left edge
        gui = MockQRect(0, 100, 800, 600)
        screen = MockQRect(0, 0, 1000, 800)  # Small screen

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Right placement would be 810, but terminal (840px) goes off-screen
        # Left placement would be -850, which is clamped to 0
        # Since right doesn't fit and left would be negative, clamp to screen.x()
        self.assertGreaterEqual(x, 0)

    def test_vertical_clamping_bottom(self):
        """Terminal should clamp when GUI is near bottom edge."""
        # GUI positioned low
        gui = MockQRect(100, 600, 800, 400)
        screen = MockQRect(0, 0, 1920, 1080)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Terminal height = 620, bottom would be 600 + 620 = 1220 > 1080
        # Should clamp to 1080 - 620 = 460
        expected_y = 1080 - h  # 1080 - 620 = 460
        self.assertEqual(y, expected_y)

    def test_vertical_clamping_top(self):
        """Terminal should clamp when calculated position is above top edge."""
        # GUI at top, but y adjusted down might make it negative
        gui = MockQRect(100, 0, 800, 600)
        screen = MockQRect(0, 50, 1920, 1030)  # Screen starts at y=50

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # y starts at 0, but screen starts at 50
        # Should clamp to screen.y() = 50
        self.assertGreaterEqual(y, 50)


class TestMultiMonitorPlacement(unittest.TestCase):
    """Multi-monitor specific tests."""

    def test_secondary_monitor_offset(self):
        """Terminal should respect secondary monitor offset."""
        # GUI on secondary monitor (starts at x=1920)
        gui = MockQRect(2000, 100, 800, 600)
        screen = MockQRect(1920, 0, 1920, 1080)  # Secondary monitor

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Terminal should be within secondary monitor bounds
        self.assertGreaterEqual(x, 1920)
        self.assertLess(x + w, 1920 + 1920)

    def test_monitor_with_negative_coordinates(self):
        """Terminal should handle monitors with negative coordinates."""
        # Monitor to the left (negative x)
        gui = MockQRect(-1500, 100, 800, 600)
        screen = MockQRect(-1920, 0, 1920, 1080)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, screen)

        # Should stay within the negative-x monitor
        self.assertGreaterEqual(x, -1920)
        self.assertLess(x + w, 0)


class TestNoScreenInfo(unittest.TestCase):
    """Tests when screen info is unavailable."""

    def test_placement_without_screen_geometry(self):
        """Terminal should still place reasonably without screen info."""
        gui = MockQRect(100, 100, 800, 600)

        x, y, w, h = compute_terminal_rect(gui, 100, 35, None)

        # Without screen info, just place right of GUI
        self.assertEqual(x, 100 + 800 + 10)  # 910
        self.assertEqual(y, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
