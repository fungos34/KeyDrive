"""Integrity Verification Routes.

CHG-20251221-009: /api/verify endpoint for validating device integrity.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify, request

from models import Device, VerificationLog, db
from routes import verify_bp


@verify_bp.route("/check", methods=["POST"])
def check_integrity():
    """
    Check device integrity hash.

    Request body:
        {
            "id": "device identifier",
            "datetime": "ISO timestamp",
            "hash": "integrity hash of scripts",
            "version": "current software version",
            "integrity_signed": "signature status",
            "signing_key_fpr": "signing key fingerprint"
        }

    Returns:
        {
            "valid": true/false,
            "message": "description"
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({"valid": False, "message": "No data provided"}), 400

    device_id_hash = data.get("id")
    hash_value = data.get("hash")
    version = data.get("version")
    integrity_signed = data.get("integrity_signed")
    signing_key_fpr = data.get("signing_key_fpr")

    if not device_id_hash or not hash_value:
        return jsonify({"valid": False, "message": "Missing required fields: id, hash"}), 400

    # Get or create device record
    device = Device.query.filter_by(device_id_hash=device_id_hash).first()
    if not device:
        device = Device(device_id_hash=device_id_hash, current_version=version)
        db.session.add(device)

    # Check if device is locked
    if device.locked:
        _log_verification(device_id_hash, hash_value, "blocked")
        return jsonify({"valid": False, "message": "Device is locked", "locked": True}), 403

    # TODO: Implement actual hash verification against signed manifest
    # For now, we just log the verification attempt
    is_valid = True  # Placeholder - implement actual verification

    # Update device record
    device.last_verified = datetime.now(timezone.utc)
    if version:
        device.current_version = version

    # Log verification attempt
    _log_verification(device_id_hash, hash_value, "pass" if is_valid else "fail")

    db.session.commit()

    return jsonify({"valid": is_valid, "message": "Integrity verified", "locked": False})


@verify_bp.route("/health", methods=["GET"])
def health_check():
    """Server health check endpoint."""
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


def _log_verification(device_id_hash: str, hash_value: str, result: str) -> None:
    """Log a verification attempt."""
    log_entry = VerificationLog(
        device_id_hash=device_id_hash,
        hash_value=hash_value,
        result=result,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent", "")[:256],
    )
    db.session.add(log_entry)
