# core/tray.py - System tray icon management
"""
Cross-platform system tray icon support.

Provides per-drive tray icons with:
- Unique tooltip per drive (nickname + drive_id short form)
- Context menu with Open, Quit actions
- Close-to-tray behavior integration

Per AGENT_ARCHITECTURE.md Section 2.5:
- Cross-platform: Windows, Linux, macOS
- Consistent UX across platforms
"""

import logging
import platform
from pathlib import Path
from typing import Callable, Optional

# Logger for tray operations
_tray_logger = logging.getLogger("SmartDrive.tray")


# =============================================================================
# Tray Icon Manager
# =============================================================================


class TrayIconManager:
    """
    Manages system tray icon for a drive.

    Creates a tray icon with:
    - Drive-specific tooltip
    - Context menu: Open, Quit
    - Integration with close-to-tray behavior

    Usage:
        tray = TrayIconManager(
            drive_id="abc123...",
            drive_name="My Drive",
            on_open=show_window,
            on_quit=quit_app,
            icon_path=Path("icon.ico")
        )
        tray.show()
    """

    def __init__(
        self,
        drive_id: str,
        drive_name: Optional[str] = None,
        on_open: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        icon_path: Optional[Path] = None,
        parent=None,
    ):
        """
        Initialize tray icon manager.

        Args:
            drive_id: UUIDv4 drive identifier
            drive_name: Human-readable drive name/nickname
            on_open: Callback for "Open" menu action
            on_quit: Callback for "Quit" menu action
            icon_path: Path to icon file (ico/png)
            parent: Parent QWidget (for Qt integration)
        """
        self.drive_id = drive_id
        self.drive_name = drive_name or "KeyDrive"
        self.on_open = on_open
        self.on_quit = on_quit
        self.icon_path = icon_path
        self.parent = parent

        self._tray_icon = None
        self._menu = None
        self._is_visible = False

        # Generate tooltip with drive identification
        short_id = drive_id[:8] if drive_id else ""
        self.tooltip = f"{self.drive_name}"
        if short_id:
            self.tooltip += f" ({short_id})"

        _tray_logger.info(f"TrayIconManager initialized: {self.tooltip}")

    def _create_tray_icon(self) -> bool:
        """
        Create the system tray icon.

        Returns:
            True if created successfully, False otherwise
        """
        try:
            from PyQt6.QtGui import QAction, QIcon
            from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

            # Log tray availability
            is_available = QSystemTrayIcon.isSystemTrayAvailable()
            _tray_logger.info(f"System tray available: {is_available}")

            if not is_available:
                _tray_logger.warning("System tray not available on this platform")
                return False

            # Create tray icon
            self._tray_icon = QSystemTrayIcon(self.parent)

            # Resolve and set icon with comprehensive logging
            icon = None
            icon_source = "none"

            if self.icon_path:
                _tray_logger.info(f"Tray icon path provided: {self.icon_path}")
                _tray_logger.info(f"  Path exists: {self.icon_path.exists()}")

                if self.icon_path.exists():
                    try:
                        file_size = self.icon_path.stat().st_size
                        _tray_logger.info(f"  File size: {file_size} bytes")
                    except OSError as e:
                        _tray_logger.warning(f"  Cannot stat file: {e}")

                    icon = QIcon(str(self.icon_path))
                    icon_source = str(self.icon_path)
                else:
                    _tray_logger.warning(f"Tray icon path does not exist: {self.icon_path}")

            # Fallback to application icon
            if icon is None or icon.isNull():
                _tray_logger.info("Falling back to application window icon")
                app = QApplication.instance()
                if app:
                    app_icon = app.windowIcon()
                    if not app_icon.isNull():
                        icon = app_icon
                        icon_source = "app.windowIcon()"
                        _tray_logger.info("Using application window icon")
                    else:
                        _tray_logger.warning("Application window icon is also null")

            # BUG-20251220-008 FIX: Ultimate fallback to Qt built-in icon
            # Windows requires a valid icon for system tray to display
            if icon is None or icon.isNull():
                _tray_logger.info("Falling back to Qt built-in icon (SP_DriveHDIcon)")
                try:
                    from PyQt6.QtWidgets import QStyle

                    app = QApplication.instance()
                    if app:
                        style = app.style()
                        if style:
                            icon = style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
                            icon_source = "QStyle.SP_DriveHDIcon"
                            _tray_logger.info("Using Qt built-in SP_DriveHDIcon")
                except Exception as e:
                    _tray_logger.warning(f"Failed to get built-in icon: {e}")

            # Log final icon state
            if icon:
                is_null = icon.isNull()
                _tray_logger.info(f"Tray icon source: {icon_source}")
                _tray_logger.info(f"Tray icon isNull: {is_null}")

                if is_null:
                    _tray_logger.error("CRITICAL: Tray icon is NULL - tray will fail to display")
                    # BUG-20251220-008: Return False to indicate failure rather than continuing with NULL icon
                    return False

                self._tray_icon.setIcon(icon)
            else:
                _tray_logger.error("CRITICAL: No icon available for tray - cannot display")
                return False

            # Set tooltip
            self._tray_icon.setToolTip(self.tooltip)
            _tray_logger.debug(f"Tray tooltip set: {self.tooltip}")

            # Create context menu
            self._menu = QMenu()

            # Open action
            open_action = QAction("Open", self._menu)
            open_action.triggered.connect(self._on_open_triggered)
            self._menu.addAction(open_action)

            # Separator
            self._menu.addSeparator()

            # Quit action
            quit_action = QAction("Quit", self._menu)
            quit_action.triggered.connect(self._on_quit_triggered)
            self._menu.addAction(quit_action)

            self._tray_icon.setContextMenu(self._menu)

            # Connect activation signal (double-click on Windows, single-click varies)
            self._tray_icon.activated.connect(self._on_activated)

            _tray_logger.info("Tray icon created successfully")
            return True

        except ImportError:
            _tray_logger.error("PyQt6 not available, cannot create tray icon")
            return False
        except Exception as e:
            _tray_logger.error(f"Failed to create tray icon: {e}")
            return False

    def _on_open_triggered(self) -> None:
        """Handle Open menu action."""
        _tray_logger.debug("Tray menu: Open triggered")
        if self.on_open:
            self.on_open()

    def _on_quit_triggered(self) -> None:
        """Handle Quit menu action."""
        _tray_logger.debug("Tray menu: Quit triggered")
        if self.on_quit:
            self.on_quit()

    def _on_activated(self, reason) -> None:
        """
        Handle tray icon activation (click/double-click).

        On Windows: double-click opens
        On Linux/macOS: single-click typically opens
        """
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon

            # Trigger is typically double-click on Windows, varies on other platforms
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                _tray_logger.debug("Tray icon activated (trigger)")
                if self.on_open:
                    self.on_open()
            elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                _tray_logger.debug("Tray icon activated (double-click)")
                if self.on_open:
                    self.on_open()
        except Exception as e:
            _tray_logger.warning(f"Tray activation error: {e}")

    def show(self) -> bool:
        """
        Show the tray icon.

        Creates the icon if not already created.

        Returns:
            True if shown successfully, False otherwise
        """
        _tray_logger.info("Tray show() called")

        if not self._tray_icon:
            _tray_logger.debug("Creating tray icon...")
            if not self._create_tray_icon():
                _tray_logger.error("Failed to create tray icon")
                return False

        # Verify icon is set before showing
        try:
            current_icon = self._tray_icon.icon()
            if current_icon.isNull():
                _tray_logger.error("CRITICAL: About to call show() but icon is NULL")
                _tray_logger.error("This will cause 'QSystemTrayIcon::setVisible: No Icon set' warning")
        except Exception as e:
            _tray_logger.warning(f"Could not verify icon state: {e}")

        self._tray_icon.show()
        self._is_visible = True
        _tray_logger.info(f"Tray icon show() executed: {self.tooltip}")
        return True

    def hide(self) -> None:
        """Hide the tray icon."""
        if self._tray_icon:
            self._tray_icon.hide()
            self._is_visible = False
            _tray_logger.info("Tray icon hidden")

    def set_icon(self, icon_path: Path) -> None:
        """
        Update the tray icon image.

        Args:
            icon_path: Path to new icon file
        """
        if not self._tray_icon:
            return

        try:
            from PyQt6.QtGui import QIcon

            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self._tray_icon.setIcon(icon)
                self.icon_path = icon_path
                _tray_logger.debug(f"Tray icon updated: {icon_path}")
        except Exception as e:
            _tray_logger.warning(f"Failed to update tray icon: {e}")

    def set_tooltip(self, tooltip: str) -> None:
        """
        Update the tray icon tooltip.

        Args:
            tooltip: New tooltip text
        """
        self.tooltip = tooltip
        if self._tray_icon:
            self._tray_icon.setToolTip(tooltip)
            _tray_logger.debug(f"Tray tooltip updated: {tooltip}")

    def show_message(self, title: str, message: str, icon_type: str = "information", duration_ms: int = 5000) -> None:
        """
        Show a tray notification message.

        Args:
            title: Notification title
            message: Notification body
            icon_type: One of "information", "warning", "critical"
            duration_ms: Duration to show (platform-dependent)
        """
        if not self._tray_icon:
            return

        try:
            from PyQt6.QtWidgets import QSystemTrayIcon

            icon_map = {
                "information": QSystemTrayIcon.MessageIcon.Information,
                "warning": QSystemTrayIcon.MessageIcon.Warning,
                "critical": QSystemTrayIcon.MessageIcon.Critical,
            }

            msg_icon = icon_map.get(icon_type, QSystemTrayIcon.MessageIcon.Information)
            self._tray_icon.showMessage(title, message, msg_icon, duration_ms)
            _tray_logger.debug(f"Tray message shown: {title}")
        except Exception as e:
            _tray_logger.warning(f"Failed to show tray message: {e}")

    def cleanup(self) -> None:
        """Clean up tray icon resources."""
        self.hide()
        if self._tray_icon:
            self._tray_icon.deleteLater()
            self._tray_icon = None
        if self._menu:
            self._menu.deleteLater()
            self._menu = None
        _tray_logger.info("Tray icon cleaned up")

    @property
    def is_visible(self) -> bool:
        """Check if tray icon is currently visible."""
        return self._is_visible


def is_tray_available() -> bool:
    """
    Check if system tray is available on this platform.

    Returns:
        True if system tray is available, False otherwise
    """
    try:
        from PyQt6.QtWidgets import QSystemTrayIcon

        return QSystemTrayIcon.isSystemTrayAvailable()
    except ImportError:
        return False
