# core/resources.py - SINGLE SOURCE OF TRUTH for resource resolution
"""
Centralized resource resolution with logging and validation.

All icon/asset loading MUST go through this module to ensure:
- Deterministic resolution order
- Comprehensive logging for diagnostics
- Proper validation before use
- Consistent fallback behavior

Per AGENT_ARCHITECTURE.md Section 2.5:
- Cross-platform: Windows, Linux, macOS
- No reliance on current working directory
- Path objects only
"""

import logging
import platform
import sys
from pathlib import Path
from typing import Optional, List, Tuple

# Logger for resource operations
_resources_logger = logging.getLogger('SmartDrive.resources')


# =============================================================================
# Resource Directory Resolution
# =============================================================================

def get_base_dir() -> Path:
    """
    Get the base directory for resource resolution.
    
    Handles:
    - PyInstaller bundled executables
    - Running from source
    - Deployed structure (.smartdrive/scripts/)
    
    Returns:
        Path to the launcher/project root directory
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller bundled executable
        exe_path = Path(sys.executable)
        base = exe_path.parent
        
        # If exe is in .smartdrive/scripts/, go up two levels
        if base.name == "scripts" and base.parent.name == ".smartdrive":
            base = base.parent.parent
        
        _resources_logger.debug(f"Resource base (frozen): {base}")
        return base
    else:
        # Running from source
        # __file__ is core/resources.py, so go up to .smartdrive, then to root
        module_path = Path(__file__).resolve()
        
        # core/resources.py -> core -> .smartdrive -> ROOT
        if module_path.parent.name == "core":
            base = module_path.parent.parent.parent
        else:
            base = module_path.parent
        
        _resources_logger.debug(f"Resource base (source): {base}")
        return base


def get_static_dir(launcher_root: Optional[Path] = None) -> Path:
    """
    Get the static assets directory with priority resolution.
    
    Priority order:
    1. .smartdrive/static/ (deployed structure)
    2. ROOT/static/ (legacy/dev structure)
    
    Args:
        launcher_root: Optional explicit root path. If None, auto-detected.
    
    Returns:
        Path to the static directory (may not exist)
    """
    if launcher_root is None:
        launcher_root = get_base_dir()
    
    # Primary: .smartdrive/static/
    primary = launcher_root / ".smartdrive" / "static"
    if primary.exists():
        _resources_logger.debug(f"Static dir (primary): {primary}")
        return primary
    
    # Legacy: ROOT/static/
    legacy = launcher_root / "static"
    if legacy.exists():
        _resources_logger.debug(f"Static dir (legacy): {legacy}")
        return legacy
    
    # Default to primary
    _resources_logger.debug(f"Static dir (default): {primary}")
    return primary


# =============================================================================
# Icon Resolution
# =============================================================================

def get_icon_candidates(
    filename: str,
    launcher_root: Optional[Path] = None,
    include_png_fallback: bool = True
) -> List[Path]:
    """
    Get ordered list of candidate paths for an icon file.
    
    Args:
        filename: Icon filename (e.g., "LOGO_main.ico")
        launcher_root: Optional explicit root path
        include_png_fallback: If True and filename is .ico, also try .png
    
    Returns:
        Ordered list of candidate paths to try
    """
    if launcher_root is None:
        launcher_root = get_base_dir()
    
    candidates: List[Path] = []
    
    # Primary: .smartdrive/static/
    primary_dir = launcher_root / ".smartdrive" / "static"
    candidates.append(primary_dir / filename)
    
    # Legacy: ROOT/static/
    legacy_dir = launcher_root / "static"
    candidates.append(legacy_dir / filename)
    
    # PyInstaller bundled location
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundled = Path(sys._MEIPASS) / "static"
        candidates.append(bundled / filename)
    
    # Add PNG fallback for .ico files (cross-platform)
    if include_png_fallback and filename.lower().endswith('.ico'):
        png_filename = filename[:-4] + ".png"
        for base in [primary_dir, legacy_dir]:
            candidates.append(base / png_filename)
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            candidates.append(Path(sys._MEIPASS) / "static" / png_filename)
    
    return candidates


def resolve_icon_path(
    filename: str,
    launcher_root: Optional[Path] = None,
    log_resolution: bool = True
) -> Optional[Path]:
    """
    Resolve icon path with full logging and validation.
    
    Args:
        filename: Icon filename (e.g., "LOGO_main.ico")
        launcher_root: Optional explicit root path
        log_resolution: If True, log all resolution steps
    
    Returns:
        Path to existing icon file, or None if not found
    """
    candidates = get_icon_candidates(filename, launcher_root)
    
    if log_resolution:
        _resources_logger.info(f"Resolving icon: {filename}")
        _resources_logger.debug(f"  Base dir: {launcher_root or get_base_dir()}")
        _resources_logger.debug(f"  Candidates: {len(candidates)}")
    
    for i, candidate in enumerate(candidates):
        exists = candidate.exists()
        
        if log_resolution:
            status = "✓ EXISTS" if exists else "✗ missing"
            size_info = ""
            if exists:
                try:
                    size = candidate.stat().st_size
                    size_info = f" ({size} bytes)"
                except OSError:
                    size_info = " (size unknown)"
            _resources_logger.debug(f"  [{i+1}] {candidate}: {status}{size_info}")
        
        if exists:
            if log_resolution:
                _resources_logger.info(f"  → Selected: {candidate}")
            return candidate
    
    if log_resolution:
        _resources_logger.warning(f"  → No valid icon found for: {filename}")
    
    return None


def validate_qicon(icon_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Validate that a QIcon can be loaded from the given path.
    
    Args:
        icon_path: Path to icon file
    
    Returns:
        Tuple of (is_valid, error_message)
        is_valid is True if icon loaded successfully
        error_message is None on success, or error description on failure
    """
    try:
        from PyQt6.QtGui import QIcon
        
        icon = QIcon(str(icon_path))
        is_null = icon.isNull()
        
        _resources_logger.debug(f"QIcon validation: path={icon_path}, isNull={is_null}")
        
        if is_null:
            return False, f"QIcon.isNull() returned True for: {icon_path}"
        
        return True, None
        
    except ImportError:
        return False, "PyQt6 not available for QIcon validation"
    except Exception as e:
        return False, f"QIcon load error: {e}"


