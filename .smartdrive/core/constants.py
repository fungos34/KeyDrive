# core/constants.py - SINGLE SOURCE OF TRUTH for all shared string literals
"""
All shared string constants MUST be defined here.
No other module may define these values.

Categories:
- ConfigKeys: JSON config keys
- UserInputs: Fixed user confirmation strings
- CryptoParams: Cryptographic parameters
- FileNames: Launcher and documentation file names
- Prompts: User-facing prompts and messages
- ConsoleStyle: Unicode vs ASCII-safe output mode
"""

import os
import platform
from enum import Enum
from typing import Dict

# =============================================================================
# Console Style - Unicode vs ASCII-safe output
# =============================================================================


class ConsoleStyle:
    """
    Console output style selection for emoji/unicode vs ASCII-safe rendering.

    Elevated PowerShell on Windows often has broken UTF-8 support, causing
    emoji to render as garbage characters. This class provides ASCII fallbacks.

    Usage:
        style = ConsoleStyle.detect()
        print(style.SUCCESS + " Operation completed")
    """

    # Unicode mode (default)
    UNICODE = "unicode"
    # ASCII-safe mode (for broken consoles)
    ASCII = "ascii"

    # Symbol mappings by mode
    _SYMBOLS = {
        UNICODE: {
            "SUCCESS": "✓",
            "FAILURE": "❌",
            "WARNING": "⚠️",
            "INFO": "ℹ️",
            "KEY": "🔑",
            "LOCK": "🔐",
            "UNLOCK": "🔓",
            "SETUP": "🆕",
            "CONFIG": "ℹ️",
            "RECOVERY": "🆘",
            "SIGN": "✍️",
            "VERIFY": "🔍",
            "CHALLENGE": "📋",
            "HELP": "📖",
            "UPDATE": "📦",
            "EXIT": "❌",
            "TOOLS": "🛠️",
            "DRIVE": "📀",
            "BACK": "↩️",
            "ENCRYPT": "🔒",
            "MENU_DIVIDER": "─",
            "MENU_DOUBLE": "═",
            "BOX_H": "─",
            "BOX_V": "│",
            "BOX_TL": "┌",
            "BOX_TR": "┐",
            "BOX_BL": "└",
            "BOX_BR": "┘",
            "BOX_ML": "├",
            "BOX_MR": "┤",
            "SECTION_SEP": "─",
        },
        ASCII: {
            "SUCCESS": "[OK]",
            "FAILURE": "[X]",
            "WARNING": "[!]",
            "INFO": "[i]",
            "KEY": "[KEY]",
            "LOCK": "[LOCKED]",
            "UNLOCK": "[UNLOCKED]",
            "SETUP": "[NEW]",
            "CONFIG": "[i]",
            "RECOVERY": "[SOS]",
            "SIGN": "[SIGN]",
            "VERIFY": "[CHECK]",
            "CHALLENGE": "[HASH]",
            "HELP": "[?]",
            "UPDATE": "[UPD]",
            "EXIT": "[X]",
            "TOOLS": "[*]",
            "DRIVE": "[=]",
            "BACK": "<-",
            "ENCRYPT": "[ENCRYPT]",
            "MENU_DIVIDER": "-",
            "MENU_DOUBLE": "=",
            "BOX_H": "-",
            "BOX_V": "|",
            "BOX_TL": "+",
            "BOX_TR": "+",
            "BOX_BL": "+",
            "BOX_BR": "+",
            "BOX_ML": "+",
            "BOX_MR": "+",
            "SECTION_SEP": "-",
        },
    }

    def __init__(self, mode: str = None):
        """Initialize with specified mode or auto-detect."""
        self._mode = mode or self.detect_mode()

    @classmethod
    def detect_mode(cls) -> str:
        """
        Auto-detect console style based on environment.

        Returns ASCII mode if:
        - Running elevated on Windows (PowerShell UTF-8 issues)
        - TERM is 'dumb' or not set
        - NO_COLOR or SMARTDRIVE_ASCII environment variable is set
        """
        # Explicit override
        if os.environ.get("SMARTDRIVE_ASCII", "").lower() in ("1", "true", "yes"):
            return cls.ASCII
        if os.environ.get("NO_COLOR"):
            return cls.ASCII

        # Check for dumb terminal
        term = os.environ.get("TERM", "").lower()
        if term in ("dumb", ""):
            # Could be elevated PowerShell or minimal environment
            pass  # Don't immediately return ASCII, check further

        # Windows-specific detection
        if platform.system().lower() == "windows":
            # Check if running elevated - elevated PowerShell often has UTF-8 issues
            # The presence of certain markers can indicate elevation issues
            # However, modern Windows Terminal handles UTF-8 fine even when elevated
            # So we check for the legacy conhost by looking at console properties
            try:
                import ctypes

                # Check for Windows Terminal (which handles UTF-8 correctly)
                if os.environ.get("WT_SESSION"):
                    # Running in Windows Terminal - Unicode is safe
                    return cls.UNICODE

                # Check if elevated
                is_elevated = ctypes.windll.shell32.IsUserAnAdmin() != 0
                if is_elevated:
                    # Check console code page
                    # If running in legacy console (not Windows Terminal), use ASCII
                    # GetConsoleOutputCP returns 0 if no console is attached
                    kernel32 = ctypes.windll.kernel32
                    cp = kernel32.GetConsoleOutputCP()
                    # 65001 is UTF-8, 437 is US ASCII, 850 is Latin-1
                    # If not UTF-8 and elevated, prefer ASCII
                    if cp != 65001:
                        return cls.ASCII
            except:
                pass

        return cls.UNICODE

    @classmethod
    def detect(cls) -> "ConsoleStyle":
        """Factory method to create ConsoleStyle with auto-detection."""
        return cls(cls.detect_mode())

    @property
    def mode(self) -> str:
        """Current mode (UNICODE or ASCII)."""
        return self._mode

    def symbol(self, name: str) -> str:
        """Get symbol by name for current mode."""
        return self._SYMBOLS.get(self._mode, self._SYMBOLS[self.UNICODE]).get(name, "")

    # Convenient properties for common symbols
    @property
    def SUCCESS(self) -> str:
        return self.symbol("SUCCESS")

    @property
    def FAILURE(self) -> str:
        return self.symbol("FAILURE")

    @property
    def WARNING(self) -> str:
        return self.symbol("WARNING")

    @property
    def INFO(self) -> str:
        return self.symbol("INFO")

    @property
    def KEY(self) -> str:
        return self.symbol("KEY")

    @property
    def LOCK(self) -> str:
        return self.symbol("LOCK")

    @property
    def UNLOCK(self) -> str:
        return self.symbol("UNLOCK")

    @property
    def MENU_DIVIDER(self) -> str:
        return self.symbol("MENU_DIVIDER")

    @property
    def BOX_H(self) -> str:
        return self.symbol("BOX_H")

    @property
    def BOX_V(self) -> str:
        return self.symbol("BOX_V")

    @property
    def BOX_TL(self) -> str:
        return self.symbol("BOX_TL")

    @property
    def BOX_TR(self) -> str:
        return self.symbol("BOX_TR")

    @property
    def BOX_BL(self) -> str:
        return self.symbol("BOX_BL")

    @property
    def BOX_BR(self) -> str:
        return self.symbol("BOX_BR")

    @property
    def BOX_ML(self) -> str:
        return self.symbol("BOX_ML")

    @property
    def BOX_MR(self) -> str:
        return self.symbol("BOX_MR")

    def label_for_op(self, op_id: str, unicode_label: str) -> str:
        """
        Get label for operation, using ASCII fallback if needed.

        If mode is ASCII, strips emoji prefix and uses text-only version.
        """
        if self._mode == self.UNICODE:
            return unicode_label

        # Map operation IDs to ASCII-safe labels
        ascii_labels = {
            "mount": "[UNLOCKED] Mount encrypted volume",
            "unmount": "[LOCKED] Unmount volume",
            "setup": "[NEW] Setup new encrypted drive",
            "rekey": "[KEY] Change password / Rotate keyfile",
            "keyfile_utils": "[*] Keyfile utilities",
            "config_status": "[i] Show configuration & status",
            "recovery": "[SOS] Recovery Kit (emergency access)",
            "sign_scripts": "[SIGN] Sign scripts (create integrity signature)",
            "verify_integrity": "[CHECK] Verify script integrity (GPG signature)",
            "challenge_hash": "[HASH] Generate challenge hash (remote verification)",
            "help": "[?] Help / Documentation",
            "update": "[UPD] Update deployment drive",
            "exit": "[X] Exit",
        }
        return ascii_labels.get(op_id, unicode_label)


