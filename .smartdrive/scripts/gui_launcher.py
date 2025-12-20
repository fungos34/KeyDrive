#!/usr/bin/env python3
"""
SmartDrive GUI Launcher
=======================

Simple launcher for the SmartDrive GUI application.
This script can be bundled into an executable using PyInstaller.

Usage:
    python gui_launcher.py
    # or bundled: SmartDriveWindows.exe
"""

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Add project root and scripts directory to Python path
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
from core.paths import Paths
if _script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
    # Deployed on drive: .smartdrive/scripts/gui_launcher.py
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/gui_launcher.py at repo root
    _project_root = _script_dir.parent
    _deploy_root = None

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# ============================================================
# GLOBAL EXCEPTION HANDLING AND LOGGING
# ============================================================


def setup_logging(launcher_root: Path) -> logging.Logger:
    """
    Set up rotating log file for GUI exceptions.

    Args:
        launcher_root: Root directory (drive root or repo root)

    Returns:
        Configured logger instance
    """
    from core.paths import Paths

    log_dir = Paths.logs_dir(launcher_root)
    log_file = Paths.gui_log_file(launcher_root)

    # Create logs directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    # Configure rotating file handler (5MB max, 3 backups)
    handler = RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")  # 5MB
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    # Configure root logger
    logger = logging.getLogger("SmartDriveGUI")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    # Also log to stderr for debugging
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stderr_handler)

    return logger


def create_exception_hook(logger: logging.Logger):
    """
    Create a global exception hook that logs unhandled exceptions.

    Args:
        logger: Logger instance for writing exceptions

    Returns:
        Exception hook function
    """

    def exception_hook(exc_type, exc_value, exc_traceback):
        """Global exception handler that logs and displays errors."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Allow Ctrl+C to exit normally
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # Log the exception
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

        # Format the traceback for display
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        tb_text = "".join(tb_lines)

        # Print to stderr
        print(f"❌ FATAL ERROR:\n{tb_text}", file=sys.stderr)

        # Try to show a GUI error dialog
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Critical)
                msg.setWindowTitle("SmartDrive Error")
                msg.setText(f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}")
                msg.setDetailedText(tb_text)
                msg.exec()
        except Exception:
            pass  # If Qt isn't available, we've already logged to stderr

    return exception_hook


def qt_message_handler(msg_type, context, message):
    """
    Qt message handler that captures Qt warnings/errors to the log.

    Args:
        msg_type: Qt message type (QtDebugMsg, QtWarningMsg, etc.)
        context: Context information (file, line, function)
        message: The actual message
    """
    from PyQt6.QtCore import QtMsgType

    logger = logging.getLogger("SmartDriveGUI.Qt")

    if msg_type == QtMsgType.QtDebugMsg:
        logger.debug(f"Qt: {message}")
    elif msg_type == QtMsgType.QtInfoMsg:
        logger.info(f"Qt: {message}")
    elif msg_type == QtMsgType.QtWarningMsg:
        logger.warning(f"Qt: {message}")
    elif msg_type == QtMsgType.QtCriticalMsg:
        logger.error(f"Qt: {message}")
    elif msg_type == QtMsgType.QtFatalMsg:
        logger.critical(f"Qt FATAL: {message}")


# ============================================================
# MAIN ENTRY POINT
# ============================================================

# Set up logging as early as possible
_launcher_root = _project_root
_logger = setup_logging(_launcher_root)

# Install global exception hook
sys.excepthook = create_exception_hook(_logger)

# Install Qt message handler
try:
    from PyQt6.QtCore import qInstallMessageHandler

    qInstallMessageHandler(qt_message_handler)
except ImportError:
    _logger.warning("PyQt6 not available, Qt message handler not installed")

_logger.info("SmartDrive GUI Launcher starting...")
_logger.info(f"Launcher root: {_launcher_root}")
_logger.info(f"Python version: {sys.version}")

# Import and run the GUI
try:
    from gui import main

    main()
except ImportError as e:
    _logger.error(f"Failed to import GUI module: {e}")
    print(f"❌ Failed to import GUI module: {e}")
    print("Make sure PyQt6 is installed: pip install PyQt6 PyQt6-Qt6")
    input("Press Enter to exit...")
    sys.exit(1)
except Exception as e:
    _logger.critical(f"GUI Error: {e}", exc_info=True)
    print(f"❌ GUI Error: {e}")
    traceback.print_exc()
    input("Press Enter to exit...")
    sys.exit(1)
