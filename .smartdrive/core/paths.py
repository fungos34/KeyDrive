# core/paths.py - SINGLE SOURCE OF TRUTH for all filesystem paths
"""
All filesystem paths MUST be defined here as Path objects.
No other module may construct filesystem paths.

RULES:
- All paths are Path objects internally
- Convert to str() ONLY at I/O boundaries (subprocess, JSON, print)
- Use Path arithmetic (/) for joins, never string concatenation
"""

from pathlib import Path
from typing import Optional
import platform
import os


class Paths:
    """
    Centralized path definitions. All paths are Path objects.
    
    Usage:
        from core.paths import Paths
        config_path = Paths.config_file(launcher_root)
    """
    
    # ==========================================================================
    # Directory structure constants (relative)
    # ==========================================================================
    
    # Hidden SmartDrive data directory
    SMARTDRIVE_DIR_NAME = ".smartdrive"
    
    # Subdirectories under .smartdrive/
    SCRIPTS_SUBDIR = "scripts"
    KEYS_SUBDIR = "keys"
    INTEGRITY_SUBDIR = "integrity"
    RECOVERY_SUBDIR = "recovery"
    STATIC_SUBDIR = "static"  # Static assets under .smartdrive/
    
    # Legacy static assets directory name (at launcher root)
    STATIC_DIR_NAME = "static"
    
    # ==========================================================================
    # File names
    # ==========================================================================
    
    CONFIG_FILENAME = "config.json"
    
    # Keyfile names
    KEYFILE_PLAIN = "keyfile.vc"
    KEYFILE_GPG = "keyfile.vc.gpg"
    SEED_GPG = "seed.gpg"
    
    # Integrity files
    INTEGRITY_HASH = "scripts.sha256"
    INTEGRITY_SIG = "scripts.sha256.sig"
    
    # Recovery files
    RECOVERY_SHARES_FILE = "shares.json"
    RECOVERY_METADATA_FILE = "recovery_metadata.json"
    
    # Audit log
    AUDIT_LOG_FILE = "audit.log"

    # Executable names (platform-specific)
    # Use these with shutil.which(...) when checking PATH
    VERACRYPT_EXE_NAME = "VeraCrypt.exe"
    VERACRYPT_FORMAT_EXE_NAME = "VeraCrypt Format.exe"
    
    # ==========================================================================
    # VeraCrypt installation paths (platform-specific)
    # ==========================================================================
    
    @classmethod
    def veracrypt_exe(cls) -> Optional[Path]:
        """Return the VeraCrypt executable path for the current platform."""
        system = platform.system().lower()
        
        if "windows" in system:
            # Check both possible installation locations
            paths = [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "VeraCrypt" / "VeraCrypt.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "VeraCrypt" / "VeraCrypt.exe",
            ]
            for p in paths:
                if p.exists():
                    return p
            # Return default even if not found (for error messages)
            return paths[0]
        elif "darwin" in system:
            return Path("/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt")
        else:
            # Linux - typically in PATH
            return Path("/usr/bin/veracrypt")
    
    @classmethod
    def veracrypt_format_exe(cls) -> Optional[Path]:
        """Return the VeraCrypt Format executable (Windows only)."""
        system = platform.system().lower()
        
        if "windows" in system:
            paths = [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "VeraCrypt" / "VeraCrypt Format.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "VeraCrypt" / "VeraCrypt Format.exe",
            ]
            for p in paths:
                if p.exists():
                    return p
            return paths[0]
        return None
    
    # ==========================================================================
    # Path builders (return Path objects)
    # ==========================================================================
    
    @classmethod
    def smartdrive_dir(cls, launcher_root: Path) -> Path:
        """Return the .smartdrive directory path."""
        return launcher_root / cls.SMARTDRIVE_DIR_NAME
    
    @classmethod
    def scripts_dir(cls, launcher_root: Path) -> Path:
        """Return the scripts directory path."""
        return cls.smartdrive_dir(launcher_root) / cls.SCRIPTS_SUBDIR
    
    @classmethod
    def keys_dir(cls, launcher_root: Path) -> Path:
        """Return the keys directory path."""
        return cls.smartdrive_dir(launcher_root) / cls.KEYS_SUBDIR
    
    @classmethod
    def integrity_dir(cls, launcher_root: Path) -> Path:
        """Return the integrity directory path."""
        return cls.smartdrive_dir(launcher_root) / cls.INTEGRITY_SUBDIR
    
    @classmethod
    def recovery_dir(cls, launcher_root: Path) -> Path:
        """Return the recovery directory path."""
        return cls.smartdrive_dir(launcher_root) / cls.RECOVERY_SUBDIR
    
    @classmethod
    def static_dir(cls, launcher_root: Path) -> Path:
        """
        Return the static assets directory path.
        
        Priority order:
        1. .smartdrive/static/ (deployed structure)
        2. ROOT/static/ (legacy/dev structure)
        
        Returns the first existing directory, or .smartdrive/static/ as default.
        """
        # Primary: .smartdrive/static/ (deployed/preferred structure)
        primary = cls.smartdrive_dir(launcher_root) / cls.STATIC_SUBDIR
        if primary.exists():
            return primary
        
        # Legacy fallback: ROOT/static/ (development structure)
        legacy = launcher_root / cls.STATIC_DIR_NAME
        if legacy.exists():
            return legacy
        
        # Default to primary even if it doesn't exist yet
        return primary
    
    @classmethod
    def logs_dir(cls, launcher_root: Path) -> Path:
        """Return the logs directory path for GUI logging."""
        return cls.smartdrive_dir(launcher_root) / "logs"
    
    @classmethod
    def gui_log_file(cls, launcher_root: Path) -> Path:
        """Return the GUI log file path."""
        return cls.logs_dir(launcher_root) / "gui.log"
    
    @classmethod
    def static_file(cls, launcher_root: Path, filename: str) -> Path:
        """
        Return path to a static asset file.
        
        Args:
            launcher_root: Root directory (drive root or repo root)
            filename: Name of the static file (e.g., "LOGO_mounted.ico")
            
        Returns:
            Path to the static file
        """
        return cls.static_dir(launcher_root) / filename
    
    @classmethod
    def icon_mounted(cls, launcher_root: Path) -> Path:
        """Return path to the mounted volume icon."""
        return cls.static_file(launcher_root, "LOGO_mounted.ico")
    
    @classmethod
    def icon_unmounted(cls, launcher_root: Path) -> Path:
        """Return path to the unmounted volume icon."""
        return cls.static_file(launcher_root, "LOGO_unmounted.ico")
    
    @classmethod
    def icon_main(cls, launcher_root: Path) -> Path:
        """Return path to the main drive icon."""
        return cls.static_file(launcher_root, "LOGO_main.ico")
    
    @classmethod
    def icon_launcher_drive(cls, launcher_root: Path) -> Path:
        """Return path to the launcher partition icon (for Windows Explorer).
        
        Falls back to LOGO_main.ico if LOGO_key.ico doesn't exist.
        """
        preferred = cls.static_file(launcher_root, "LOGO_key.ico")
        if preferred.exists():
            return preferred
        return cls.static_file(launcher_root, "LOGO_main.ico")
    
    @classmethod
    def icon_veracrypt_volume(cls, launcher_root: Path) -> Path:
        """Return path to the VeraCrypt volume icon (for Windows Explorer).
        
        Falls back to LOGO_mounted.ico if LOGO_drive.ico doesn't exist.
        """
        preferred = cls.static_file(launcher_root, "LOGO_drive.ico")
        if preferred.exists():
            return preferred
        return cls.static_file(launcher_root, "LOGO_mounted.ico")
    
    @classmethod
    def config_file(cls, launcher_root: Path) -> Path:
        """Return the config.json path.
        
        NOTE: Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json.
        This is intentional - config is a runtime artifact that persists independent of scripts.
        """
        return cls.smartdrive_dir(launcher_root) / cls.CONFIG_FILENAME
    
    @classmethod
    def keyfile_gpg(cls, launcher_root: Path) -> Path:
        """Return the encrypted keyfile path."""
        return cls.keys_dir(launcher_root) / cls.KEYFILE_GPG
    
    @classmethod
    def keyfile_plain(cls, launcher_root: Path) -> Path:
        """Return the plain keyfile path."""
        return cls.keys_dir(launcher_root) / cls.KEYFILE_PLAIN
    
    @classmethod
    def seed_gpg(cls, launcher_root: Path) -> Path:
        """Return the encrypted seed path."""
        return cls.keys_dir(launcher_root) / cls.SEED_GPG
    
    @classmethod
    def integrity_hash_file(cls, launcher_root: Path) -> Path:
        """Return the integrity hash file path."""
        return cls.integrity_dir(launcher_root) / cls.INTEGRITY_HASH
    
    @classmethod
    def integrity_sig_file(cls, launcher_root: Path) -> Path:
        """Return the integrity signature file path."""
        return cls.integrity_dir(launcher_root) / cls.INTEGRITY_SIG
    
    @classmethod
    def audit_log(cls, launcher_root: Path) -> Path:
        """Return the audit log file path."""
        return cls.smartdrive_dir(launcher_root) / cls.AUDIT_LOG_FILE
    
    @classmethod
    def recovery_shares(cls, launcher_root: Path) -> Path:
        """Return the recovery shares file path."""
        return cls.recovery_dir(launcher_root) / cls.RECOVERY_SHARES_FILE
    
    @classmethod
    def recovery_metadata(cls, launcher_root: Path) -> Path:
        """Return the recovery metadata file path."""
        return cls.recovery_dir(launcher_root) / cls.RECOVERY_METADATA_FILE
    
    # ==========================================================================
    # Script file paths
    # ==========================================================================
    
    @classmethod
    def script(cls, launcher_root: Path, script_name: str) -> Path:
        """Return the path to a specific script."""
        return cls.scripts_dir(launcher_root) / script_name
    
    # Required scripts that must exist for core functionality
    REQUIRED_SCRIPTS = [
        "mount.py",
        "unmount.py",
        "recovery.py",
        "recovery_container.py",
        "veracrypt_cli.py",
        "crypto_utils.py",
        "smartdrive.py",
    ]
    
    # Optional scripts
    OPTIONAL_SCRIPTS = [
        "rekey.py",
        "keyfile.py",
        "gui_launcher.py",
        "gui.py",
        "version.py",
        "setup.py",
        "update.py",
    ]
    
    @classmethod
    def assert_required_scripts_exist(cls, launcher_root: Path) -> None:
        """
        Assert all required scripts exist. Raises RuntimeError if any missing.
        """
        scripts = cls.scripts_dir(launcher_root)
        missing = []
        for script_name in cls.REQUIRED_SCRIPTS:
            if not (scripts / script_name).exists():
                missing.append(script_name)
        if missing:
            raise RuntimeError(
                f"Required scripts missing from {scripts}: {', '.join(missing)}"
            )
    
    # ==========================================================================
    # Utility: Path normalization from config
    # ==========================================================================
    
    @classmethod
    def normalize_path(cls, path_str: Optional[str]) -> Optional[Path]:
        """
        Convert a string path (from config/JSON) to a Path object.
        Returns None if input is None or empty.
        
        This is the ONLY function that should convert config strings to Paths.
        """
        if not path_str:
            return None
        return Path(path_str)
    
    @classmethod
    def to_str(cls, path: Optional[Path]) -> Optional[str]:
        """
        Convert a Path to string for I/O (JSON, subprocess).
        Returns None if input is None.
        
        Use this at I/O boundaries only.
        """
        if path is None:
            return None
        return str(path)


