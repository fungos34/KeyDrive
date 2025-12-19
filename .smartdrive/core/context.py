# core/context.py - SINGLE SOURCE OF TRUTH for runtime context
"""
RuntimeContext provides a unified context that flows through all operations.

This module solves the "run from anywhere" problem by ensuring:
1. Target drive identity is captured once and propagated everywhere
2. No script guesses paths based on cwd or __file__
3. All subprocess calls receive explicit --config paths

RULES:
- RuntimeContext is created ONCE at the start of any operation
- All subprocess invocations must pass --config explicitly
- No implicit path resolution based on cwd

Usage:
    from core.context import RuntimeContext, create_context_from_config
    from core.paths import Paths
    
    # Create from explicit config path
    drive_root = Path("G:\\")
    ctx = create_context_from_config(Paths.config_file(drive_root))
    
    # Or detect from script location (for initial entry points only)
    ctx = RuntimeContext.from_script_location(Path(__file__))
    
    # Pass to subprocess
    subprocess.run([sys.executable, "mount.py", "--config", str(ctx.config_path)])
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import platform
import json
import logging

_context_logger = logging.getLogger("smartdrive.context")


@dataclass
class RuntimeContext:
    """
    Unified runtime context for all SmartDrive operations.
    
    This is the SINGLE SOURCE OF TRUTH for:
    - Where the drive is located (drive_root)
    - Where SmartDrive data lives (.smartdrive/)
    - Where config is stored
    - What disk/volume we're operating on (Windows identifiers)
    
    All scripts must receive this context explicitly - no guessing.
    """
    
    # Core paths (ALWAYS absolute Path objects)
    drive_root: Path  # E.g., "G:\" or "/media/user/SMARTDRIVE"
    smartdrive_dir: Path  # E.g., "G:\.smartdrive" 
    config_path: Path  # E.g., "G:\.smartdrive\config.json"
    
    # Windows-specific disk identifiers (for partitioning/volume operations)
    disk_number: Optional[int] = None  # Windows disk number (0, 1, 2...)
    disk_unique_id: Optional[str] = None  # GUID or serial for persistent identification
    
    # Cached config data (loaded lazily)
    _config_cache: Optional[Dict[str, Any]] = field(default=None, repr=False)
    
    def __post_init__(self):
        """Validate and normalize paths."""
        # Ensure all paths are absolute
        if not self.drive_root.is_absolute():
            raise ValueError(f"drive_root must be absolute: {self.drive_root}")
        if not self.smartdrive_dir.is_absolute():
            raise ValueError(f"smartdrive_dir must be absolute: {self.smartdrive_dir}")
        if not self.config_path.is_absolute():
            raise ValueError(f"config_path must be absolute: {self.config_path}")
        
        # Resolve to canonical paths
        self.drive_root = self.drive_root.resolve()
        self.smartdrive_dir = self.smartdrive_dir.resolve()
        self.config_path = self.config_path.resolve()
        
        _context_logger.debug(
            f"RuntimeContext created: drive_root={self.drive_root}, "
            f"config_path={self.config_path}"
        )
    
    # =========================================================================
    # Factory methods
    # =========================================================================
    
    @classmethod
    def from_config_path(cls, config_path: Path) -> "RuntimeContext":
        """
        Create context from an explicit config.json path.
        
        This is the PREFERRED factory method when --config is provided.
        
        Args:
            config_path: Absolute path to config.json
            
        Returns:
            RuntimeContext with paths derived from config location
        """
        config_path = Path(config_path).resolve()
        
        if not config_path.is_absolute():
            raise ValueError(f"config_path must be absolute: {config_path}")
        
        # Config is at .smartdrive/config.json
        # So smartdrive_dir = config_path.parent
        # And drive_root = smartdrive_dir.parent
        smartdrive_dir = config_path.parent
        drive_root = smartdrive_dir.parent
        
        # Validate structure
        if smartdrive_dir.name != ".smartdrive":
            _context_logger.warning(
                f"Config parent is not .smartdrive: {smartdrive_dir.name}"
            )
        
        return cls(
            drive_root=drive_root,
            smartdrive_dir=smartdrive_dir,
            config_path=config_path
        )
    
    @classmethod
    def from_drive_root(cls, drive_root: Path) -> "RuntimeContext":
        """
        Create context from a drive root path.
        
        Args:
            drive_root: Absolute path to drive root (e.g., "G:\")
            
        Returns:
            RuntimeContext with standard .smartdrive structure
        """
        drive_root = Path(drive_root).resolve()
        
        if not drive_root.is_absolute():
            raise ValueError(f"drive_root must be absolute: {drive_root}")
        
        smartdrive_dir = drive_root / ".smartdrive"
        config_path = smartdrive_dir / "config.json"
        
        return cls(
            drive_root=drive_root,
            smartdrive_dir=smartdrive_dir,
            config_path=config_path
        )
    
    @classmethod
    def from_script_location(cls, script_path: Path) -> "RuntimeContext":
        """
        Infer context from a script's __file__ location.
        
        This is for INITIAL ENTRY POINTS ONLY (e.g., smartdrive.py launched directly).
        Subprocess calls should use --config instead.
        
        Args:
            script_path: Path(__file__) from the calling script
            
        Returns:
            RuntimeContext inferred from script location
        """
        script_path = Path(script_path).resolve()
        script_dir = script_path.parent
        
        # Detect if we're in deployed structure (.smartdrive/scripts/)
        # or development structure (scripts/ at repo root)
        if script_dir.parent.name == ".smartdrive":
            # Deployed: .smartdrive/scripts/foo.py
            smartdrive_dir = script_dir.parent
            drive_root = smartdrive_dir.parent
        else:
            # Development: check if .smartdrive exists
            potential_root = script_dir.parent
            if (potential_root / ".smartdrive").exists():
                # Dev with .smartdrive structure
                smartdrive_dir = potential_root / ".smartdrive"
                drive_root = potential_root
            else:
                # Legacy structure (scripts/ at root)
                smartdrive_dir = potential_root / ".smartdrive"
                drive_root = potential_root
        
        config_path = smartdrive_dir / "config.json"
        
        _context_logger.debug(
            f"Inferred context from {script_path}: "
            f"drive_root={drive_root}, config={config_path}"
        )
        
        return cls(
            drive_root=drive_root,
            smartdrive_dir=smartdrive_dir,
            config_path=config_path
        )
    
    # =========================================================================
    # Derived paths (computed from core paths)
    # =========================================================================
    
    @property
    def scripts_dir(self) -> Path:
        """Return .smartdrive/scripts/ path."""
        return self.smartdrive_dir / "scripts"
    
    @property
    def keys_dir(self) -> Path:
        """Return .smartdrive/keys/ path."""
        return self.smartdrive_dir / "keys"
    
    @property
    def static_dir(self) -> Path:
        """Return static assets directory (checks both locations)."""
        # Primary: .smartdrive/static/
        primary = self.smartdrive_dir / "static"
        if primary.exists():
            return primary
        # Fallback: ROOT/static/ (legacy)
        legacy = self.drive_root / "static"
        if legacy.exists():
            return legacy
        return primary  # Default to primary even if not exists
    
    @property
    def logs_dir(self) -> Path:
        """Return .smartdrive/logs/ path."""
        return self.smartdrive_dir / "logs"
    
    @property
    def integrity_dir(self) -> Path:
        """Return .smartdrive/integrity/ path."""
        return self.smartdrive_dir / "integrity"
    
    @property
    def recovery_dir(self) -> Path:
        """Return .smartdrive/recovery/ path."""
        return self.smartdrive_dir / "recovery"
    
    # =========================================================================
    # Config access
    # =========================================================================
    
    def load_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Load config.json with caching.
        
        Args:
            force_reload: If True, bypass cache and reload from disk
            
        Returns:
            Config dictionary
            
        Raises:
            FileNotFoundError: If config doesn't exist
            json.JSONDecodeError: If config is invalid JSON
        """
        if self._config_cache is None or force_reload:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Config not found: {self.config_path}")
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config_cache = json.load(f)
            
            _context_logger.debug(f"Loaded config from {self.config_path}")
        
        return self._config_cache
    
    def config_exists(self) -> bool:
        """Check if config.json exists."""
        return self.config_path.exists()
    
    # =========================================================================
    # Subprocess helpers
    # =========================================================================
    
    def get_subprocess_args(self) -> list:
        """
        Return args to pass to subprocess for context propagation.
        
        Usage:
            subprocess.run([sys.executable, "mount.py"] + ctx.get_subprocess_args())
        """
        return ["--config", str(self.config_path)]
    
    def script_path(self, script_name: str) -> Path:
        """Return full path to a script in .smartdrive/scripts/."""
        return self.scripts_dir / script_name
    
    # =========================================================================
    # Diagnostic logging
    # =========================================================================
    
    def log_diagnostic_snapshot(self) -> None:
        """
        Log comprehensive diagnostic information about this context.
        
        Call this before mount operations for troubleshooting.
        """
        _context_logger.info("=" * 60)
        _context_logger.info("RUNTIME CONTEXT DIAGNOSTIC SNAPSHOT")
        _context_logger.info("=" * 60)
        _context_logger.info(f"drive_root:      {self.drive_root}")
        _context_logger.info(f"smartdrive_dir:  {self.smartdrive_dir}")
        _context_logger.info(f"config_path:     {self.config_path}")
        _context_logger.info(f"config_exists:   {self.config_exists()}")
        _context_logger.info(f"scripts_dir:     {self.scripts_dir}")
        _context_logger.info(f"scripts_exists:  {self.scripts_dir.exists()}")
        _context_logger.info(f"static_dir:      {self.static_dir}")
        _context_logger.info(f"static_exists:   {self.static_dir.exists()}")
        
        if self.disk_number is not None:
            _context_logger.info(f"disk_number:     {self.disk_number}")
        if self.disk_unique_id:
            _context_logger.info(f"disk_unique_id:  {self.disk_unique_id}")
        
        # Config summary if exists
        if self.config_exists():
            try:
                cfg = self.load_config()
                _context_logger.info(f"config.version:  {cfg.get('version', 'N/A')}")
                _context_logger.info(f"config.mode:     {cfg.get('mode', 'N/A')}")
                _context_logger.info(f"config.drive_id: {cfg.get('drive_id', 'N/A')[:8]}..." if cfg.get('drive_id') else "config.drive_id: N/A")
            except Exception as e:
                _context_logger.warning(f"Could not load config: {e}")
        
        _context_logger.info("=" * 60)


# =============================================================================
# Factory functions (convenience wrappers)
# =============================================================================

def create_context_from_config(config_path: Path) -> RuntimeContext:
    """
    Create RuntimeContext from an explicit config path.
    
    This is the primary factory for scripts that receive --config.
    """
    return RuntimeContext.from_config_path(config_path)


def create_context_from_drive(drive_root: Path) -> RuntimeContext:
    """
    Create RuntimeContext from a drive root path.
    
    Use this when you know the drive root but not the config path.
    """
    return RuntimeContext.from_drive_root(drive_root)


def infer_context_from_script(script_file: Path) -> RuntimeContext:
    """
    Infer RuntimeContext from a script's __file__.
    
    Use this ONLY for initial entry points. Subprocess calls should
    use --config instead.
    """
    return RuntimeContext.from_script_location(script_file)


# =============================================================================
# Argument parsing helpers
# =============================================================================

def add_config_argument(parser) -> None:
    """
    Add --config argument to an argparse parser.
    
    Usage:
        parser = argparse.ArgumentParser()
        add_config_argument(parser)
        args = parser.parse_args()
        ctx = get_context_from_args(args, __file__)
    """
    parser.add_argument(
        "--config", "-c",
        type=Path,
        metavar="PATH",
        help="Absolute path to config.json (propagated through all operations)"
    )


def get_context_from_args(args, script_file: Path) -> RuntimeContext:
    """
    Get RuntimeContext from parsed args, with fallback to script location.
    
    Args:
        args: Parsed argparse namespace with .config attribute
        script_file: Path(__file__) from calling script
        
    Returns:
        RuntimeContext from --config if provided, else inferred from script location
    """
    if hasattr(args, 'config') and args.config:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = config_path.resolve()
        _context_logger.info(f"Using explicit config: {config_path}")
        return RuntimeContext.from_config_path(config_path)
    else:
        _context_logger.info(f"Inferring context from script location: {script_file}")
        return RuntimeContext.from_script_location(script_file)
