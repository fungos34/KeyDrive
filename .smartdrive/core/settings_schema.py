"""
Settings schema for GUI Settings dialog.

Defines metadata for all config.json fields to enable:
- Schema-driven UI generation
- Tab organization
- Path picker integration
- i18n label/tooltip support
- Field visibility rules
- Validation
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

from core.constants import ConfigKeys
from core.modes import SECURITY_MODE_DISPLAY, SecurityMode
from core.paths import Paths

# =============================================================================
# Field Types
# =============================================================================


class FieldType(Enum):
    """Widget type for settings field."""

    TEXT = "text"  # QLineEdit
    PATH_FILE = "path_file"  # QLineEdit + Browse button (file)
    PATH_DIR = "path_dir"  # QLineEdit + Browse button (directory)
    NUMBER = "number"  # QSpinBox
    BOOLEAN = "boolean"  # QCheckBox
    DROPDOWN = "dropdown"  # QComboBox
    TEXTAREA = "textarea"  # QTextEdit (multiline)
    READONLY = "readonly"  # QLabel (display only)


# =============================================================================
# Setting Field Definition
# =============================================================================


@dataclass
class SettingField:
    """
    Metadata for a single settings field.

    Attributes:
        key: ConfigKeys constant
        label_key: i18n translation key for label
        field_type: Widget type to use
        tab: Tab name (e.g., "General", "Security")
        group: Group box name within tab (optional)
        default: Default value if not in config
        readonly: If True, display as read-only label
        tooltip_key: i18n key for tooltip (optional)
        placeholder: Placeholder text (optional)
        options: List of options for dropdown [(display, value), ...]
        validation: Function(value) -> (bool, error_msg)
        visibility_condition: Function(config) -> bool (show field?)
        nested_path: Path to nested key, e.g., ["windows", "volume_path"]
        order: Display order within group (lower = first)
    """

    key: str
    label_key: str
    field_type: FieldType
    tab: str
    group: Optional[str] = None
    default: Any = None
    readonly: bool = False
    tooltip_key: Optional[str] = None
    placeholder: Optional[str] = None
    options: Optional[List[tuple]] = None
    validation: Optional[Callable[[Any], tuple[bool, str]]] = None
    visibility_condition: Optional[Callable[[dict], bool]] = None
    nested_path: Optional[List[str]] = None
    order: int = 100


# =============================================================================
# Validation Functions
# =============================================================================


def validate_mount_letter(value: str) -> tuple[bool, str]:
    """Validate Windows mount letter (A-Z)."""
    if not value:
        return True, ""  # Empty is valid (will use default)
    value = value.strip().upper()
    if len(value) != 1 or not ("A" <= value <= "Z"):
        return False, "Mount letter must be a single letter (A-Z)"
    return True, ""


def validate_uuid(value: str) -> tuple[bool, str]:
    """Validate UUIDv4 format."""
    if not value:
        return True, ""
    import re

    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    if not re.match(uuid_pattern, value, re.IGNORECASE):
        return False, "Invalid UUID format"
    return True, ""


def validate_positive_int(value: Any) -> tuple[bool, str]:
    """Validate positive integer."""
    try:
        num = int(value)
        if num <= 0:
            return False, "Must be a positive number"
        return True, ""
    except (ValueError, TypeError):
        return False, "Must be a valid number"


# =============================================================================
# Visibility Conditions
# =============================================================================


def show_if_keyfile_mode(config: dict) -> bool:
    """Show field only if mode uses keyfile."""
    mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
    return mode in [SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value]


def show_if_gpg_mode(config: dict) -> bool:
    """Show field only if mode uses GPG."""
    mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)
    return mode in [SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value]


def show_if_recovery_enabled(config: dict) -> bool:
    """Show field only if recovery is enabled."""
    recovery = config.get(ConfigKeys.RECOVERY, {})
    return recovery.get(ConfigKeys.RECOVERY_ENABLED, False)


# =============================================================================
# Settings Schema - All Fields
# =============================================================================

SETTINGS_SCHEMA: List[SettingField] = [
    # =========================================================================
    # General Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.DRIVE_ID,
        label_key="label_drive_id",
        field_type=FieldType.READONLY,
        tab="General",
        group="Drive Identification",
        readonly=True,
        tooltip_key="tooltip_drive_id",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.DRIVE_NAME,
        label_key="label_drive_name",
        field_type=FieldType.TEXT,
        tab="General",
        group="Drive Identification",
        placeholder="My Encrypted Drive",
        tooltip_key="tooltip_drive_name",
        order=2,
    ),
    SettingField(
        key=ConfigKeys.GUI_LANG,
        label_key="settings_language",
        field_type=FieldType.DROPDOWN,
        tab="General",
        group="Appearance",
        default="en",
        tooltip_key="tooltip_language",
        order=10,
    ),
    SettingField(
        key=ConfigKeys.GUI_THEME,
        label_key="label_theme",
        field_type=FieldType.DROPDOWN,
        tab="General",
        group="Appearance",
        default="system",
        tooltip_key="tooltip_theme",
        order=11,
    ),
    SettingField(
        key=ConfigKeys.SETUP_DATE,
        label_key="label_setup_date",
        field_type=FieldType.READONLY,
        tab="General",
        group="Timestamps",
        readonly=True,
        order=20,
    ),
    SettingField(
        key=ConfigKeys.LAST_PASSWORD_CHANGE,
        label_key="label_last_password_change",
        field_type=FieldType.READONLY,
        tab="General",
        group="Timestamps",
        readonly=True,
        order=21,
    ),
    SettingField(
        key=ConfigKeys.LAST_VERIFIED,
        label_key="label_last_verified",
        field_type=FieldType.READONLY,
        tab="General",
        group="Timestamps",
        readonly=True,
        order=22,
    ),
    # =========================================================================
    # Security Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.MODE,
        label_key="label_mode",
        field_type=FieldType.DROPDOWN,
        tab="Security",
        group="Security Mode",
        default=SecurityMode.PW_ONLY.value,
        options=[
            (SECURITY_MODE_DISPLAY[SecurityMode.PW_ONLY], SecurityMode.PW_ONLY.value),
            (SECURITY_MODE_DISPLAY[SecurityMode.PW_KEYFILE], SecurityMode.PW_KEYFILE.value),
            (SECURITY_MODE_DISPLAY[SecurityMode.GPG_PW_ONLY], SecurityMode.GPG_PW_ONLY.value),
            (SECURITY_MODE_DISPLAY[SecurityMode.PW_GPG_KEYFILE], SecurityMode.PW_GPG_KEYFILE.value),
        ],
        tooltip_key="tooltip_mode",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.ENCRYPTED_KEYFILE,
        label_key="label_encrypted_keyfile",
        field_type=FieldType.PATH_FILE,
        tab="Security",
        group="Keyfile Configuration",
        tooltip_key="tooltip_encrypted_keyfile",
        visibility_condition=show_if_keyfile_mode,
        order=10,
    ),
    SettingField(
        key=ConfigKeys.KEYFILE,
        label_key="label_plain_keyfile",
        field_type=FieldType.PATH_FILE,
        tab="Security",
        group="Keyfile Configuration",
        tooltip_key="tooltip_plain_keyfile",
        order=11,
    ),
    SettingField(
        key=ConfigKeys.SEED_GPG_PATH,
        label_key="label_seed_gpg_path",
        field_type=FieldType.PATH_FILE,
        tab="Security",
        group="GPG Configuration",
        tooltip_key="tooltip_seed_gpg_path",
        visibility_condition=show_if_gpg_mode,
        order=20,
    ),
    SettingField(
        key=ConfigKeys.KDF,
        label_key="label_kdf",
        field_type=FieldType.DROPDOWN,
        tab="Security",
        group="GPG Configuration",
        default="scrypt",
        options=[
            ("scrypt (recommended)", "scrypt"),
            ("argon2id", "argon2id"),
        ],
        tooltip_key="tooltip_kdf",
        visibility_condition=show_if_gpg_mode,
        order=21,
    ),
    SettingField(
        key=ConfigKeys.PW_ENCODING,
        label_key="label_pw_encoding",
        field_type=FieldType.DROPDOWN,
        tab="Security",
        group="GPG Configuration",
        default="utf-8",
        options=[
            ("UTF-8", "utf-8"),
            ("Latin-1", "latin-1"),
        ],
        tooltip_key="tooltip_pw_encoding",
        visibility_condition=show_if_gpg_mode,
        order=22,
    ),
    # =========================================================================
    # Windows Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.VOLUME_PATH,
        label_key="label_volume_path",
        field_type=FieldType.TEXT,  # Volume GUID or \\Device\\Harddisk path
        tab="Windows",
        group=None,
        nested_path=[ConfigKeys.WINDOWS, ConfigKeys.VOLUME_PATH],
        placeholder=r"\\?\Volume{...} or \\Device\Harddisk1\Partition2",
        tooltip_key="tooltip_windows_volume_path",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.MOUNT_LETTER,
        label_key="label_mount_letter",
        field_type=FieldType.TEXT,
        tab="Windows",
        group=None,
        nested_path=[ConfigKeys.WINDOWS, ConfigKeys.MOUNT_LETTER],
        default="V",
        placeholder="V",
        validation=validate_mount_letter,
        tooltip_key="tooltip_mount_letter",
        order=2,
    ),
    # BUG-20251221-037: Mount point fallback toggle
    SettingField(
        key=ConfigKeys.WINDOWS_ALLOW_MOUNT_FALLBACK,
        label_key="label_allow_mount_fallback",
        field_type=FieldType.BOOLEAN,
        tab="Windows",
        group=None,
        nested_path=[ConfigKeys.WINDOWS, ConfigKeys.ALLOW_MOUNT_FALLBACK],
        default=True,
        tooltip_key="tooltip_allow_mount_fallback",
        order=3,
    ),
    SettingField(
        key=ConfigKeys.VERACRYPT_PATH,
        label_key="label_veracrypt_path",
        field_type=FieldType.PATH_FILE,
        tab="Windows",
        group=None,
        nested_path=[ConfigKeys.WINDOWS, ConfigKeys.VERACRYPT_PATH],
        placeholder=r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
        tooltip_key="tooltip_veracrypt_path",
        order=4,
    ),
    # =========================================================================
    # Drive Context Display (CHG-20251221-040)
    # Shows all 4 drive types: OS, Instantiation, Launcher, VeraCrypt
    # These are runtime-computed read-only fields for user awareness
    # BUG-20251224-001 FIX: Use platform-specific keys to avoid duplicate key errors
    # =========================================================================
    SettingField(
        key=ConfigKeys.WINDOWS_OS_DRIVE,
        label_key="label_os_drive",
        field_type=FieldType.READONLY,
        tab="Windows",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_os_drive",
        order=8,
    ),
    SettingField(
        key=ConfigKeys.WINDOWS_INSTANTIATION_DRIVE,
        label_key="label_instantiation_drive",
        field_type=FieldType.READONLY,
        tab="Windows",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_instantiation_drive",
        order=9,
    ),
    # Launcher Root: Read-only display of current .smartdrive context (CHG-20251221-026)
    # BUG-20251223-001 FIX: Use WINDOWS_LAUNCHER_ROOT to avoid duplicate key collision
    SettingField(
        key=ConfigKeys.WINDOWS_LAUNCHER_ROOT,
        label_key="label_launcher_root",
        field_type=FieldType.READONLY,
        tab="Windows",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_launcher_root",
        order=10,
    ),
    # =========================================================================
    # Unix Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.VOLUME_PATH,
        label_key="label_volume_path",
        field_type=FieldType.TEXT,
        tab="Unix",
        group=None,
        nested_path=[ConfigKeys.UNIX, ConfigKeys.VOLUME_PATH],
        placeholder="/dev/sdb2",
        tooltip_key="tooltip_unix_volume_path",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.MOUNT_POINT,
        label_key="label_mount_point",
        field_type=FieldType.PATH_DIR,
        tab="Unix",
        group=None,
        nested_path=[ConfigKeys.UNIX, ConfigKeys.MOUNT_POINT],
        default="~/veradrive",
        placeholder="~/veradrive",
        tooltip_key="tooltip_mount_point",
        order=2,
    ),
    # BUG-20251221-037: Mount point fallback toggle
    SettingField(
        key=ConfigKeys.UNIX_ALLOW_MOUNT_FALLBACK,
        label_key="label_allow_mount_fallback",
        field_type=FieldType.BOOLEAN,
        tab="Unix",
        group=None,
        nested_path=[ConfigKeys.UNIX, ConfigKeys.ALLOW_MOUNT_FALLBACK],
        default=True,
        tooltip_key="tooltip_allow_mount_fallback",
        order=3,
    ),
    # =========================================================================
    # Drive Context Display (CHG-20251221-040) - Unix
    # Shows all 4 drive types: OS, Instantiation, Launcher, VeraCrypt
    # BUG-20251224-001 FIX: Use platform-specific keys to avoid duplicate key errors
    # =========================================================================
    SettingField(
        key=ConfigKeys.UNIX_OS_DRIVE,
        label_key="label_os_drive",
        field_type=FieldType.READONLY,
        tab="Unix",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_os_drive",
        order=8,
    ),
    SettingField(
        key=ConfigKeys.UNIX_INSTANTIATION_DRIVE,
        label_key="label_instantiation_drive",
        field_type=FieldType.READONLY,
        tab="Unix",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_instantiation_drive",
        order=9,
    ),
    # Launcher Root: Read-only display of current .smartdrive context (CHG-20251221-026)
    # BUG-20251223-001 FIX: Use UNIX_LAUNCHER_ROOT to avoid duplicate key collision
    SettingField(
        key=ConfigKeys.UNIX_LAUNCHER_ROOT,
        label_key="label_launcher_root",
        field_type=FieldType.READONLY,
        tab="Unix",
        group="drive_context",
        readonly=True,
        tooltip_key="tooltip_launcher_root",
        order=10,
    ),
    # =========================================================================
    # Recovery Tab
    # BUG-20251220-006 FIX: Changed from editable checkbox to read-only status
    # The recovery.enabled flag should reflect actual kit existence, not user toggle
    # =========================================================================
    SettingField(
        key=ConfigKeys.RECOVERY_ENABLED,
        label_key="label_recovery_status",
        field_type=FieldType.READONLY,  # BUG-20251220-006: Display as status text
        tab="Recovery",
        group="Emergency Recovery Kit",
        nested_path=[ConfigKeys.RECOVERY, ConfigKeys.RECOVERY_ENABLED],
        default=False,
        tooltip_key="tooltip_recovery_status",
        readonly=True,
        order=1,
    ),
    SettingField(
        key=ConfigKeys.RECOVERY_SHARE_COUNT,
        label_key="label_recovery_share_count",
        field_type=FieldType.NUMBER,
        tab="Recovery",
        group="Emergency Recovery Kit",
        nested_path=[ConfigKeys.RECOVERY, ConfigKeys.RECOVERY_SHARE_COUNT],
        default=5,
        validation=validate_positive_int,
        tooltip_key="tooltip_recovery_share_count",
        visibility_condition=show_if_recovery_enabled,
        order=2,
    ),
    SettingField(
        key=ConfigKeys.RECOVERY_THRESHOLD,
        label_key="label_recovery_threshold",
        field_type=FieldType.NUMBER,
        tab="Recovery",
        group="Emergency Recovery Kit",
        nested_path=[ConfigKeys.RECOVERY, ConfigKeys.RECOVERY_THRESHOLD],
        default=3,
        validation=validate_positive_int,
        tooltip_key="tooltip_recovery_threshold",
        visibility_condition=show_if_recovery_enabled,
        order=3,
    ),
    # =========================================================================
    # Lost & Found Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.LOST_AND_FOUND_ENABLED,
        label_key="label_lost_and_found_enabled",
        field_type=FieldType.BOOLEAN,
        tab="Lost and Found",
        group=None,
        nested_path=[ConfigKeys.LOST_AND_FOUND, ConfigKeys.LOST_AND_FOUND_ENABLED],
        default=False,
        tooltip_key="tooltip_lost_and_found_enabled",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.LOST_AND_FOUND_MESSAGE,
        label_key="label_lost_and_found_message",
        field_type=FieldType.TEXTAREA,
        tab="Lost and Found",
        group=None,
        nested_path=[ConfigKeys.LOST_AND_FOUND, ConfigKeys.LOST_AND_FOUND_MESSAGE],
        placeholder="If found, please contact: your@email.com",
        tooltip_key="tooltip_lost_and_found_message",
        order=2,
    ),
    # =========================================================================
    # Updates Tab
    # =========================================================================
    SettingField(
        key=ConfigKeys.UPDATE_SOURCE_TYPE,
        label_key="label_source_type",
        field_type=FieldType.DROPDOWN,
        tab="Updates",
        group=None,
        default="local",
        options=[
            ("Local Directory", "local"),
            ("Server URL", "server"),
        ],
        tooltip_key="tooltip_source_type",
        order=1,
    ),
    SettingField(
        key=ConfigKeys.UPDATE_URL,
        label_key="label_server_url",
        field_type=FieldType.TEXT,
        tab="Updates",
        group=None,
        placeholder=Paths.UPDATES_URL,
        default=Paths.UPDATES_URL,
        tooltip_key="tooltip_server_url",
        order=2,
    ),
    SettingField(
        key=ConfigKeys.UPDATE_LOCAL_ROOT,
        label_key="label_local_root",
        field_type=FieldType.PATH_DIR,
        tab="Updates",
        group=None,
        placeholder=r"C:\Projects\VeraCrypt_Yubikey_2FA",
        tooltip_key="tooltip_local_root",
        order=3,
    ),
    # =========================================================================
    # Advanced Tab
    # =========================================================================
    # CHG-20251222-013: Verification/Integrity fields moved to Integrity tab
    # for consolidation (user feedback: redundancy in settings tabs)
    SettingField(
        key=ConfigKeys.SALT_B64,
        label_key="label_salt_b64",
        field_type=FieldType.READONLY,
        tab="Advanced",
        group="GPG KDF Parameters",
        readonly=True,
        tooltip_key="tooltip_salt_b64",
        visibility_condition=show_if_gpg_mode,
        order=10,
    ),
    SettingField(
        key=ConfigKeys.HKDF_INFO,
        label_key="label_hkdf_info",
        field_type=FieldType.TEXT,
        tab="Advanced",
        group="GPG KDF Parameters",
        tooltip_key="tooltip_hkdf_info",
        visibility_condition=show_if_gpg_mode,
        order=11,
    ),
    SettingField(
        key=ConfigKeys.SCHEMA_VERSION,
        label_key="label_schema_version",
        field_type=FieldType.READONLY,
        tab="Advanced",
        group="Metadata",
        readonly=True,
        order=20,
    ),
    # CHG-20251224-001: VERSION field removed from Advanced tab
    # Version info is shown in General → About section to avoid redundancy
    # User feedback: "at least two different sites where the version and stuff is denoted"
    # =========================================================================
    # Integrity Tab (CHG-20251220-002)
    # Provides GUI access to integrity verification and signing operations
    # CHG-20251222-013: Consolidated all integrity-related fields here
    # =========================================================================
    SettingField(
        key="integrity_placeholder",
        label_key="label_integrity_status",
        field_type=FieldType.READONLY,
        tab="Integrity",
        group="Software Integrity",
        readonly=True,
        tooltip_key="tooltip_integrity_status",
        order=1,
    ),
    # CHG-20251222-013: Moved from Advanced tab - Verification override
    SettingField(
        key=ConfigKeys.VERIFICATION_OVERRIDDEN,
        label_key="label_verification_overridden",
        field_type=FieldType.BOOLEAN,
        tab="Integrity",
        group="Verification Status",
        default=False,
        tooltip_key="tooltip_verification_overridden",
        order=5,
    ),
    # CHG-20251222-013: Moved from Advanced tab - Signature status
    SettingField(
        key=ConfigKeys.INTEGRITY_SIGNED,
        label_key="label_integrity_signed",
        field_type=FieldType.READONLY,
        tab="Integrity",
        group="Verification Status",
        readonly=True,
        tooltip_key="tooltip_integrity_signed",
        order=6,
    ),
    # CHG-20251222-013: Moved from Advanced tab - Signing key fingerprint
    SettingField(
        key=ConfigKeys.SIGNING_KEY_FPR,
        label_key="label_signing_key_fpr",
        field_type=FieldType.READONLY,
        tab="Integrity",
        group="Verification Status",
        readonly=True,
        tooltip_key="tooltip_signing_key_fpr",
        order=7,
    ),
    # CHG-20251221-002: Remote verification server URL
    SettingField(
        key=ConfigKeys.INTEGRITY_SERVER_URL,
        label_key="label_integrity_server_url",
        field_type=FieldType.TEXT,
        tab="Integrity",
        group="Remote Verification",
        placeholder=Paths.INTEGRITY_URL,
        default=Paths.INTEGRITY_URL,
        tooltip_key="tooltip_integrity_server_url",
        order=10,
    ),
]


# =============================================================================
# Schema Query Functions
# =============================================================================


def get_fields_for_tab(tab_name: str) -> List[SettingField]:
    """Get all fields for a specific tab, sorted by order."""
    fields = [f for f in SETTINGS_SCHEMA if f.tab == tab_name]
    return sorted(fields, key=lambda f: f.order)


def get_all_tabs() -> List[str]:
    """Get list of all tab names in order."""
    tabs = []
    seen = set()
    for field in SETTINGS_SCHEMA:
        if field.tab not in seen:
            tabs.append(field.tab)
            seen.add(field.tab)
    return tabs


def get_field_by_key(key: str, nested_path: Optional[List[str]] = None) -> Optional[SettingField]:
    """Find field by ConfigKey and optional nested path."""
    for field in SETTINGS_SCHEMA:
        if field.key == key and field.nested_path == nested_path:
            return field
    return None