def get_app_icon_path(
    launcher_root: Optional[Path] = None,
    prefer_ico: bool = True
) -> Optional[Path]:
    """
    Get the main application icon path.
    
    This is the primary icon used for:
    - Window icon
    - Taskbar icon
    - Tray icon (unmounted state)
    
    Args:
        launcher_root: Optional explicit root path
        prefer_ico: If True, prefer .ico files on Windows
    
    Returns:
        Path to main app icon, or None if not found
    """
    system = platform.system().lower()
    
    # On Windows, prefer .ico
    if "windows" in system and prefer_ico:
        icon_path = resolve_icon_path("LOGO_main.ico", launcher_root)
        if icon_path:
            return icon_path
    
    # Try PNG (works everywhere)
    icon_path = resolve_icon_path("LOGO_main.png", launcher_root)
    if icon_path:
        return icon_path
    
    # Fallback to .ico even on non-Windows
    icon_path = resolve_icon_path("LOGO_main.ico", launcher_root)
    return icon_path


def get_mounted_icon_path(launcher_root: Optional[Path] = None) -> Optional[Path]:
    """
    Get the mounted state icon path.
    
    Args:
        launcher_root: Optional explicit root path
    
    Returns:
        Path to mounted icon, or None if not found
    """
    system = platform.system().lower()
    
    # On Windows, prefer .ico
    if "windows" in system:
        icon_path = resolve_icon_path("LOGO_mounted.ico", launcher_root)
        if icon_path:
            return icon_path
    
    # Try PNG
    icon_path = resolve_icon_path("LOGO_mounted.png", launcher_root)
    if icon_path:
        return icon_path
    
    # Fallback to .ico
    return resolve_icon_path("LOGO_mounted.ico", launcher_root)