# =============================================================================
# Config Keys - All JSON configuration keys
# =============================================================================


class ConfigKeys:
    """All configuration file keys. Use these instead of string literals."""

    # Schema and version
    SCHEMA_VERSION = "schema_version"
    VERSION = "version"

    # Drive identification
    DRIVE_ID = "drive_id"  # UUIDv4 - stable per-drive identifier
    DRIVE_NAME = "drive_name"
    MODE = "mode"

    # Lost and found return message support
    LOST_AND_FOUND = "lost_and_found"
    LOST_AND_FOUND_ENABLED = "enabled"
    LOST_AND_FOUND_MESSAGE = "message"

    # Timestamps
    SETUP_DATE = "setup_date"
    LAST_PASSWORD_CHANGE = "last_password_change"
    LAST_VERIFIED = "last_verified"
    LAST_UPDATED = "last_updated"

    # Platform-specific config
    WINDOWS = "windows"
    UNIX = "unix"

    # Volume paths and mount points
    VOLUME_PATH = "volume_path"
    MOUNT_LETTER = "mount_letter"
    MOUNT_POINT = "mount_point"
    VERACRYPT_PATH = "veracrypt_path"

    # Keyfile config
    KEYFILE = "keyfile"
    ENCRYPTED_KEYFILE = "encrypted_keyfile"
    KEYFILE_FINGERPRINTS = "keyfile_fingerprints"

    # GPG password-only mode
    SEED_GPG_PATH = "seed_gpg_path"
    KDF = "kdf"
    SALT_B64 = "salt_b64"
    HKDF_INFO = "hkdf_info"
    PW_ENCODING = "pw_encoding"

    # Update config
    UPDATE_SOURCE_TYPE = "update_source_type"
    UPDATE_URL = "update_url"
    UPDATE_LOCAL_ROOT = "update_local_root"

    # Recovery config
    RECOVERY = "recovery"
    RECOVERY_ENABLED = "enabled"
    RECOVERY_SHARE_COUNT = "share_count"
    RECOVERY_THRESHOLD = "threshold"

    # Verification flags
    VERIFICATION_OVERRIDDEN = "verification_overridden"
    INTEGRITY_SIGNED = "integrity_signed"

    # Signing key configuration
    SIGNING_KEY_FPR = "signing_key_fpr"

    # GUI configuration
    GUI_LANG = "gui_lang"
    GUI_THEME = "gui_theme"

    # Volume identity (computed hash stored during setup)
    VOLUME_IDENTITY = "volume_identity"

    # Legacy alias: SECURITY_MODE -> MODE (TODO 6: migration shim)
    # Some code may reference SECURITY_MODE, but SSOT key is "mode"
    SECURITY_MODE = MODE  # Alias for backwards compatibility


