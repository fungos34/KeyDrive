-- KeyDrive Server Database Schema
-- CHG-20251221-009: SQLite schema reference
-- Development-only component - not deployed to KeyDrive devices

-- Device registration and verification tracking
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id_hash VARCHAR(64) NOT NULL UNIQUE,
    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_verified DATETIME,
    current_version VARCHAR(32),
    locked BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_devices_device_id_hash ON devices(device_id_hash);
CREATE INDEX IF NOT EXISTS idx_devices_locked ON devices(locked);

-- GPG-encrypted seed storage
CREATE TABLE IF NOT EXISTS seeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id_hash VARCHAR(64) NOT NULL REFERENCES devices(device_id_hash),
    encrypted_seed TEXT NOT NULL,  -- GPG-encrypted, base64-encoded
    key_fingerprints TEXT NOT NULL,  -- JSON array of fingerprints
    salt VARCHAR(64) NOT NULL,  -- Base64-encoded salt for HKDF
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_seeds_device_id_hash ON seeds(device_id_hash);
CREATE INDEX IF NOT EXISTS idx_seeds_locked ON seeds(locked);

-- Hardware key status tracking
CREATE TABLE IF NOT EXISTS keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',  -- active, lost, revoked
    reported_at DATETIME,  -- When key was reported lost
    reason TEXT,  -- Reason for status change
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_keys_fingerprint ON keys(fingerprint);
CREATE INDEX IF NOT EXISTS idx_keys_status ON keys(status);

-- Audit log of verification attempts
CREATE TABLE IF NOT EXISTS verification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id_hash VARCHAR(64) NOT NULL REFERENCES devices(device_id_hash),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hash_value VARCHAR(128) NOT NULL,
    result VARCHAR(16) NOT NULL,  -- pass, fail, error, blocked
    ip_address VARCHAR(45),  -- IPv4 or IPv6
    user_agent VARCHAR(256)
);

CREATE INDEX IF NOT EXISTS idx_verification_log_device_id_hash ON verification_log(device_id_hash);
CREATE INDEX IF NOT EXISTS idx_verification_log_timestamp ON verification_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_verification_log_result ON verification_log(result);

-- Software update metadata
CREATE TABLE IF NOT EXISTS updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version VARCHAR(32) NOT NULL UNIQUE,
    release_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    package_filename VARCHAR(256) NOT NULL,
    package_hash VARCHAR(128) NOT NULL,  -- SHA-512 hash
    package_size INTEGER NOT NULL,  -- Size in bytes
    changelog TEXT,
    min_version VARCHAR(32),  -- Minimum version required to upgrade
    is_current BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_updates_version ON updates(version);
CREATE INDEX IF NOT EXISTS idx_updates_is_current ON updates(is_current);

-- Trigger to ensure only one current update
CREATE TRIGGER IF NOT EXISTS ensure_single_current_update
    BEFORE UPDATE ON updates
    WHEN NEW.is_current = 1
BEGIN
    UPDATE updates SET is_current = 0 WHERE is_current = 1 AND id != NEW.id;
END;
