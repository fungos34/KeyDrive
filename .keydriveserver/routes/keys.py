"""Key Lockout Management Routes.

CHG-20251221-009: /api/keys endpoints for hardware key lockout.
Development-only component - not deployed to KeyDrive devices.

Security: Key lockout requires admin authentication.
When a key is marked as lost, all associated devices/seeds are blocked.
"""

from __future__ import annotations

import json
from datetime import datetime

from flask import current_app, jsonify, request

from models import Device, Key, Seed, db
from routes import keys_bp


@keys_bp.route("/report-lost", methods=["POST"])
def report_key_lost():
    """
    Report a hardware key as lost.

    Request body:
        {
            "fingerprint": "GPG key fingerprint",
            "reason": "Description of why key is reported lost",
            "admin_token": "Admin authentication token"
        }

    Returns:
        {
            "success": true,
            "message": "Key marked as lost",
            "affected_devices": 5
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    fingerprint = data.get("fingerprint")
    reason = data.get("reason", "")
    admin_token = data.get("admin_token") or request.headers.get("X-Admin-Token")

    # Validate admin authentication
    expected_token = current_app.config.get("ADMIN_TOKEN")
    if not expected_token:
        return jsonify({"success": False, "message": "Admin token not configured on server"}), 500

    if admin_token != expected_token:
        return jsonify({"success": False, "message": "Invalid admin token"}), 401

    if not fingerprint:
        return jsonify({"success": False, "message": "Missing fingerprint"}), 400

    # Get or create key record
    key = Key.query.filter_by(fingerprint=fingerprint).first()
    if not key:
        key = Key(fingerprint=fingerprint)
        db.session.add(key)

    # Mark key as lost
    key.status = "lost"
    key.reported_at = datetime.utcnow()
    key.reason = reason

    # Lock all seeds that use this key
    affected_devices = 0
    seeds = Seed.query.all()
    for seed in seeds:
        fingerprints = json.loads(seed.key_fingerprints) if seed.key_fingerprints else []
        if fingerprint in fingerprints:
            seed.locked = True
            affected_devices += 1

            # Also lock the device
            device = Device.query.filter_by(device_id_hash=seed.device_id_hash).first()
            if device:
                device.locked = True

    db.session.commit()

    return jsonify({"success": True, "message": "Key marked as lost", "affected_devices": affected_devices})


@keys_bp.route("/<fingerprint>/status", methods=["GET"])
def get_key_status(fingerprint: str):
    """
    Get the status of a hardware key.

    Args:
        fingerprint: GPG key fingerprint

    Returns:
        {
            "fingerprint": "...",
            "status": "active|lost|revoked",
            "reported_at": "...",
            "reason": "..."
        }
    """
    key = Key.query.filter_by(fingerprint=fingerprint).first()

    if not key:
        return jsonify({"fingerprint": fingerprint, "status": "active", "reported_at": None, "reason": None})

    return jsonify(
        {
            "fingerprint": key.fingerprint,
            "status": key.status,
            "reported_at": key.reported_at.isoformat() if key.reported_at else None,
            "reason": key.reason,
        }
    )


@keys_bp.route("/unlock", methods=["POST"])
def unlock_key():
    """
    Unlock a previously lost key (admin only).

    Request body:
        {
            "fingerprint": "GPG key fingerprint",
            "admin_token": "Admin authentication token"
        }

    Returns:
        {
            "success": true,
            "message": "Key unlocked",
            "affected_devices": 5
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    fingerprint = data.get("fingerprint")
    admin_token = data.get("admin_token") or request.headers.get("X-Admin-Token")

    # Validate admin authentication
    expected_token = current_app.config.get("ADMIN_TOKEN")
    if not expected_token:
        return jsonify({"success": False, "message": "Admin token not configured on server"}), 500

    if admin_token != expected_token:
        return jsonify({"success": False, "message": "Invalid admin token"}), 401

    if not fingerprint:
        return jsonify({"success": False, "message": "Missing fingerprint"}), 400

    # Get key record
    key = Key.query.filter_by(fingerprint=fingerprint).first()
    if not key:
        return jsonify({"success": False, "message": "Key not found"}), 404

    # Restore key to active
    key.status = "active"
    key.reason = f"Unlocked on {datetime.utcnow().isoformat()}"

    # Unlock seeds that ONLY use this key (seeds with multiple keys stay locked if any key is lost)
    affected_devices = 0
    seeds = Seed.query.filter_by(locked=True).all()
    for seed in seeds:
        fingerprints = json.loads(seed.key_fingerprints) if seed.key_fingerprints else []

        # Check if all keys for this seed are now active
        all_active = True
        for fp in fingerprints:
            other_key = Key.query.filter_by(fingerprint=fp).first()
            if other_key and other_key.status != "active":
                all_active = False
                break

        if all_active:
            seed.locked = False
            affected_devices += 1

            # Also unlock the device
            device = Device.query.filter_by(device_id_hash=seed.device_id_hash).first()
            if device:
                device.locked = False

    db.session.commit()

    return jsonify({"success": True, "message": "Key unlocked", "affected_devices": affected_devices})


@keys_bp.route("/list-lost", methods=["GET"])
def list_lost_keys():
    """
    List all keys that are currently marked as lost (admin only).

    Headers:
        X-Admin-Token: Admin authentication token

    Returns:
        [
            {"fingerprint": "...", "reported_at": "...", "reason": "..."},
            ...
        ]
    """
    admin_token = request.headers.get("X-Admin-Token")
    expected_token = current_app.config.get("ADMIN_TOKEN")

    if not expected_token or admin_token != expected_token:
        return jsonify({"error": "Admin authentication required"}), 401

    lost_keys = Key.query.filter_by(status="lost").all()

    return jsonify(
        [
            {
                "fingerprint": k.fingerprint,
                "reported_at": k.reported_at.isoformat() if k.reported_at else None,
                "reason": k.reason,
            }
            for k in lost_keys
        ]
    )