# =============================================================================
# User Input Confirmations - Fixed strings users must type
# =============================================================================


class UserInputs:
    """Fixed user confirmation strings. Use these for input validation."""

    # Confirmation words
    YES = "YES"
    NO = "NO"
    CANCEL = "CANCEL"
    ERASE = "ERASE"
    RECOVER = "RECOVER"
    REKEY = "REKEY"
    CONFIRM = "IUNDERSTAND"

    # Extended confirmations
    ACCEPT_UNVERIFIED = "I ACCEPT UNVERIFIED PASSWORD"

    # Menu choices (single letter)
    RETRY = "R"
    ABORT = "A"
    SKIP = "S"
    CONTINUE = "C"
    MANUAL = "M"
    YES_UPPER = "Y"
    NO_UPPER = "N"
    QUIT = "Q"
    BACK = "B"
    NEXT = "N"

    # After Setup operations
    MOUNT = "M"
    GUI = "G"
    RECOVERY = "P"
    REKEY = "R"
    EXIT = "Q"
    LOGS = "L"


    # clipboard operations
    COPY_PASSWORD = "CPW"
    COPY_DEVICE_PATH = "CDP"
    COPY_KEY_FILE = "CKF"
    PRINT_PASSWORD = "PRINTPW"


# =============================================================================
# Cryptographic Parameters
# =============================================================================


