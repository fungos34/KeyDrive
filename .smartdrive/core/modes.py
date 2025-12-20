# core/modes.py - SINGLE SOURCE OF TRUTH for enums and state definitions
"""
All mode enums, state definitions, and outcome types MUST be defined here.
No other module may define these values.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional


# =============================================================================
# Volume Identifier (SSOT for volume resolution)
# =============================================================================

class VolumeIdentifierKind(str, Enum):
    """
    Kind of volume identifier.
    
    MANDATORY per AGENT_ARCHITECTURE.md:
    - DRIVE_LETTER and VOLUME_GUID are CONFIRMED identifiers (persistable)
    - DEVICE_PATH is TRANSIENT input only (NEVER persist as resolved)
    """
    
    DRIVE_LETTER = "drive_letter"   # e.g., "E:" - confirmed, persistable
    VOLUME_GUID = "volume_guid"     # e.g., "\\?\Volume{...}\" - confirmed, persistable
    DEVICE_PATH = "device_path"     # e.g., "\Device\Harddisk1\Partition2" - TRANSIENT ONLY


@dataclass
class VolumeIdentifier:
    """
    Strict volume identifier model.
    
    MANDATORY RULES (per AGENT_ARCHITECTURE.md):
    1. kind must be one of VolumeIdentifierKind values
    2. DEVICE_PATH kind is NEVER persistable - only for transient input
    3. Only DRIVE_LETTER or VOLUME_GUID may be persisted to config
    4. resolution_method documents HOW the identifier was obtained
    
    Usage:
        # From drive letter (already confirmed)
        vid = VolumeIdentifier.from_drive_letter("E")
        
        # From resolution (must be confirmed)
        vid = VolumeIdentifier(
            kind=VolumeIdentifierKind.VOLUME_GUID,
            value="\\\\?\\Volume{abc-123}\\",
            resolution_method="wmi_query"
        )
        
        # Check if persistable
        if vid.is_persistable:
            config["volume_id"] = vid.to_config()
    """
    
    kind: VolumeIdentifierKind
    value: str
    resolution_method: Optional[str] = None  # How this was resolved (for logging)
    
    @property
    def is_persistable(self) -> bool:
        """
        Whether this identifier can be persisted to config.
        
        DEVICE_PATH is NEVER persistable - it's transient input only.
        """
        return self.kind != VolumeIdentifierKind.DEVICE_PATH
    
    @property
    def is_device_path(self) -> bool:
        """Whether this is a device path (transient, not resolvable)."""
        return self.kind == VolumeIdentifierKind.DEVICE_PATH
    
    @property
    def is_confirmed(self) -> bool:
        """Whether this identifier has been confirmed by the OS."""
        return self.is_persistable and self.resolution_method is not None
    
    def to_veracrypt_arg(self) -> str:
        """
        Get the value formatted for VeraCrypt /volume argument.
        
        Raises:
            ValueError: If this is a device path (not resolvable)
        """
        if self.is_device_path:
            raise ValueError(
                f"Cannot use device path '{self.value}' with VeraCrypt. "
                f"Must resolve to drive letter or volume GUID first."
            )
        return self.value
    
    def to_config(self) -> dict:
        """
        Serialize to config dict format.
        
        Raises:
            ValueError: If not persistable (device path)
        """
        if not self.is_persistable:
            raise ValueError(
                f"Cannot persist {self.kind.value} identifier '{self.value}' to config. "
                f"Only drive_letter and volume_guid are allowed."
            )
        return {
            "kind": self.kind.value,
            "value": self.value,
            "resolution_method": self.resolution_method
        }
    
    @classmethod
    def from_config(cls, data: dict) -> "VolumeIdentifier":
        """Load from config dict. Validates kind is persistable."""
        kind = VolumeIdentifierKind(data["kind"])
        if kind == VolumeIdentifierKind.DEVICE_PATH:
            raise ValueError(
                f"Invalid config: device_path is not a valid persisted identifier kind. "
                f"Config corruption detected."
            )
        return cls(
            kind=kind,
            value=data["value"],
            resolution_method=data.get("resolution_method")
        )
    
    @classmethod
    def from_drive_letter(cls, letter: str, resolution_method: str = "explicit") -> "VolumeIdentifier":
        """Create from a drive letter (e.g., 'E' or 'E:')."""
        # Normalize: ensure single letter uppercase with colon
        normalized = letter.strip().upper().rstrip(":")
        if len(normalized) != 1 or not normalized.isalpha():
            raise ValueError(f"Invalid drive letter: '{letter}'")
        return cls(
            kind=VolumeIdentifierKind.DRIVE_LETTER,
            value=f"{normalized}:",
            resolution_method=resolution_method
        )
    
    @classmethod
    def from_volume_guid(cls, guid_path: str, resolution_method: str = "explicit") -> "VolumeIdentifier":
        r"""Create from a volume GUID path (e.g., '\\?\Volume{...}\')."""
        if not guid_path.startswith("\\\\?\\Volume{"):
            raise ValueError(f"Invalid volume GUID path: '{guid_path}'")
        return cls(
            kind=VolumeIdentifierKind.VOLUME_GUID,
            value=guid_path,
            resolution_method=resolution_method
        )
    
    @classmethod
    def from_device_path(cls, device_path: str) -> "VolumeIdentifier":
        """
        Create a TRANSIENT device path identifier.
        
        WARNING: This is for input parsing only. NEVER persist or treat as resolved.
        """
        return cls(
            kind=VolumeIdentifierKind.DEVICE_PATH,
            value=device_path,
            resolution_method=None  # Explicitly None - not resolved
        )
    
    def __str__(self) -> str:
        status = "confirmed" if self.is_confirmed else ("transient" if self.is_device_path else "unconfirmed")
        return f"VolumeIdentifier({self.kind.value}: {self.value}, {status})"


# =============================================================================
# Security Modes
# =============================================================================

# Module-level flag for secrets availability (cannot be Enum attribute due to immutability)
_SECRETS_AVAILABLE = False

class SecurityMode(str, Enum):
    """
    Security mode for SmartDrive setup.
    Determines authentication requirements.
    
    String enum for JSON serialization compatibility.
    """
    
    PW_ONLY = "pw_only"           # Password only, no keyfile
    PW_KEYFILE = "pw_keyfile"      # Password + plain keyfile
    PW_GPG_KEYFILE = "pw_gpg_keyfile"  # Password + GPG-encrypted keyfile (YubiKey)
    GPG_PW_ONLY = "gpg_pw_only"    # GPG-derived password (YubiKey, no separate keyfile)
    
    @property
    def display_name(self) -> str:
        """Human-readable display name for UI."""
        return SECURITY_MODE_DISPLAY.get(self, self.value)
    
    @property
    def requires_yubikey(self) -> bool:
        """Whether this mode requires a YubiKey."""
        return self in (SecurityMode.PW_GPG_KEYFILE, SecurityMode.GPG_PW_ONLY)
    
    @property
    def requires_keyfile(self) -> bool:
        """Whether this mode requires a keyfile."""
        return self in (SecurityMode.PW_KEYFILE, SecurityMode.PW_GPG_KEYFILE)
    
    @classmethod
    def from_config(cls, mode_str: str) -> "SecurityMode":
        """Parse security mode from config string."""
        try:
            return cls(mode_str)
        except ValueError:
            # Legacy compatibility
            if mode_str == "yubikey":
                return cls.PW_GPG_KEYFILE
            if mode_str == "keyfile":
                return cls.PW_KEYFILE
            raise ValueError(f"Unknown security mode: {mode_str}")


# Display names for security modes
SECURITY_MODE_DISPLAY: Dict[SecurityMode, str] = {
    SecurityMode.PW_ONLY: "🔒 Password Only",
    SecurityMode.PW_KEYFILE: "🔑 Keyfile + Password",
    SecurityMode.PW_GPG_KEYFILE: "🔐 YubiKey + Password",
    SecurityMode.GPG_PW_ONLY: "🔐 GPG Encrypted Password",
}


# =============================================================================
# Setup Phases
# =============================================================================

class SetupPhase(Enum):
    """Setup wizard phases."""
    
    PREREQUISITES = auto()
    DEVICE_SELECTION = auto()
    SECURITY_OPTIONS = auto()
    VOLUME_CREATION = auto()
    VERIFICATION = auto()
    COMPLETE = auto()


# =============================================================================
# Recovery Outcomes
# =============================================================================

class RecoveryOutcome(str, Enum):
    """
    Outcome of a recovery operation.
    String enum for audit logging.
    """
    
    # Success outcomes
    SUCCESS = "success"
    SUCCESS_WITH_REKEY = "success_with_rekey"
    
    # Failure outcomes
    ABORTED_BY_USER = "aborted_by_user"
    ABORTED_PREFLIGHT = "aborted_preflight"
    ABORTED_VOLUME_MISMATCH = "aborted_volume_mismatch"
    FAILED_DECRYPTION = "failed_decryption"
    FAILED_MOUNT = "failed_mount"
    FAILED_SHARE_VALIDATION = "failed_share_validation"
    FAILED_PHRASE_VALIDATION = "failed_phrase_validation"
    FAILED_UNKNOWN = "failed_unknown"
    
    # Partial outcomes
    PARTIAL_EMERGENCY_ACCESS = "partial_emergency_access"
    
    @property
    def is_success(self) -> bool:
        """Whether this outcome represents a successful recovery."""
        return self in (RecoveryOutcome.SUCCESS, RecoveryOutcome.SUCCESS_WITH_REKEY)
    
    @property
    def is_failure(self) -> bool:
        """Whether this outcome represents a failed recovery."""
        return self.value.startswith("failed_")
    
    @property
    def is_aborted(self) -> bool:
        """Whether this outcome represents an aborted recovery."""
        return self.value.startswith("aborted_")


# =============================================================================
# Mount Status
# =============================================================================

class MountStatus(str, Enum):
    """Status of a mounted volume."""
    
    MOUNTED = "mounted"
    UNMOUNTED = "unmounted"
    UNKNOWN = "unknown"
    ERROR = "error"


# =============================================================================
# Update Source Types
# =============================================================================

class UpdateSourceType(str, Enum):
    """Source types for update operations."""
    
    GITHUB = "github"
    LOCAL = "local"
    NONE = "none"


# =============================================================================
# Audit Event Types
# =============================================================================

class AuditEvent(str, Enum):
    """Audit log event types."""
    
    # Setup events
    SETUP_STARTED = "setup_started"
    SETUP_COMPLETED = "setup_completed"
    SETUP_FAILED = "setup_failed"
    
    # Mount events
    MOUNT_STARTED = "mount_started"
    MOUNT_SUCCESS = "mount_success"
    MOUNT_FAILED = "mount_failed"
    
    # Unmount events
    UNMOUNT_STARTED = "unmount_started"
    UNMOUNT_SUCCESS = "unmount_success"
    UNMOUNT_FAILED = "unmount_failed"
    
    # Recovery events
    RECOVERY_STARTED = "recovery_started"
    RECOVERY_SUCCESS = "recovery_success"
    RECOVERY_FAILED = "recovery_failed"
    RECOVERY_ABORTED = "recovery_aborted"
    
    # Rekey events
    REKEY_STARTED = "rekey_started"
    REKEY_SUCCESS = "rekey_success"
    REKEY_FAILED = "rekey_failed"
    
    # Security events
    YUBIKEY_DETECTED = "yubikey_detected"
    YUBIKEY_NOT_FOUND = "yubikey_not_found"
    GPG_DECRYPT_SUCCESS = "gpg_decrypt_success"
    GPG_DECRYPT_FAILED = "gpg_decrypt_failed"
    INTEGRITY_CHECK_PASSED = "integrity_check_passed"
    INTEGRITY_CHECK_FAILED = "integrity_check_failed"