def get_unmounted_icon_path(launcher_root: Optional[Path] = None) -> Optional[Path]:
    """
    Get the unmounted state icon path.
    
    Note: Uses LOGO_main as the unmounted/default icon.
    
    Args:
        launcher_root: Optional explicit root path
    
    Returns:
        Path to unmounted icon, or None if not found
    """
    # Unmounted = main/default icon
    return get_app_icon_path(launcher_root)


# =============================================================================
# Theme-Aware Icon Resolution (SSOT)
# =============================================================================

def get_logo_main_ico(
    theme: Optional[str] = None,
    launcher_root: Optional[Path] = None
) -> Optional[Path]:
    """
    SSOT: Get main logo .ico with optional theme suffix.
    
    Resolution order:
    1. LOGO_main_{theme}.ico (if theme specified)
    2. LOGO_main.ico (default fallback)
    
    Args:
        theme: Optional theme name (e.g., "dark", "light")
        launcher_root: Optional explicit root path
    
    Returns:
        Path to icon file, or None if not found
    
    Examples:
        get_logo_main_ico("dark") -> .smartdrive/static/LOGO_main_dark.ico
        get_logo_main_ico()       -> .smartdrive/static/LOGO_main.ico
    """
    # Try theme-specific first
    if theme:
        themed_filename = f"LOGO_main_{theme}.ico"
        _resources_logger.debug(f"icon.resolve.theme: trying {themed_filename}")
        themed_path = resolve_icon_path(themed_filename, launcher_root, log_resolution=False)
        if themed_path:
            _resources_logger.info(f"icon.resolve.theme.found: {themed_filename} -> {themed_path}")
            return themed_path
        _resources_logger.debug(f"icon.resolve.theme.fallback: {themed_filename} not found, using default")
    
    # Fallback to default
    default_path = resolve_icon_path("LOGO_main.ico", launcher_root, log_resolution=False)
    if default_path:
        _resources_logger.info(f"icon.resolve.default.found: LOGO_main.ico -> {default_path}")
    else:
        _resources_logger.warning("icon.resolve.default.notfound: LOGO_main.ico not found")
    
    return default_path


def get_logo_main_png(
    theme: Optional[str] = None,
    launcher_root: Optional[Path] = None
) -> Optional[Path]:
    """
    SSOT: Get main logo .png with optional theme suffix.
    
    Resolution order:
    1. LOGO_main_{theme}.png (if theme specified)
    2. LOGO_main.png (default fallback)
    
    Args:
        theme: Optional theme name (e.g., "dark", "light")
        launcher_root: Optional explicit root path
    
    Returns:
        Path to icon file, or None if not found
    
    Examples:
        get_logo_main_png("dark") -> .smartdrive/static/LOGO_main_dark.png
        get_logo_main_png()       -> .smartdrive/static/LOGO_main.png
    """
    # Try theme-specific first
    if theme:
        themed_filename = f"LOGO_main_{theme}.png"
        _resources_logger.debug(f"icon.resolve.theme: trying {themed_filename}")
        themed_path = resolve_icon_path(themed_filename, launcher_root, log_resolution=False)
        if themed_path:
            _resources_logger.info(f"icon.resolve.theme.found: {themed_filename} -> {themed_path}")
            return themed_path
        _resources_logger.debug(f"icon.resolve.theme.fallback: {themed_filename} not found, using default")
    
    # Fallback to default
    default_path = resolve_icon_path("LOGO_main.png", launcher_root, log_resolution=False)
    if default_path:
        _resources_logger.info(f"icon.resolve.default.found: LOGO_main.png -> {default_path}")
    else:
        _resources_logger.warning("icon.resolve.default.notfound: LOGO_main.png not found")
    
    return default_path