class CryptoParams:
    """Cryptographic constants and parameters."""

    # Keyfile parameters
    KEYFILE_SIZE = 64  # bytes

    # Seed parameters (GPG password-only mode)
    SEED_SIZE = 32  # bytes
    SALT_SIZE = 16  # bytes
    DERIVED_PASSWORD_LENGTH = 32  # characters

    # KDF parameters
    KDF_HKDF_SHA256 = "hkdf-sha256"
    HKDF_INFO_DEFAULT = "smartdrive-vc-pw-v1"
    PW_ENCODING_DEFAULT = "base64url_nopad"

    # PBKDF2 parameters (for recovery)
    PBKDF2_ITERATIONS = 100000
    PBKDF2_DKLEN = 64

    # Argon2id parameters (for recovery word derivation)
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_COST = 65536  # 64 MiB
    ARGON2_PARALLELISM = 4

    # Launcher partition encryption settings
    LAUNCHER_PARTITION_SIZE_MB = 200
    LAUNCHER_FILESYSTEM = "exFAT"  # fat32, exfat, ntfs, ext4
    LAUNCHER_FILESYSTEM_CAPABILITIES = "cross-platform"
    LAUNCHER_FILESYSTEM_ID = "exfat"  # fat32, exfat, ntfs, ext4

    # VeraCrypt encryption settings
    VERACRYPT_ENCRYPTION = "AES-256"
    VERACRYPT_HASH = "SHA-512"
    VERACRYPT_FILESYSTEM = "exFAT"
    VERACRYPT_FILESYSTEM_CAPABILITIES = "works on Windows, macOS, and Linux"

    # Shamir's Secret Sharing defaults
    SHAMIR_DEFAULT_SHARES = 5
    SHAMIR_DEFAULT_THRESHOLD = 3


# =============================================================================
# File Names - Launcher scripts and documentation
# =============================================================================


class FileNames:
    """Standard file names for launchers and documentation."""

    # Configuration file (SSOT - used by all scripts)
    CONFIG_JSON = "config.json"

    # Build output directory (not a deployed path)
    DISTRIBUTION_DIR = "dist"  # Distribution build output directory

    # Integrity/hash files
    HASH_FILE = "scripts.sha256"
    SIGNATURE_FILE = "scripts.sha256.sig"

    # Keyfile names
    KEYFILE_BIN = "keyfile.bin"
    KEYFILE_PLAIN = "keyfile.vc"
    KEYFILE_GPG = "keyfile.vc.gpg"
    SEED_GPG = "seed.gpg"

    # Recovery files
    RECOVERY_SHARES_FILE = "shares.json"
    RECOVERY_METADATA_FILE = "recovery_metadata.json"

    # Audit log
    AUDIT_LOG_FILE = "audit.log"

    # Windows launchers
    BAT_LAUNCHER = "KeyDrive.bat"
    VBS_LAUNCHER = "KeyDrive.vbs"
    GUI_BAT_LAUNCHER = "KeyDriveGUI.bat"
    GUI_EXE = "KeyDriveGUI.exe"

    # Unix launchers
    SH_LAUNCHER = "keydrive.sh"

    # Documentation
    README = "README.md"
    README_PDF = "README.pdf"
    GUI_README = "GUI_README.md"
    GUI_README_PDF = "GUI_README.pdf"

    # Icons - Use LOGO_main as default/unmounted state
    # LOGO_mounted.ico exists for mounted state
    # LOGO_main.ico is the default/unmounted icon
    ICON_MAIN = "LOGO_main.ico"
    ICON_MAIN_PNG = "LOGO_main.png"  # PNG fallback for cross-platform
    ICON_UNMOUNTED = "LOGO_main.ico"  # Unmounted = default/main icon
    ICON_MOUNTED = "LOGO_mounted.ico"
    ICON_FOLDER = "folder_icon.ico"

    # python file names
    MOUNT_PY = "mount.py"
    UNMOUNT_PY = "unmount.py"
    REKEY_PY = "rekey.py"
    KEYFILE_PY = "keyfile.py"
    GUI_LAUNCHER_PY = "gui_launcher.py"
    GUI_PY = "gui.py"
    GUI_I18N_PY = "gui_i18n.py"
    CLI_I18N_PY = "cli_i18n.py"
    RECOVERY_PY = "recovery.py"
    RECOVERY_CONTAINER_PY = "recovery_container.py"
    VERACRYPT_CLI_PY = "veracrypt_cli.py"
    CRYPTO_UTILS_PY = "crypto_utils.py"
    SETUP_PY = "setup.py"
    UPDATE_PY = "update.py"
    DEPLOY_PY = "deploy.py"
    VERSION_PY = "version.py"
    VARIABLES_PY = "variables.py"
    CONSTANTS_PY = "constants.py"
    MODES_PY = "modes.py"
    PATHS_PY = "paths.py"
    LIMITS_PY = "limits.py"
    KEYDRIVE_PY = "smartdrive.py"
    PLATFORM_PY = "platform.py"
    SAFETY_PY = "safety.py"
    REQUIREMENTS_TXT = "requirements.txt"

    # Distinct drive icons for Windows Explorer
    # LOGO_key.ico - KeyDrive launcher partition (USB unencrypted partition)
    # LOGO_drive.ico - VeraCrypt encrypted volume
    # If these don't exist, fall back to LOGO_main.ico / LOGO_mounted.ico
    ICON_LAUNCHER_DRIVE = "LOGO_key.ico"  # For launcher partition in Explorer
    ICON_VERACRYPT_VOLUME = "LOGO_drive.ico"  # For VeraCrypt volume in Explorer
    DRIVE_ICON = "desktop.ini"  # Windows drive icon config file

    # Recovery kit files (SSOT - used by setup.py, recovery.py)
    RECOVERY_CONTAINER_BIN = "recovery_container.bin"
    RECOVERY_HEADER_HDR = "header_backup.hdr"
    RECOVERY_KIT_HTML_SUFFIX = "_Recovery_Kit.html"  # Prefixed with Branding.PRODUCT_NAME

    # Temporary file prefix (SSOT - used during setup)
    TMP_FILE_PREFIX = "smartdrive_"  # Prefix for temp files in RAM-backed dirs

    # File name groups for different operations
    SIGNATURE_HASH_FILES = [
        KEYDRIVE_PY,
        MOUNT_PY,
        UNMOUNT_PY,
        REKEY_PY,
        KEYFILE_PY,
    ]  # Files which get fed to a hash function during signing.
    REQUIRED_CORE_FILES = ["__init__.py", CONSTANTS_PY, MODES_PY, PATHS_PY, LIMITS_PY, VERSION_PY]
    REQUIRED_SCRIPTS_FOR_DEPLOYMENT = [
        MOUNT_PY,
        UNMOUNT_PY,
        RECOVERY_PY,
        RECOVERY_CONTAINER_PY,
        VERACRYPT_CLI_PY,
        CRYPTO_UTILS_PY,
        KEYDRIVE_PY,
    ]
    OPTIONAL_SCRIPTS_FOR_DEPLOYMENT = [
        REKEY_PY,
        KEYFILE_PY,
        GUI_LAUNCHER_PY,
        GUI_PY,
        GUI_I18N_PY,
        VERSION_PY,
        SETUP_PY,
        UPDATE_PY,
        DEPLOY_PY,
    ]
    COPIED_SCRIPTS_FOR_DEPLOYMENT = [
        KEYDRIVE_PY,
        MOUNT_PY,
        UNMOUNT_PY,
        REKEY_PY,
        KEYFILE_PY,
        GUI_LAUNCHER_PY,
        GUI_PY,
        GUI_I18N_PY,
        CRYPTO_UTILS_PY,
        VERSION_PY,
    ]
    FILES_TO_UPDATE = [
        "*.py",
        REQUIREMENTS_TXT,
    ]
    FILES_PROTECTED_FROM_UPDATE = {
        "keys",  # Keyfiles directory
        "integrity",  # Signatures directory
        "recovery_kits",  # Recovery documents
        CONFIG_JSON,  # User configuration (version field updated separately)
    }


