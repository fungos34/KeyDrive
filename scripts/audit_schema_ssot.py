"""
Schema-Config SSOT Audit Script
================================
Ensures all user-configurable ConfigKeys appear in settings_schema using SET-EQUALITY.
Part of repo health verification (extend existing audit if present).

Exit codes:
  0: All checks pass
  1: Schema drift detected (missing or orphaned keys)
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / ".smartdrive"))

from core.constants import ConfigKeys
from core.settings_schema import SETTINGS_SCHEMA


def enumerate_all_configkeys():
    """Enumerate all ConfigKeys attributes (single source of truth)."""
    keys = set()
    for attr_name in dir(ConfigKeys):
        if not attr_name.startswith("_"):
            attr_value = getattr(ConfigKeys, attr_name)
            if isinstance(attr_value, str):
                keys.add(attr_value)
    return keys


def enumerate_schema_keys():
    """Enumerate all keys covered by settings_schema."""
    schema_keys = set()
    for field in SETTINGS_SCHEMA:
        if field.nested_path:
            # For nested paths, use dot notation
            schema_keys.add(".".join(field.nested_path))
        else:
            schema_keys.add(field.key)
    return schema_keys


# Keys that are expected to NOT be in schema (system-managed, runtime, or deprecated)
EXPECTED_NOT_IN_SCHEMA = {
    ConfigKeys.DRIVE_ID,  # System-generated UUID
    ConfigKeys.SETUP_DATE,  # Timestamp
    ConfigKeys.LAST_PASSWORD_CHANGE,  # Timestamp
    ConfigKeys.LAST_VERIFIED,  # Timestamp
    ConfigKeys.INTEGRITY_SIGNED,  # System-managed signature
    ConfigKeys.SIGNING_KEY_FPR,  # System-managed fingerprint
    ConfigKeys.SALT_B64,  # Cryptographic salt
    ConfigKeys.SCHEMA_VERSION,  # Config version tracking
    ConfigKeys.VERSION,  # Software version
    ConfigKeys.LAST_UPDATED,  # Timestamp
    ConfigKeys.KEYFILE_FINGERPRINTS,  # System-managed list
    # Generic leaf keys (used in nested paths like recovery.enabled, lost_and_found.enabled)
    "enabled",  # Generic key used in multiple nested contexts
    "message",  # Generic key used in nested contexts
    "threshold",  # Generic key used in nested contexts
    "share_count",  # Generic key used in nested contexts
    "mount_letter",  # Generic key used in nested contexts
    "mount_point",  # Generic key used in nested contexts
    "volume_path",  # Generic key used in nested contexts
    "veracrypt_path",  # Generic key used in nested contexts
    # Nested root keys (not user-editable as keys themselves)
    "windows",  # Container for windows.* keys
    "unix",  # Container for unix.* keys
    "recovery",  # Container for recovery.* keys
    "lost_and_found",  # Container for lost_and_found.* keys
}

# Keys that are in schema but not in ConfigKeys (nested paths)
ALLOWED_SCHEMA_ONLY = {
    "lost_and_found.enabled",  # From nested config
    "lost_and_found.message",  # From nested config
    "recovery.enabled",  # From nested config
    "recovery.share_count",  # From nested config
    "recovery.threshold",  # From nested config
    "unix.mount_point",  # From nested config
    "unix.volume_path",  # From nested config
    "windows.mount_letter",  # From nested config
    "windows.veracrypt_path",  # From nested config
    "windows.volume_path",  # From nested config
}


def check_schema_completeness():
    """Verify schema covers all user-editable ConfigKeys using set-equality."""
    all_config_keys = enumerate_all_configkeys()
    schema_keys = enumerate_schema_keys()

    # Keys that should be in schema (user-editable)
    expected_in_schema = all_config_keys - EXPECTED_NOT_IN_SCHEMA

    # Check for missing keys
    missing_in_schema = expected_in_schema - schema_keys - ALLOWED_SCHEMA_ONLY

    # Check for orphaned keys (in schema but not in ConfigKeys, excluding allowed)
    orphaned_in_schema = schema_keys - all_config_keys - ALLOWED_SCHEMA_ONLY

    # Readonly keys marked in schema
    readonly_keys_in_schema = set()
    for field in SETTINGS_SCHEMA:
        if field.readonly:
            readonly_keys_in_schema.add(field.key)

    return missing_in_schema, orphaned_in_schema, readonly_keys_in_schema


def main():
    """Run schema audit with set-equality comparison."""
    try:
        print("Schema-Config SSOT Audit (Set-Equality)")
        print("=" * 60)

        missing, orphaned, readonly_in_schema = check_schema_completeness()

        failed = False

        # Check 1: No missing keys
        if missing:
            print("\nFAIL: ConfigKeys missing from schema:")
            for key in sorted(missing):
                print(f"   - {key}")
            print("\n   Add these to settings_schema.py or EXPECTED_NOT_IN_SCHEMA")
            failed = True
        else:
            all_config_keys = enumerate_all_configkeys()
            expected = all_config_keys - EXPECTED_NOT_IN_SCHEMA
            print(f"\nAll {len(expected)} user-editable ConfigKeys present in schema")

        # Check 2: No orphaned keys
        if orphaned:
            print("\nFAIL: Schema keys not in ConfigKeys:")
            for key in sorted(orphaned):
                print(f"   - {key}")
            print("\n   Add these to ConfigKeys or ALLOWED_SCHEMA_ONLY")
            failed = True

        # Check 3: Readonly keys are marked
        print(f"\n{len(readonly_in_schema)} readonly keys marked in schema")

        # Check 4: Schema structure
        tabs = set(f.tab for f in SETTINGS_SCHEMA)
        print(f"\nSchema spans {len(tabs)} tabs: {', '.join(sorted(tabs))}")
        print(f"Total schema fields: {len(SETTINGS_SCHEMA)}")

        if failed:
            print("\n" + "=" * 60)
            print("FAIL: Schema audit detected drift")
            return 1

        print("\n" + "=" * 60)
        print("Schema audit PASSED")
        return 0

    except Exception as e:
        print(f"\nERROR: Schema audit failed with exception: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
