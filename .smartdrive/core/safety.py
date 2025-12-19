# core/safety.py - SINGLE SOURCE OF TRUTH for setup safety guardrails
"""
SetupSafetyPolicy prevents destructive operations on critical disks.

This module provides:
- Source disk detection (disk hosting the running setup script)
- Target disk validation before any destructive operation
- Extensible policy for different setup types

Per AGENT_ARCHITECTURE.md Section 2.5:
- No hardcoded partition numbers or device paths
- Explicit safety gates before destructive operations

CRITICAL: This module MUST be checked before any repartitioning, formatting,
or destructive disk operation. The validate_target() method is the ONLY
approved way to confirm a target disk is safe.
"""

import logging
import platform as stdlib_platform  # Avoid conflict with core/platform.py
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Tuple

_safety_logger = logging.getLogger('SmartDrive.safety')


# =============================================================================
# Enums
# =============================================================================

class SetupType(Enum):
    """
    Types of setup operations with different risk profiles.
    
    - DESTRUCTIVE_DISK: Full disk partitioning (wipes entire disk)
    - CONTAINER_FILE: VeraCrypt container file (non-destructive to disk)
    - FOLDER_MODE: Encrypted folder (no disk-level operations)
    """
    DESTRUCTIVE_DISK = auto()  # Repartition entire disk - HIGHEST RISK
    CONTAINER_FILE = auto()     # Create container file on existing partition
    FOLDER_MODE = auto()        # Folder-based encryption (future)


class SafetyBlockReason(Enum):
    """Reasons why a target may be blocked."""
    SOURCE_DISK_MATCH = "Target disk is the same as source disk (setup is running from here)"
    SYSTEM_DISK = "Target disk contains system/boot partitions"
    INVALID_DISK_ID = "Invalid disk identifier provided"
    READ_ONLY_DISK = "Disk is marked as read-only"
    INSUFFICIENT_SIZE = "Disk is too small for setup"


# =============================================================================
# Safety Validation Result
# =============================================================================

@dataclass
class SafetyValidationResult:
    """
    Result of a safety validation check.
    
    Use .is_safe to check if operation can proceed.
    Use .block_reason for user-facing error message if blocked.
    """
    is_safe: bool
    block_reason: Optional[SafetyBlockReason] = None
    details: Optional[str] = None
    
    @classmethod
    def ok(cls) -> "SafetyValidationResult":
        """Return a safe/OK result."""
        return cls(is_safe=True)
    
    @classmethod
    def block(cls, reason: SafetyBlockReason, details: str = "") -> "SafetyValidationResult":
        """Return a blocked result with reason."""
        return cls(is_safe=False, block_reason=reason, details=details)
    
    def __bool__(self) -> bool:
        """Allow use in boolean context: if result: ..."""
        return self.is_safe
    
    def format_error(self) -> str:
        """Format a user-friendly error message."""
        if self.is_safe:
            return ""
        msg = f"⛔ SAFETY BLOCK: {self.block_reason.value}"
        if self.details:
            msg += f"\n   Details: {self.details}"
        return msg


# =============================================================================
# Disk Identity
# =============================================================================

@dataclass
class DiskIdentity:
    """
    Persistent identity of a disk across reboots and remounts.
    
    On Windows: Uses disk UniqueId (GPT GUID or MBR signature)
    On Unix: Uses /dev/disk/by-id or similar
    
    CRITICAL: disk_number is VOLATILE (can change between reboots, especially USB).
    unique_id is the ONLY field used for identity comparison.
    
    Fields:
        unique_id: Persistent identifier (REQUIRED for comparison)
        disk_number: Windows disk number (volatile, for display only)
        device_path: Unix /dev/sdX (volatile, for display only)
        friendly_name: Human-readable name (for user messages)
        serial_number: Drive serial (additional verification)
        bus_type: Connection type (USB, SATA, NVMe, etc.)
    """
    unique_id: str  # Persistent identifier (REQUIRED)
    disk_number: Optional[int] = None  # Windows disk number (VOLATILE)
    device_path: Optional[str] = None  # Unix /dev/sdX (VOLATILE)
    friendly_name: Optional[str] = None  # Human-readable name
    serial_number: Optional[str] = None  # Drive serial (if available)
    bus_type: Optional[str] = None  # USB, SATA, NVMe, etc.
    
    def matches(self, other: "DiskIdentity") -> bool:
        """
        Check if two identities refer to the same physical disk.
        
        CRITICAL: Uses unique_id ONLY. disk_number is NOT used for comparison
        because it can change between reboots (especially for USB drives).
        """
        if not self.unique_id or not other.unique_id:
            _safety_logger.warning("Cannot match disks without unique_id")
            return False
        
        # Normalize for comparison (case-insensitive, strip whitespace)
        self_id = self.unique_id.strip().lower()
        other_id = other.unique_id.strip().lower()
        
        match_result = self_id == other_id
        _safety_logger.debug(
            f"Identity comparison: '{self_id[:20]}...' vs '{other_id[:20]}...' = {match_result}"
        )
        return match_result
    
    def to_log_dict(self) -> dict:
        """Return dictionary for structured logging (sanitized for privacy)."""
        return {
            "unique_id": self.unique_id[:30] + "..." if len(self.unique_id) > 30 else self.unique_id,
            "disk_number": self.disk_number,
            "bus_type": self.bus_type,
            "friendly_name": self.friendly_name,
        }