# =============================================================================
# Prompts and Messages
# =============================================================================


class Prompts:
    """User-facing prompts and standardized messages."""

    # Phase headers
    PHASE_TEMPLATE = "\n{'='*70}\n  PHASE {num}/{total}: {title}\n{'='*70}\n"

    # Status symbols
    SUCCESS = "✓"
    FAILURE = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    KEY = "🔑"
    LOCK = "🔐"
    UNLOCK = "🔓"

    # Standard messages
    SETUP_COMPLETE = "SETUP COMPLETE!"
    SETUP_INCOMPLETE = "SETUP INCOMPLETE"

    # Error messages
    YUBIKEY_NOT_DETECTED = "YubiKey not detected"
    VERIFICATION_FAILED = "VERIFICATION FAILED"
    RECOVERY_NOT_FOUND = "RECOVERY SCRIPT NOT FOUND"

    # Menu headers
    MENU_DIVIDER = "─" * 70
    MENU_DOUBLE_DIVIDER = "=" * 70


# =============================================================================
# Default Values
# =============================================================================


class Defaults:
    """Default configuration values."""

    # Mount points
    WINDOWS_MOUNT_LETTER = "V"
    UNIX_MOUNT_POINT = "~/veradrive"

    # Config schema
    SCHEMA_VERSION = 2


# =============================================================================
# VeraCrypt CLI Flags - Platform-specific command options
# =============================================================================