# =============================================================================
# Legacy compatibility: DEPLOYED_SCRIPTS_DIR as Path object
# =============================================================================
# This is kept for backward compatibility during migration.
# New code should use Paths.scripts_dir(launcher_root) instead.

DEPLOYED_SCRIPTS_DIR = Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.SCRIPTS_SUBDIR


# =============================================================================
# Platform-specific utility functions
# =============================================================================

def normalize_mount_letter(letter: str) -> str:
    """
    Normalize Windows drive letter to canonical format for VeraCrypt CLI.
    
    Args:
        letter: Drive letter in various formats ("Z", "z:", " /Z: ", etc.)
    
    Returns:
        Canonical uppercase single letter (e.g., "Z")
        NEVER returns strings starting with "/" or "-"
    
    Raises:
        ValueError: If input is empty, multi-char (after cleanup), or non-alpha
    
    Examples:
        "Z" -> "Z"
        "z:" -> "Z"
        " /Z: " -> "Z"
        "AB" -> ValueError
        "" -> ValueError
    """
    if not letter:
        raise ValueError("Mount letter cannot be empty")
    
    # Strip whitespace, colons, and leading slashes
    letter_clean = letter.strip().upper().replace(":", "").replace("/", "").replace("-", "")
    
    if len(letter_clean) != 1:
        raise ValueError(f"Invalid drive letter (must be single character): {letter!r}")
    if not letter_clean.isalpha():
        raise ValueError(f"Invalid drive letter (must be alphabetic): {letter!r}")
    
    return letter_clean