# =============================================================================
# Source Disk Detection
# =============================================================================

def detect_source_disk_windows(script_path: Path) -> Optional[DiskIdentity]:
    r"""
    Detect the disk that the setup script is running from on Windows.
    
    Args:
        script_path: Path to the running script (__file__)
        
    Returns:
        DiskIdentity of the source disk, or None if detection fails
        
    In development mode (running from C:\Users\...), returns the OS disk.
    In deployed mode (running from USB), returns the USB disk.
    """
    script_path = Path(script_path).resolve()
    
    # Get drive letter from script path
    if not script_path.parts:
        _safety_logger.error("Cannot determine drive from empty script path")
        return None
    
    drive_letter = script_path.parts[0].rstrip(":\\")  # "C:" -> "C"
    
    _safety_logger.debug(f"Detecting source disk for drive {drive_letter}:")
    
    # PowerShell to find disk info from drive letter
    # Include BusType for diagnostics (USB vs SATA vs NVMe)
    ps_script = f"""
    $partition = Get-Partition -DriveLetter '{drive_letter}' -ErrorAction SilentlyContinue
    if ($partition) {{
        $disk = Get-Disk -Number $partition.DiskNumber
        @{{
            DiskNumber = $disk.Number
            UniqueId = $disk.UniqueId
            SerialNumber = $disk.SerialNumber
            FriendlyName = $disk.FriendlyName
            BusType = $disk.BusType.ToString()
            IsSystem = $disk.IsSystem
            IsBoot = $disk.IsBoot
        }} | ConvertTo-Json
    }} else {{
        @{{ Error = "Could not find partition for drive letter" }} | ConvertTo-Json
    }}
    """
    
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            _safety_logger.error(f"PowerShell failed: {result.stderr}")
            return None
        
        import json
        data = json.loads(result.stdout)
        
        if "Error" in data:
            _safety_logger.error(f"Source disk detection failed: {data['Error']}")
            return None
        
        identity = DiskIdentity(
            unique_id=data.get("UniqueId", ""),
            disk_number=data.get("DiskNumber"),
            friendly_name=data.get("FriendlyName"),
            serial_number=data.get("SerialNumber"),
            bus_type=data.get("BusType")
        )
        
        _safety_logger.info(
            f"Source disk detected: #{identity.disk_number} "
            f"'{identity.friendly_name}' BusType={identity.bus_type} "
            f"UniqueId={identity.unique_id[:20]}..."
        )
        
        return identity
        
    except subprocess.TimeoutExpired:
        _safety_logger.error("Timeout detecting source disk")
        return None
    except json.JSONDecodeError as e:
        _safety_logger.error(f"Failed to parse disk info: {e}")
        return None
    except Exception as e:
        _safety_logger.error(f"Source disk detection failed: {e}")
        return None