class VeraCryptFlags:
    """VeraCrypt CLI flags for command construction (SSOT)."""

    # Windows flags (forward-slash style)
    WIN_VOLUME = "/volume"
    WIN_LETTER = "/letter"
    WIN_PASSWORD = "/password"
    WIN_KEYFILE = "/keyfile"
    WIN_MOUNT = "/mount"
    WIN_DISMOUNT = "/dismount"
    WIN_QUIT = "/quit"
    WIN_SILENT = "/silent"
    WIN_CREATE = "/create"
    WIN_SIZE = "/size"
    WIN_ENCRYPTION = "/encryption"
    WIN_HASH = "/hash"
    WIN_FILESYSTEM = "/filesystem"
    WIN_QUICK = "/quick"
    WIN_PIM = "/pim"
    WIN_BACKUP_HEADERS = "/backup-headers"
    WIN_RESTORE_HEADERS = "/restore-headers"

    # Unix flags (double-dash style)
    UNIX_TEXT = "--text"
    UNIX_NON_INTERACTIVE = "--non-interactive"
    UNIX_STDIN = "--stdin"
    UNIX_MOUNT = "--mount"
    UNIX_DISMOUNT = "--dismount"
    UNIX_PASSWORD = "--password"
    UNIX_KEYFILES = "--keyfiles"
    UNIX_PIM = "--pim"
    UNIX_LIST = "--list"
    UNIX_VERSION = "--version"
    UNIX_FORCE = "--force"
    UNIX_BACKUP_HEADERS = "--backup-headers"
    UNIX_RESTORE_HEADERS = "--restore-headers"


# =============================================================================
# Recovery CLI Flags - Arguments for recovery.py
# =============================================================================


class RecoveryFlags:
    """Recovery script CLI flags (SSOT)."""

    # Subcommands
    CMD_GENERATE = "generate"
    CMD_RECOVER = "recover"
    CMD_RECONSTRUCT = "reconstruct"

    # Flags
    FLAG_OFFLINE = "--offline"


# =============================================================================
# GUI Configuration Keys
# =============================================================================


class GUIConfig:
    """GUI configuration defaults (SSOT)."""

    # Language default
    DEFAULT_LANG = "en"

    # Theme default
    DEFAULT_THEME = "brand"


# =============================================================================
# GUI Theme Palettes (SSOT for all color schemes)
# =============================================================================

