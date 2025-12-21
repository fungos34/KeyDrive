"""Seed Storage Routes.

CHG-20251221-009: /api/seeds endpoints for encrypted seed management.
Development-only component - not deployed to KeyDrive devices.

Security: Server stores GPG-encrypted seeds and cannot decrypt them.
"""

from __future__ import annotations

import json
from datetime import datetime

from flask import current_app, jsonify, request

from models import Device, Key, Seed, db
from routes import seeds_bp


@seeds_bp.route("", methods=["POST"])
def store_seed():
    """
    Store an encrypted seed for a device.

    Request body:
        {
            "device_id": "hashed device identifier",
            "encrypted_seed": "GPG-encrypted, base64-encoded seed",
            "key_fingerprints": ["fingerprint1", "fingerprint2"],
            "salt": "base64-encoded salt for HKDF"
        }

    Returns:
        {"success": true, "message": "Seed stored"}
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    device_id_hash = data.get("device_id")
    encrypted_seed = data.get("encrypted_seed")
    key_fingerprints = data.get("key_fingerprints", [])
    salt = data.get("salt")

    # Validate required fields
    if not device_id_hash:
        return jsonify({"success": False, "message": "Missing device_id"}), 400
    if not encrypted_seed:
        return jsonify({"success": False, "message": "Missing encrypted_seed"}), 400
    if not salt:
        return jsonify({"success": False, "message": "Missing salt"}), 400

    # Check if any associated keys are locked
    for fp in key_fingerprints:
        key = Key.query.filter_by(fingerprint=fp).first()
        if key and key.status == "lost":
            return jsonify({"success": False, "message": f"Key {fp[:8]}... is marked as lost", "locked": True}), 403

    # Get or create device record
    device = Device.query.filter_by(device_id_hash=device_id_hash).first()
    if not device:
        device = Device(device_id_hash=device_id_hash)
        db.session.add(device)
        db.session.flush()  # Get device record created

    # Check if seed already exists for this device
    existing_seed = Seed.query.filter_by(device_id_hash=device_id_hash).first()
    if existing_seed:
        # Update existing seed
        existing_seed.encrypted_seed = encrypted_seed
        existing_seed.key_fingerprints = json.dumps(key_fingerprints)
        existing_seed.salt = salt
        existing_seed.created_at = datetime.utcnow()
        existing_seed.locked = False
    else:
        # Create new seed
        seed = Seed(
            device_id_hash=device_id_hash,
            encrypted_seed=encrypted_seed,
            key_fingerprints=json.dumps(key_fingerprints),
            salt=salt,
        )
        db.session.add(seed)

    db.session.commit()

    return jsonify({"success": True, "message": "Seed stored"})


@seeds_bp.route("/<device_id>", methods=["GET"])
def get_seed(device_id: str):
    """
    Retrieve encrypted seed for a device.

    Args:
        device_id: Hashed device identifier

    Returns:
        {
            "encrypted_seed": "...",
            "salt": "...",
            "key_fingerprints": [...],
            "created_at": "...",
            "locked": false
        }
    """
    seed = Seed.query.filter_by(device_id_hash=device_id).first()

    if not seed:
        return jsonify({"error": "Seed not found for device"}), 404

    # Check if seed is locked
    if seed.locked:
        return jsonify({"error": "Seed is locked", "locked": True}), 403

    # Check if any associated keys are locked
    fingerprints = json.loads(seed.key_fingerprints) if seed.key_fingerprints else []
    for fp in fingerprints:
        key = Key.query.filter_by(fingerprint=fp).first()
        if key and key.status == "lost":
            return jsonify({"error": f"Associated key {fp[:8]}... is locked", "locked": True}), 403

    return jsonify(
        {
            "encrypted_seed": seed.encrypted_seed,
            "salt": seed.salt,
            "key_fingerprints": fingerprints,
            "created_at": seed.created_at.isoformat(),
            "locked": seed.locked,
        }
    )


@seeds_bp.route("/<device_id>", methods=["DELETE"])
def delete_seed(device_id: str):
    """
    Delete seed for a device (admin only).

    Args:
        device_id: Hashed device identifier

    Headers:
        X-Admin-Token: Admin authentication token

    Returns:
        {"success": true, "message": "Seed deleted"}
    """
    admin_token = request.headers.get("X-Admin-Token")
    expected_token = current_app.config.get("ADMIN_TOKEN")

    if not expected_token or admin_token != expected_token:
        return jsonify({"success": False, "message": "Admin authentication required"}), 401

    seed = Seed.query.filter_by(device_id_hash=device_id).first()

    if not seed:
        return jsonify({"error": "Seed not found for device"}), 404

    db.session.delete(seed)
    db.session.commit()

    return jsonify({"success": True, "message": "Seed deleted"})


@seeds_bp.route("/<device_id>/lock", methods=["POST"])
def lock_seed(device_id: str):
    """
    Lock seed for a device (admin only).

    Args:
        device_id: Hashed device identifier

    Headers:
        X-Admin-Token: Admin authentication token

    Returns:
        {"success": true, "message": "Seed locked"}
    """
    admin_token = request.headers.get("X-Admin-Token")
    expected_token = current_app.config.get("ADMIN_TOKEN")

    if not expected_token or admin_token != expected_token:
        return jsonify({"success": False, "message": "Admin authentication required"}), 401

    seed = Seed.query.filter_by(device_id_hash=device_id).first()

    if not seed:
        return jsonify({"error": "Seed not found for device"}), 404

    seed.locked = True
    db.session.commit()

    return jsonify({"success": True, "message": "Seed locked"})
