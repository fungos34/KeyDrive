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

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Any
from core.constants import ConfigKeys
from core.modes import SecurityMode


# =============================================================================
# Field Types
# =============================================================================

class FieldType(Enum):
    """Widget type for settings field."""
    TEXT = "text"           # QLineEdit
    PATH_FILE = "path_file" # QLineEdit + Browse button (file)
    PATH_DIR = "path_dir"   # QLineEdit + Browse button (directory)
    NUMBER = "number"       # QSpinBox
    BOOLEAN = "boolean"     # QCheckBox
    DROPDOWN = "dropdown"   # QComboBox
    TEXTAREA = "textarea"   # QTextEdit (multiline)
    READONLY = "readonly"   # QLabel (display only)


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
    if len(value) != 1 or not ('A' <= value <= 'Z'):
        return False, "Mount letter must be a single letter (A-Z)"
    return True, ""


def validate_uuid(value: str) -> tuple[bool, str]:
    """Validate UUIDv4 format."""
    if not value:
        return True, ""
    import re
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
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
            ("Password Only", SecurityMode.PW_ONLY.value),
            ("Password + Keyfile", SecurityMode.PW_KEYFILE.value),
            ("GPG Password-Only (YubiKey)", SecurityMode.GPG_PW_ONLY.value),
            ("Password + GPG Keyfile (YubiKey)", SecurityMode.PW_GPG_KEYFILE.value),
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
    
    SettingField(
        key=ConfigKeys.VERACRYPT_PATH,
        label_key="label_veracrypt_path",
        field_type=FieldType.PATH_FILE,
        tab="Windows",
        group=None,
        nested_path=[ConfigKeys.WINDOWS, ConfigKeys.VERACRYPT_PATH],
        placeholder=r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
        tooltip_key="tooltip_veracrypt_path",
        order=3,
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
    
    # =========================================================================
    # Recovery Tab
    # =========================================================================
    
    SettingField(
        key=ConfigKeys.RECOVERY_ENABLED,
        label_key="label_recovery_enabled",
        field_type=FieldType.BOOLEAN,
        tab="Recovery",
        group="Emergency Recovery Kit",
        nested_path=[ConfigKeys.RECOVERY, ConfigKeys.RECOVERY_ENABLED],
        default=False,
        tooltip_key="tooltip_recovery_enabled",
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
        tab="Lost & Found",
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
        tab="Lost & Found",
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
        placeholder="https://updates.example.com/smartdrive",
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
    
    SettingField(
        key=ConfigKeys.VERIFICATION_OVERRIDDEN,
        label_key="label_verification_overridden",
        field_type=FieldType.BOOLEAN,
        tab="Advanced",
        group="Verification",
        default=False,
        tooltip_key="tooltip_verification_overridden",
        order=1,
    ),
    
    SettingField(
        key=ConfigKeys.INTEGRITY_SIGNED,
        label_key="label_integrity_signed",
        field_type=FieldType.READONLY,
        tab="Advanced",
        group="Verification",
        readonly=True,
        tooltip_key="tooltip_integrity_signed",
        order=2,
    ),
    
    SettingField(
        key=ConfigKeys.SIGNING_KEY_FPR,
        label_key="label_signing_key_fpr",
        field_type=FieldType.READONLY,
        tab="Advanced",
        group="Verification",
        readonly=True,
        tooltip_key="tooltip_signing_key_fpr",
        order=3,
    ),
    
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
    
    SettingField(
        key=ConfigKeys.VERSION,
        label_key="label_version",
        field_type=FieldType.READONLY,
        tab="Advanced",
        group="Metadata",
        readonly=True,
        order=21,
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