THEME_PALETTES: Dict[str, Dict[str, str]] = {
    # IMPORTANT: Do not change the green theme values.
    # The GUI default look depends on these exact colors.
    "brand": {
        "primary": "#2F7AE5",
        "primary_hover": "#2564C0",
        "secondary": "#8AB8FF",
        "success": "#2FA36B",
        "error": "#C93A3A",
        "warning": "#C89B2C",
        "background": "#F7F9FC",
        "surface": "#FFFFFF",
        "border": "#D6DCE6",
        "separator": "#E3E7EE",
        "text": "#1F2933",
        "text_secondary": "#4B5563",
        "text_disabled": "#9AA4B2",
        "smartdrive_used": "#2F7AE5",
        "smartdrive_free": "#BFD6FF",
        "vc_used": "#0E8FAE",
        "vc_free": "#CFEFF6",
        "launch_used": "#2F7AE5",
        "launch_free": "#BFD6FF",
        "close_fg": "#1F2933",
        "close_hover": "#F2DCDC",
        "close_pressed": "#E9B5B5",
    },
    "green": {
        "primary": "#2FA36B",
        "primary_hover": "#3FBF87",
        "secondary": "#7FD1B2",
        "success": "#2FA36B",
        "error": "#f44336",
        "warning": "#D9A441",
        "background": "#0F1F1A",
        "surface": "#162B24",
        "border": "#1B352C",
        "separator": "#244238",
        "text": "#E6F2ED",
        "text_secondary": "#B8D6C9",
        "text_disabled": "#7FA99A",
        "smartdrive_used": "#2FA36B",
        "smartdrive_free": "#7FD1B2",
        "vc_used": "#0891B2",
        "vc_free": "#67E8F9",
        "launch_used": "#2FA36B",
        "launch_free": "#7FD1B2",
        "close_fg": "#ffffff",
        "close_hover": "#ffdddd",
        "close_pressed": "#ffaaaa",
    },
    "blue": {
        "primary": "#2F7AE5",
        "primary_hover": "#2564C0",
        "secondary": "#8AB8FF",
        "success": "#2FA36B",
        "error": "#E24A4A",
        "warning": "#D9A441",
        "background": "#0D1424",
        "surface": "#121F36",
        "border": "#1C2F52",
        "separator": "#223A63",
        "text": "#EAF1FF",
        "text_secondary": "#B9C9E6",
        "text_disabled": "#6E86AF",
        "smartdrive_used": "#2F7AE5",
        "smartdrive_free": "#8AB8FF",
        "vc_used": "#12A4C5",
        "vc_free": "#7DE3F6",
        "launch_used": "#2F7AE5",
        "launch_free": "#8AB8FF",
        "close_fg": "#ffffff",
        "close_hover": "#ffdddd",
        "close_pressed": "#ffaaaa",
    },
    "rose": {
        "primary": "#D9467A",
        "primary_hover": "#EC5B8C",
        "secondary": "#F2A1BC",
        "success": "#D9467A",
        "error": "#f44336",
        "warning": "#D9A441",
        "background": "#1A0F14",
        "surface": "#26161E",
        "border": "#3A1F2B",
        "separator": "#4A2736",
        "text": "#FBE7EF",
        "text_secondary": "#E8BFD0",
        "text_disabled": "#B8879E",
        "smartdrive_used": "#D9467A",
        "smartdrive_free": "#F2A1BC",
        "vc_used": "#E11D48",
        "vc_free": "#FDA4AF",
        "launch_used": "#D9467A",
        "launch_free": "#F2A1BC",
        "close_fg": "#ffffff",
        "close_hover": "#ffdddd",
        "close_pressed": "#ffaaaa",
    },
    "slate": {
        "primary": "#64748B",
        "primary_hover": "#7C8CA6",
        "secondary": "#A8B4C8",
        "success": "#4B9E8C",
        "error": "#f44336",
        "warning": "#D9A441",
        "background": "#0E1116",
        "surface": "#151A22",
        "border": "#1F2632",
        "separator": "#2A3444",
        "text": "#E6EAF0",
        "text_secondary": "#C2CAD6",
        "text_disabled": "#8A94A6",
        "smartdrive_used": "#64748B",
        "smartdrive_free": "#A8B4C8",
        "vc_used": "#38BDF8",
        "vc_free": "#7DD3FC",
        "launch_used": "#64748B",
        "launch_free": "#A8B4C8",
        "close_fg": "#ffffff",
        "close_hover": "#ffdddd",
        "close_pressed": "#ffaaaa",
    },
}


# =============================================================================
# CLI Operations (SSOT for unified menu)
# =============================================================================