def get_logo_for_platform(
    theme: Optional[str] = None,
    launcher_root: Optional[Path] = None,
    prefer_ico: bool = True
) -> Optional[Path]:
    """
    SSOT: Get main logo with theme support, platform-appropriate format.
    
    On Windows: prefers .ico
    On macOS/Linux: prefers .png
    
    Args:
        theme: Optional theme name (e.g., "dark", "light")
        launcher_root: Optional explicit root path
        prefer_ico: If True, prefer .ico on Windows
    
    Returns:
        Path to icon file, or None if not found
    """
    system = platform.system().lower()
    
    if "windows" in system and prefer_ico:
        # Try ICO first on Windows
        ico_path = get_logo_main_ico(theme, launcher_root)
        if ico_path:
            return ico_path
        # Fall back to PNG
        return get_logo_main_png(theme, launcher_root)
    else:
        # Try PNG first on non-Windows
        png_path = get_logo_main_png(theme, launcher_root)
        if png_path:
            return png_path
        # Fall back to ICO
        return get_logo_main_ico(theme, launcher_root)


# =============================================================================
# Logging Helpers
# =============================================================================

def log_resource_diagnostics(launcher_root: Optional[Path] = None) -> None:
    """
    Log comprehensive resource resolution diagnostics.
    
    Call this at startup or when --diagnose flag is used.
    """
    base = launcher_root or get_base_dir()
    
    _resources_logger.info("=" * 60)
    _resources_logger.info("RESOURCE DIAGNOSTICS")
    _resources_logger.info("=" * 60)
    _resources_logger.info(f"Platform: {platform.system()}")
    _resources_logger.info(f"Frozen (PyInstaller): {getattr(sys, 'frozen', False)}")
    _resources_logger.info(f"Base directory: {base}")
    _resources_logger.info(f"Base exists: {base.exists()}")
    
    # Static directory
    static = get_static_dir(base)
    _resources_logger.info(f"Static directory: {static}")
    _resources_logger.info(f"Static exists: {static.exists()}")
    
    if static.exists():
        try:
            files = list(static.iterdir())
            _resources_logger.info(f"Static contents ({len(files)} files):")
            for f in sorted(files):
                _resources_logger.info(f"  - {f.name}")
        except OSError as e:
            _resources_logger.warning(f"Cannot list static dir: {e}")
    
    # Icon resolution
    _resources_logger.info("-" * 40)
    _resources_logger.info("Icon resolution:")
    
    main_icon = get_app_icon_path(base)
    _resources_logger.info(f"  Main icon: {main_icon}")
    if main_icon:
        valid, err = validate_qicon(main_icon)
        _resources_logger.info(f"  Main QIcon valid: {valid}")
        if err:
            _resources_logger.warning(f"  QIcon error: {err}")
    
    mounted_icon = get_mounted_icon_path(base)
    _resources_logger.info(f"  Mounted icon: {mounted_icon}")
    
    unmounted_icon = get_unmounted_icon_path(base)
    _resources_logger.info(f"  Unmounted icon: {unmounted_icon}")
    
    _resources_logger.info("=" * 60)


def check_tray_icon_requirements(icon_path: Optional[Path]) -> Tuple[bool, List[str]]:
    """
    Verify all requirements for tray icon are met.
    
    Note: Some checks require QApplication to exist. If no QApplication exists,
    those checks are skipped with a warning.
    
    Returns:
        Tuple of (all_ok, list_of_issues)
    """
    issues: List[str] = []
    
    # Check icon path
    if icon_path is None:
        issues.append("No icon path provided")
    elif not icon_path.exists():
        issues.append(f"Icon file does not exist: {icon_path}")
    else:
        # Validate QIcon only if QApplication exists
        try:
            from PyQt6.QtWidgets import QApplication
            if QApplication.instance():
                valid, err = validate_qicon(icon_path)
                if not valid:
                    issues.append(f"QIcon validation failed: {err}")
            else:
                _resources_logger.debug("Skipping QIcon validation (no QApplication)")
        except ImportError:
            pass  # PyQt6 not available
    
    # Check tray availability only if QApplication exists
    try:
        from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
        if QApplication.instance():
            if not QSystemTrayIcon.isSystemTrayAvailable():
                issues.append("System tray not available")
        else:
            _resources_logger.debug("Skipping tray availability check (no QApplication)")
    except ImportError:
        issues.append("PyQt6 not available")
    except Exception as e:
        _resources_logger.debug(f"Tray availability check error: {e}")
    
    return len(issues) == 0, issues
