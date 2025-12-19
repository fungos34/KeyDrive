# core/limits.py - SINGLE SOURCE OF TRUTH for retry counts, timeouts, thresholds
"""
All numeric limits, timeouts, and thresholds MUST be defined here.
No other module may define these values.
"""


class Limits:
    """Operational limits and thresholds."""
    
    # ==========================================================================
    # Retry counts
    # ==========================================================================
    
    # YubiKey detection retries
    YUBIKEY_MAX_ATTEMPTS = 3
    
    # GPG signing retries
    GPG_SIGN_MAX_ATTEMPTS = 3
    
    # Recovery generation retries (infinite retry available, but track attempts)
    RECOVERY_GEN_MAX_AUTO_RETRIES = 3
    
    # Mount operation retries
    MOUNT_MAX_ATTEMPTS = 3
    
    # ==========================================================================
    # Timeouts (seconds)
    # ==========================================================================
    
    # Quick process checks (pgrep, tasklist, etc.)
    PROCESS_CHECK_TIMEOUT = 5
    
    # GPG operations
    GPG_AGENT_START_TIMEOUT = 10
    GPG_CARD_STATUS_TIMEOUT = 10
    GPG_DECRYPT_TIMEOUT = 30
    GPG_ENCRYPT_TIMEOUT = 30
    GPG_SIGN_TIMEOUT = 30
    
    # VeraCrypt operations
    VERACRYPT_MOUNT_TIMEOUT = 60
    VERACRYPT_UNMOUNT_TIMEOUT = 30
    VERACRYPT_FORMAT_TIMEOUT = 300  # 5 minutes for volume creation
    
    # Subprocess default
    SUBPROCESS_DEFAULT_TIMEOUT = 30
    
    # PowerShell operations (Windows drive management, etc.)
    POWERSHELL_QUICK_TIMEOUT = 10
    POWERSHELL_ASSIGN_LETTER_TIMEOUT = 15
    
    # Clipboard auto-clear
    CLIPBOARD_TIMEOUT = 60
    CLIPBOARD_VERIFICATION_TIMEOUT = 120
    
    # ==========================================================================
    # Size limits
    # ==========================================================================
    
    # Minimum partition sizes (bytes)
    MIN_LAUNCHER_PARTITION_MB = 100
    MIN_PAYLOAD_PARTITION_MB = 100
    
    # Maximum log file size before rotation (bytes)
    MAX_LOG_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    
    # Lost and found message limits
    LOST_AND_FOUND_MESSAGE_MAX_LENGTH = 500
    LOST_AND_FOUND_MESSAGE_MIN_LENGTH = 0
    
    # ==========================================================================
    # Security thresholds
    # ==========================================================================
    
    # Minimum password length recommendations
    MIN_PASSWORD_LENGTH_WARN = 12
    MIN_PASSWORD_LENGTH_REQUIRE = 8
    
    # Recovery phrase word count
    RECOVERY_WORD_COUNT = 24
    
    # ==========================================================================
    # Timing delays
    # ==========================================================================
    
    # Delay after mount/unmount to allow filesystem to settle
    FILESYSTEM_SETTLE_DELAY = 2
    
    # Delay between retry attempts
    RETRY_DELAY = 1
    
    # ==========================================================================
    # Aliases for backward compatibility
    # ==========================================================================
    
    # Legacy names used by veracrypt_cli.py
    TIMEOUT_MOUNT = VERACRYPT_MOUNT_TIMEOUT  # 60 seconds
    TIMEOUT_LONG = VERACRYPT_FORMAT_TIMEOUT  # 300 seconds (5 minutes)