class CLIOperations:
    """
    Central definition of all CLI operations for unified menu.

    Each operation has:
    - id: stable string identifier
    - label: display text for menu (can be i18n key)
    - requires_admin: True if operation needs elevated privileges
    - forbidden_on_system_target: True if operation must NEVER target system drive
    - handler: string name of handler function in smartdrive.py
    """

    # Operation IDs (stable strings)
    OP_MOUNT = "mount"
    OP_UNMOUNT = "unmount"
    OP_SETUP = "setup"
    OP_REKEY = "rekey"
    OP_KEYFILE_UTILS = "keyfile_utils"
    OP_CONFIG_STATUS = "config_status"
    OP_RECOVERY = "recovery"
    OP_SIGN_SCRIPTS = "sign_scripts"
    OP_VERIFY_INTEGRITY = "verify_integrity"
    OP_CHALLENGE_HASH = "challenge_hash"
    OP_HELP = "help"
    OP_UPDATE = "update"
    OP_EXIT = "exit"

    # Operation metadata - SINGLE SOURCE OF TRUTH for menu rendering
    # Key: operation ID, Value: dict with label, requires_admin, forbidden_on_system_target, handler
    #
    # IMPORTANT: requires_admin is about whether the operation INHERENTLY needs
    # elevation to function. VeraCrypt handles its own UAC prompts for mount/unmount,
    # so those do NOT require the menu to be elevated. Setup requires admin because
    # it does disk partitioning which needs elevation.
    OPERATIONS = {
        OP_MOUNT: {
            "label": "🔓 Mount encrypted volume",
            "requires_admin": False,  # VeraCrypt handles UAC prompt itself
            "forbidden_on_system_target": False,
            "handler": "run_mount",
        },
        OP_UNMOUNT: {
            "label": "🔒 Unmount volume",
            "requires_admin": False,  # VeraCrypt handles UAC prompt itself
            "forbidden_on_system_target": False,
            "handler": "run_unmount",
        },
        OP_SETUP: {
            "label": "🆕 Setup new encrypted drive",
            "requires_admin": True,  # Partitioning requires admin
            "forbidden_on_system_target": True,  # NEVER on system drive
            "handler": "run_setup",
        },
        OP_REKEY: {
            "label": "🔑 Change password / Rotate keyfile",
            "requires_admin": True,  # VeraCrypt password change needs admin
            "forbidden_on_system_target": False,
            "handler": "run_rekey",
        },
        OP_KEYFILE_UTILS: {
            "label": "🛠️  Keyfile utilities",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "keyfile_utilities_menu",
        },
        OP_CONFIG_STATUS: {
            "label": "ℹ️  Show configuration & status",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "show_config_status",
        },
        OP_RECOVERY: {
            "label": "🆘 Recovery Kit (emergency access)",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "recovery_menu",
        },
        OP_SIGN_SCRIPTS: {
            "label": "✍️  Sign scripts (create integrity signature)",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "sign_scripts",
        },
        OP_VERIFY_INTEGRITY: {
            "label": "🔍 Verify script integrity (GPG signature)",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "verify_integrity",
        },
        OP_CHALLENGE_HASH: {
            "label": "📋 Generate challenge hash (remote verification)",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "generate_challenge_hash",
        },
        OP_HELP: {
            "label": "📖 Help / Documentation",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "show_help",
        },
        OP_UPDATE: {
            "label": "📦 Update deployment drive",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": "update_deployment_drive_menu",
        },
        OP_EXIT: {
            "label": "❌ Exit",
            "requires_admin": False,
            "forbidden_on_system_target": False,
            "handler": None,
        },
    }

    # Unified menu order - all operations shown regardless of launch context
    UNIFIED_MENU_ORDER = [
        OP_MOUNT,
        OP_UNMOUNT,
        OP_SETUP,
        OP_REKEY,
        OP_KEYFILE_UTILS,
        OP_CONFIG_STATUS,
        OP_RECOVERY,
        OP_SIGN_SCRIPTS,
        OP_VERIFY_INTEGRITY,
        OP_CHALLENGE_HASH,
        OP_UPDATE,
        OP_HELP,
        OP_EXIT,
    ]

    # Menu sections for visual grouping
    # Each section: (section_name, [operation_ids])
    MENU_SECTIONS = [
        ("Volume Operations", [OP_MOUNT, OP_UNMOUNT]),
        ("Setup & Configuration", [OP_SETUP, OP_REKEY, OP_KEYFILE_UTILS, OP_CONFIG_STATUS]),
        ("Recovery & Security", [OP_RECOVERY, OP_SIGN_SCRIPTS, OP_VERIFY_INTEGRITY, OP_CHALLENGE_HASH]),
        ("System", [OP_UPDATE, OP_HELP]),
    ]

    @classmethod
    def get_operation(cls, op_id: str) -> dict:
        """Get operation metadata by ID."""
        return cls.OPERATIONS.get(op_id, {})

    @classmethod
    def is_admin_required(cls, op_id: str) -> bool:
        """Check if operation requires admin privileges."""
        return cls.OPERATIONS.get(op_id, {}).get("requires_admin", False)

    @classmethod
    def is_forbidden_on_system(cls, op_id: str) -> bool:
        """Check if operation is forbidden on system drive target."""
        return cls.OPERATIONS.get(op_id, {}).get("forbidden_on_system_target", False)


# =============================================================================
# Product Branding (from variables.py consolidation)
# =============================================================================


class Branding:
    """Product branding constants."""

    PRODUCT_NAME = "KeyDrive"
    PRODUCT_NAME_FULL = "KeyDrive Secure Storage"
    PRODUCT_DESCRIPTION = "Secure, Encrypted Portable Storage Solution"
    COMPANY_NAME = "KeyDrive (c) 2021-2024 SecureStorage Inc."
    AUTHOR_NAME = "Johannes F. Wagner",
    SUPPORT_EMAIL = "info@alpwolf.at",
    WEBSITE_URL = "https://www.alpwolf.at"

    # GUI theme colors
    THEME = THEME_PALETTES["brand"]

    APP_NAME = PRODUCT_NAME
    ORGANIZATION_NAME = COMPANY_NAME
    TITLE_MAX_CHARS = 18
    TITLE_MIN_SIDE_CHARS = 2
    WINDOW_WIDTH = 360
    WINDOW_HEIGHT = 380
    WINDOW_MARGIN = 20
    CORNER_RADIUS = 12
    COLORS = THEME.copy()
    WINDOW_TITLE = f"{PRODUCT_NAME} Manager"
    BANNER_TITLE = f"{PRODUCT_NAME} Manager"
