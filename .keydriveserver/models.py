"""KeyDrive Server Database Models.

CHG-20251221-009: SQLAlchemy models for server database.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from flask_sqlalchemy import SQLAlchemy

if TYPE_CHECKING:
    from flask import Flask

db = SQLAlchemy()


def init_db(app: Flask) -> None:
    """Initialize database with Flask app."""
    db.init_app(app)
    with app.app_context():
        db.create_all()


class Device(db.Model):
    """Device registration and verification tracking."""

    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    device_id_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_verified = db.Column(db.DateTime)
    current_version = db.Column(db.String(32))
    locked = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    seeds = db.relationship("Seed", back_populates="device", lazy="dynamic")
    verification_logs = db.relationship("VerificationLog", back_populates="device", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Device {self.device_id_hash[:8]}...>"


class Seed(db.Model):
    """GPG-encrypted seed storage."""

    __tablename__ = "seeds"

    id = db.Column(db.Integer, primary_key=True)
    device_id_hash = db.Column(db.String(64), db.ForeignKey("devices.device_id_hash"), nullable=False, index=True)
    encrypted_seed = db.Column(db.Text, nullable=False)  # GPG-encrypted, base64-encoded
    key_fingerprints = db.Column(db.Text, nullable=False)  # JSON array of fingerprints
    salt = db.Column(db.String(64), nullable=False)  # Base64-encoded salt
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    locked = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    device = db.relationship("Device", back_populates="seeds")

    def __repr__(self) -> str:
        return f"<Seed device={self.device_id_hash[:8]}... locked={self.locked}>"


class Key(db.Model):
    """Hardware key status tracking."""

    __tablename__ = "keys"

    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(16), default="active", nullable=False)  # active, lost, revoked
    reported_at = db.Column(db.DateTime)  # When key was reported lost
    reason = db.Column(db.Text)  # Reason for status change
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Key {self.fingerprint[:8]}... status={self.status}>"


class VerificationLog(db.Model):
    """Audit log of verification attempts."""

    __tablename__ = "verification_log"

    id = db.Column(db.Integer, primary_key=True)
    device_id_hash = db.Column(db.String(64), db.ForeignKey("devices.device_id_hash"), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    hash_value = db.Column(db.String(128), nullable=False)
    result = db.Column(db.String(16), nullable=False)  # pass, fail, error
    ip_address = db.Column(db.String(45))  # IPv4 or IPv6
    user_agent = db.Column(db.String(256))

    # Relationships
    device = db.relationship("Device", back_populates="verification_logs")

    def __repr__(self) -> str:
        return f"<VerificationLog device={self.device_id_hash[:8]}... result={self.result}>"


class Update(db.Model):
    """Software update metadata."""

    __tablename__ = "updates"

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(32), unique=True, nullable=False, index=True)
    release_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    package_filename = db.Column(db.String(256), nullable=False)
    package_hash = db.Column(db.String(128), nullable=False)  # SHA-512 hash
    package_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    changelog = db.Column(db.Text)
    min_version = db.Column(db.String(32))  # Minimum version required to upgrade
    is_current = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<Update {self.version} current={self.is_current}>"