def detect_source_disk_unix(script_path: Path) -> Optional[DiskIdentity]:
    """
    Detect the disk that the setup script is running from on Unix/Linux.
    
    Args:
        script_path: Path to the running script (__file__)
        
    Returns:
        DiskIdentity of the source disk, or None if detection fails
    """
    script_path = Path(script_path).resolve()
    
    try:
        # Use df to find the mount point and device
        result = subprocess.run(
            ["df", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            _safety_logger.error(f"df command failed: {result.stderr}")
            return None
        
        # Parse df output (second line, first column is device)
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return None
        
        device = lines[1].split()[0]  # e.g., /dev/sda1
        
        # Extract base device (remove partition number)
        import re
        base_device_match = re.match(r'(/dev/[a-z]+)', device)
        if not base_device_match:
            # Try nvme pattern
            base_device_match = re.match(r'(/dev/nvme\d+n\d+)', device)
        
        base_device = base_device_match.group(1) if base_device_match else device
        
        # Try to get unique ID from /dev/disk/by-id
        unique_id = None
        by_id_path = Path("/dev/disk/by-id")
        if by_id_path.exists():
            for link in by_id_path.iterdir():
                if link.is_symlink():
                    target = link.resolve()
                    if str(target) == base_device:
                        unique_id = link.name
                        break
        
        if not unique_id:
            # Fallback to using device path as ID (less reliable)
            unique_id = base_device
            _safety_logger.warning(f"Using device path as unique_id: {unique_id}")
        
        identity = DiskIdentity(
            unique_id=unique_id,
            device_path=base_device,
            friendly_name=base_device
        )
        
        _safety_logger.info(f"Source disk detected: {identity.device_path} ({identity.unique_id})")
        
        return identity
        
    except Exception as e:
        _safety_logger.error(f"Source disk detection failed: {e}")
        return None


def detect_source_disk(script_path: Path) -> Optional[DiskIdentity]:
    """
    Platform-agnostic source disk detection.
    
    Args:
        script_path: Path to the running script (__file__)
        
    Returns:
        DiskIdentity of the disk hosting the script, or None if detection fails
    """
    system = stdlib_platform.system().lower()
    
    if system == "windows":
        return detect_source_disk_windows(script_path)
    else:
        return detect_source_disk_unix(script_path)


# =============================================================================
# Target Disk Identity Extraction  
# =============================================================================

def get_target_disk_identity_windows(disk_number: int) -> Optional[DiskIdentity]:
    """
    Get the identity of a target disk by its Windows disk number.
    
    Args:
        disk_number: Windows disk number from Get-Disk
        
    Returns:
        DiskIdentity for the disk, or None if not found
        
    Note: disk_number is used only to locate the disk. The returned
    DiskIdentity uses unique_id for all comparison operations.
    """
    ps_script = f"""
    $disk = Get-Disk -Number {disk_number} -ErrorAction SilentlyContinue
    if ($disk) {{
        @{{
            DiskNumber = $disk.Number
            UniqueId = $disk.UniqueId
            SerialNumber = $disk.SerialNumber
            FriendlyName = $disk.FriendlyName
            BusType = $disk.BusType.ToString()
            IsSystem = $disk.IsSystem
            IsBoot = $disk.IsBoot
            IsReadOnly = $disk.IsReadOnly
            Size = $disk.Size
        }} | ConvertTo-Json
    }} else {{
        @{{ Error = "Disk not found" }} | ConvertTo-Json
    }}
    """
    
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            _safety_logger.error(f"PowerShell failed: {result.stderr}")
            return None
        
        import json
        data = json.loads(result.stdout)
        
        if "Error" in data:
            _safety_logger.error(f"Target disk lookup failed: {data['Error']}")
            return None
        
        identity = DiskIdentity(
            unique_id=data.get("UniqueId", ""),
            disk_number=data.get("DiskNumber"),
            friendly_name=data.get("FriendlyName"),
            serial_number=data.get("SerialNumber"),
            bus_type=data.get("BusType")
        )
        
        _safety_logger.info(
            f"Target disk identity: #{identity.disk_number} "
            f"'{identity.friendly_name}' BusType={identity.bus_type} "
            f"UniqueId={identity.unique_id[:20]}..."
        )
        
        return identity
        
    except Exception as e:
        _safety_logger.error(f"Target disk identity lookup failed: {e}")
        return None


def get_target_disk_identity_unix(device_path: str) -> Optional[DiskIdentity]:
    """
    Get the identity of a target disk by its Unix device path.
    
    Args:
        device_path: Unix device path (e.g., /dev/sdb)
        
    Returns:
        DiskIdentity for the disk, or None if not found
    """
    try:
        device = Path(device_path)
        if not device.exists():
            _safety_logger.error(f"Device not found: {device_path}")
            return None
        
        # Try to find unique ID from /dev/disk/by-id
        unique_id = None
        by_id_path = Path("/dev/disk/by-id")
        if by_id_path.exists():
            for link in by_id_path.iterdir():
                if link.is_symlink():
                    target = link.resolve()
                    if str(target) == str(device.resolve()):
                        unique_id = link.name
                        break
        
        if not unique_id:
            unique_id = device_path
        
        return DiskIdentity(
            unique_id=unique_id,
            device_path=device_path,
            friendly_name=device_path
        )
        
    except Exception as e:
        _safety_logger.error(f"Target disk identity lookup failed: {e}")
        return None


# =============================================================================
# SetupSafetyPolicy - Main Safety Gate
# =============================================================================

class SetupSafetyPolicy:
    """
    SINGLE SOURCE OF TRUTH for setup safety validation.
    
    Call validate_target() before ANY destructive disk operation.
    
    Usage:
        policy = SetupSafetyPolicy(setup_type=SetupType.DESTRUCTIVE_DISK)
        result = policy.validate_target(source_disk, target_disk)
        if not result:
            print(result.format_error())
            return  # ABORT
        # Proceed with operation
    """
    
    def __init__(self, setup_type: SetupType = SetupType.DESTRUCTIVE_DISK):
        """
        Initialize safety policy.
        
        Args:
            setup_type: Type of setup operation being performed
        """
        self.setup_type = setup_type
        _safety_logger.debug(f"SetupSafetyPolicy created for {setup_type.name}")
    
    def validate_target(
        self,
        source_disk: Optional[DiskIdentity],
        target_disk: Optional[DiskIdentity]
    ) -> SafetyValidationResult:
        """
        Validate that a target disk is safe for the setup operation.
        
        Args:
            source_disk: Identity of the disk setup is running from
            target_disk: Identity of the disk to be modified
            
        Returns:
            SafetyValidationResult indicating if operation can proceed
            
        CRITICAL: This is the ONLY approved way to validate disk targets.
        Do NOT bypass this method.
        
        IMPORTANT: Comparison uses unique_id ONLY. disk_number is NOT used
        for comparison because it can change between reboots (USB reordering).
        """
        _safety_logger.info("=" * 70)
        _safety_logger.info("SAFETY VALIDATION - DISK IDENTITY CHECK")
        _safety_logger.info("=" * 70)
        _safety_logger.info(f"Setup type: {self.setup_type.name}")
        
        # Log full source disk details
        _safety_logger.info("SOURCE DISK (where setup.py is running from):")
        if source_disk:
            _safety_logger.info(f"  unique_id: {source_disk.unique_id}")
            _safety_logger.info(f"  disk_number: {source_disk.disk_number} (VOLATILE - not used for comparison)")
            _safety_logger.info(f"  bus_type: {source_disk.bus_type}")
            _safety_logger.info(f"  friendly_name: {source_disk.friendly_name}")
        else:
            _safety_logger.info("  UNKNOWN - could not detect source disk")
        
        # Log full target disk details
        _safety_logger.info("TARGET DISK (selected for partitioning):")
        if target_disk:
            _safety_logger.info(f"  unique_id: {target_disk.unique_id}")
            _safety_logger.info(f"  disk_number: {target_disk.disk_number} (VOLATILE - not used for comparison)")
            _safety_logger.info(f"  bus_type: {target_disk.bus_type}")
            _safety_logger.info(f"  friendly_name: {target_disk.friendly_name}")
        else:
            _safety_logger.info("  UNKNOWN - invalid target")
        
        _safety_logger.info("-" * 70)
        
        # Validate inputs
        if target_disk is None or not target_disk.unique_id:
            _safety_logger.error("BLOCKED: Invalid target disk identifier")
            return SafetyValidationResult.block(
                SafetyBlockReason.INVALID_DISK_ID,
                "Target disk identity could not be determined"
            )
        
        # For DESTRUCTIVE_DISK, source disk detection is MANDATORY
        if self.setup_type == SetupType.DESTRUCTIVE_DISK:
            if source_disk is None or not source_disk.unique_id:
                _safety_logger.error("BLOCKED: Cannot determine source disk for destructive operation")
                return SafetyValidationResult.block(
                    SafetyBlockReason.INVALID_DISK_ID,
                    "Source disk identity could not be determined. "
                    "Refusing to proceed with destructive operation."
                )
            
            # THE CRITICAL CHECK: Is target.unique_id == source.unique_id?
            # Note: We do NOT compare disk_number because it can change
            _safety_logger.info("IDENTITY COMPARISON (using unique_id only):")
            _safety_logger.info(f"  source.unique_id.lower() = '{source_disk.unique_id.strip().lower()}'")
            _safety_logger.info(f"  target.unique_id.lower() = '{target_disk.unique_id.strip().lower()}'")
            
            if source_disk.matches(target_disk):
                _safety_logger.critical(
                    "🛑 BLOCKED: TARGET DISK IS THE SOURCE DISK! "
                    f"UniqueId={target_disk.unique_id}"
                )
                _safety_logger.info("=" * 70)
                return SafetyValidationResult.block(
                    SafetyBlockReason.SOURCE_DISK_MATCH,
                    f"The selected disk (#{target_disk.disk_number} '{target_disk.friendly_name}') "
                    f"is the same disk that setup.py is running from. "
                    f"Repartitioning this disk would destroy the running system."
                )
            else:
                _safety_logger.info("  RESULT: Different disks ✓")
        
        # Additional checks (less critical but still important)
        # These can be expanded based on setup_type
        
        _safety_logger.info("=" * 70)
        _safety_logger.info("✓ SAFETY VALIDATION PASSED - Target disk is safe to modify")
        _safety_logger.info("=" * 70)
        return SafetyValidationResult.ok()
    
    @classmethod
    def validate_before_partition(
        cls,
        script_path: Path,
        target_disk_number: Optional[int] = None,
        target_device_path: Optional[str] = None
    ) -> SafetyValidationResult:
        """
        Convenience method to validate before partitioning.
        
        Call this from setup.py before partition_drive_*() functions.
        
        Args:
            script_path: Path(__file__) from setup.py
            target_disk_number: Windows disk number (for Windows)
            target_device_path: Unix device path (for Unix)
            
        Returns:
            SafetyValidationResult
        """
        system = stdlib_platform.system().lower()
        policy = cls(setup_type=SetupType.DESTRUCTIVE_DISK)
        
        # Detect source disk
        source_disk = detect_source_disk(script_path)
        
        # Get target disk identity
        if system == "windows" and target_disk_number is not None:
            target_disk = get_target_disk_identity_windows(target_disk_number)
        elif target_device_path:
            target_disk = get_target_disk_identity_unix(target_device_path)
        else:
            _safety_logger.error("No target disk identifier provided")
            return SafetyValidationResult.block(
                SafetyBlockReason.INVALID_DISK_ID,
                "No target disk number or device path provided"
            )
        
        return policy.validate_target(source_disk, target_disk)


# =============================================================================
# Partition Resolver SSOT
# =============================================================================

@dataclass
class PartitionRef:
    """
    Reference to a partition on a disk.
    
    Used by resolve_launcher_partition() and resolve_payload_partition()
    to return consistent, typed partition references.
    """
    disk_number: int
    partition_number: int
    size_gb: float
    drive_letter: Optional[str] = None
    is_hidden: bool = False
    partition_type: Optional[str] = None
    offset: Optional[int] = None
    
    def to_log_dict(self) -> dict:
        """Return dictionary for structured logging."""
        return {
            "disk_number": self.disk_number,
            "partition_number": self.partition_number,
            "size_gb": self.size_gb,
            "drive_letter": self.drive_letter,
            "is_hidden": self.is_hidden,
            "partition_type": self.partition_type,
        }


@dataclass
class DiskSnapshot:
    """
    Complete snapshot of a disk's partition layout for diagnostics.
    
    Use log_disk_snapshot() to generate and log this structure.
    """
    disk_identity: DiskIdentity
    partitions: list  # List of PartitionRef
    volumes: list  # List of volume info dicts
    launcher_partition: Optional[PartitionRef] = None
    payload_partition: Optional[PartitionRef] = None
    
    def log(self) -> None:
        """Log the snapshot in structured format."""
        _safety_logger.info("=" * 70)
        _safety_logger.info("DISK SNAPSHOT - PRE-MOUNT DIAGNOSTIC")
        _safety_logger.info("=" * 70)
        _safety_logger.info(f"Disk Identity: {self.disk_identity.friendly_name}")
        _safety_logger.info(f"  UniqueId: {self.disk_identity.unique_id}")
        _safety_logger.info(f"  BusType: {self.disk_identity.bus_type}")
        _safety_logger.info(f"  DiskNumber: {self.disk_identity.disk_number} (VOLATILE)")
        
        _safety_logger.info("")
        _safety_logger.info("Partitions:")
        for p in self.partitions:
            letter_str = f", Letter={p.drive_letter}" if p.drive_letter else ""
            hidden_str = " [HIDDEN]" if p.is_hidden else ""
            _safety_logger.info(f"  #{p.partition_number}: {p.size_gb:.2f} GB, Type={p.partition_type}{letter_str}{hidden_str}")
        
        _safety_logger.info("")
        _safety_logger.info("Volumes:")
        for v in self.volumes:
            _safety_logger.info(f"  Letter={v.get('letter', 'N/A')}, GUID={v.get('unique_id', 'N/A')[:30]}...")
        
        _safety_logger.info("")
        _safety_logger.info("Resolved References:")
        if self.launcher_partition:
            _safety_logger.info(f"  Launcher: Partition #{self.launcher_partition.partition_number} ({self.launcher_partition.drive_letter or 'no letter'})")
        else:
            _safety_logger.info("  Launcher: NOT RESOLVED")
        if self.payload_partition:
            _safety_logger.info(f"  Payload: Partition #{self.payload_partition.partition_number} ({self.payload_partition.drive_letter or 'no letter'})")
        else:
            _safety_logger.info("  Payload: NOT RESOLVED")
        _safety_logger.info("=" * 70)


def get_disk_snapshot_windows(disk_number: int, launcher_drive_letter: Optional[str] = None) -> Optional[DiskSnapshot]:
    """
    Get a complete snapshot of a disk's partition layout.
    
    Args:
        disk_number: Windows disk number
        launcher_drive_letter: Known launcher partition drive letter (for resolution)
    
    Returns:
        DiskSnapshot with all partition and volume information
    """
    ps_script = f"""
    $disk = Get-Disk -Number {disk_number} -ErrorAction SilentlyContinue
    $partitions = Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue | 
        ForEach-Object {{
            $vol = Get-Volume -Partition $_ -ErrorAction SilentlyContinue
            @{{
                Number = $_.PartitionNumber
                Size = [math]::Round($_.Size / 1GB, 2)
                Type = $_.Type.ToString()
                IsHidden = $_.IsHidden
                DriveLetter = $_.DriveLetter
                Offset = $_.Offset
                VolumeGuid = if ($vol) {{ $vol.UniqueId }} else {{ $null }}
            }}
        }}
    @{{
        DiskNumber = $disk.Number
        UniqueId = $disk.UniqueId
        FriendlyName = $disk.FriendlyName
        BusType = $disk.BusType.ToString()
        SerialNumber = $disk.SerialNumber
        Partitions = @($partitions)
    }} | ConvertTo-Json -Depth 3
    """
    
    try:
        import json
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            _safety_logger.error(f"PowerShell failed: {result.stderr}")
            return None
        
        data = json.loads(result.stdout)
        
        # Build disk identity
        identity = DiskIdentity(
            unique_id=data.get("UniqueId", ""),
            disk_number=data.get("DiskNumber"),
            friendly_name=data.get("FriendlyName"),
            serial_number=data.get("SerialNumber"),
            bus_type=data.get("BusType")
        )
        
        # Build partition refs
        partitions = []
        volumes = []
        for p in data.get("Partitions", []):
            pref = PartitionRef(
                disk_number=disk_number,
                partition_number=p.get("Number"),
                size_gb=p.get("Size", 0),
                drive_letter=p.get("DriveLetter"),
                is_hidden=p.get("IsHidden", False),
                partition_type=p.get("Type"),
                offset=p.get("Offset")
            )
            partitions.append(pref)
            
            if p.get("VolumeGuid"):
                volumes.append({
                    "letter": p.get("DriveLetter"),
                    "unique_id": p.get("VolumeGuid"),
                    "partition_number": p.get("Number")
                })
        
        # Resolve launcher partition (by drive letter or first partition)
        launcher_ref = None
        payload_ref = None
        
        if launcher_drive_letter:
            for p in partitions:
                if p.drive_letter and p.drive_letter.upper() == launcher_drive_letter.upper():
                    launcher_ref = p
                    break
        
        if not launcher_ref and partitions:
            # Fallback: assume first partition is launcher
            launcher_ref = partitions[0]
        
        # Resolve payload partition (largest non-launcher, non-hidden)
        if launcher_ref:
            candidates = [
                p for p in partitions 
                if p.partition_number != launcher_ref.partition_number
                and not p.is_hidden
            ]
            if candidates:
                payload_ref = max(candidates, key=lambda p: p.size_gb)
        
        return DiskSnapshot(
            disk_identity=identity,
            partitions=partitions,
            volumes=volumes,
            launcher_partition=launcher_ref,
            payload_partition=payload_ref
        )
        
    except Exception as e:
        _safety_logger.error(f"Failed to get disk snapshot: {e}")
        return None


def resolve_launcher_partition_windows(
    disk_number: int, 
    drive_root: Optional[Path] = None
) -> Optional[PartitionRef]:
    """
    SSOT: Resolve the launcher partition (where .smartdrive lives).
    
    Args:
        disk_number: Windows disk number
        drive_root: Optional drive root path to help identify launcher
    
    Returns:
        PartitionRef for the launcher partition, or None if not found
    
    Heuristic:
    1. If drive_root provided, find partition with that drive letter
    2. Otherwise, assume first basic partition is launcher
    """
    _safety_logger.info(f"Resolving launcher partition on disk {disk_number}")
    
    if drive_root:
        drive_letter = str(drive_root)[0].upper()
        _safety_logger.info(f"  Drive root provided: {drive_root} -> letter {drive_letter}")
    else:
        drive_letter = None
    
    snapshot = get_disk_snapshot_windows(disk_number, drive_letter)
    if not snapshot:
        return None
    
    if snapshot.launcher_partition:
        _safety_logger.info(
            f"  RESOLVED: Launcher = Partition #{snapshot.launcher_partition.partition_number} "
            f"({snapshot.launcher_partition.drive_letter or 'no letter'})"
        )
    
    return snapshot.launcher_partition


def resolve_payload_partition_windows(
    disk_number: int,
    launcher_partition: Optional[PartitionRef] = None
) -> Optional[PartitionRef]:
    """
    SSOT: Resolve the payload partition (for VeraCrypt volume).
    
    Args:
        disk_number: Windows disk number
        launcher_partition: Already-resolved launcher partition (for exclusion)
    
    Returns:
        PartitionRef for the payload partition, or None if not found
    
    Heuristic:
    1. Exclude launcher partition (by partition number)
    2. Exclude hidden partitions
    3. Choose largest remaining basic/data partition
    
    NO HARDCODED PARTITION NUMBERS. This function discovers the payload.
    """
    _safety_logger.info(f"Resolving payload partition on disk {disk_number}")
    
    launcher_letter = launcher_partition.drive_letter if launcher_partition else None
    snapshot = get_disk_snapshot_windows(disk_number, launcher_letter)
    if not snapshot:
        return None
    
    if snapshot.payload_partition:
        _safety_logger.info(
            f"  RESOLVED: Payload = Partition #{snapshot.payload_partition.partition_number} "
            f"(exclude launcher #{launcher_partition.partition_number if launcher_partition else 'N/A'}; "
            f"choose largest remaining: {snapshot.payload_partition.size_gb:.2f} GB)"
        )
    else:
        _safety_logger.warning("  FAILED: No payload partition found")
    
    return snapshot.payload_partition


# =============================================================================
# Test/Demo (run this file directly)
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.DEBUG)
    
    print("=" * 60)
    print("SetupSafetyPolicy Test")
    print("=" * 60)
    
    # Detect source disk
    source = detect_source_disk(Path(__file__))
    if source:
        print(f"\nSource disk detected:")
        print(f"  UniqueId: {source.unique_id}")
        print(f"  Number: {source.disk_number}")
        print(f"  Name: {source.friendly_name}")
        print(f"  Serial: {source.serial_number}")
    else:
        print("\nFailed to detect source disk!")
        sys.exit(1)
    
    # Simulate validation (using source as target = should BLOCK)
    print("\n--- Testing self-destruction block ---")
    policy = SetupSafetyPolicy(SetupType.DESTRUCTIVE_DISK)
    result = policy.validate_target(source, source)
    
    if not result.is_safe:
        print(f"\n✓ Correctly blocked: {result.format_error()}")
    else:
        print("\n✗ ERROR: Should have blocked self-destruction!")
        sys.exit(1)
    
    print("\n✓ Safety policy working correctly!")
