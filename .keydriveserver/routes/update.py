"""Update Distribution Routes.

CHG-20251221-009: /api/update endpoints for software update distribution.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

from pathlib import Path

from flask import current_app, jsonify, send_from_directory

from models import Update
from routes import update_bp


@update_bp.route("/latest", methods=["GET"])
def get_latest_version():
    """
    Get information about the latest available version.

    Returns:
        {
            "version": "1.0.0",
            "release_date": "2025-12-21T00:00:00",
            "changelog": "...",
            "package_size": 12345,
            "package_hash": "sha512 hash"
        }
    """
    update = Update.query.filter_by(is_current=True).first()

    if not update:
        return jsonify({"error": "No updates available"}), 404

    return jsonify(
        {
            "version": update.version,
            "release_date": update.release_date.isoformat(),
            "changelog": update.changelog,
            "package_size": update.package_size,
            "package_hash": update.package_hash,
            "min_version": update.min_version,
            "download_url": f"/api/update/download/{update.version}",
        }
    )


@update_bp.route("/check/<current_version>", methods=["GET"])
def check_for_update(current_version: str):
    """
    Check if an update is available for the given version.

    Args:
        current_version: The client's current version

    Returns:
        {
            "update_available": true/false,
            "latest_version": "1.0.0",
            "can_upgrade": true/false,
            "download_url": "/api/update/download/<version>"
        }
    """
    latest = Update.query.filter_by(is_current=True).first()

    if not latest:
        return jsonify({"update_available": False, "latest_version": None, "can_upgrade": False, "download_url": None})

    # Simple version comparison (assumes semver-like format)
    update_available = latest.version != current_version

    # Check if direct upgrade is possible
    can_upgrade = True
    if latest.min_version:
        can_upgrade = _version_gte(current_version, latest.min_version)

    return jsonify(
        {
            "update_available": update_available,
            "latest_version": latest.version,
            "can_upgrade": can_upgrade,
            "download_url": f"/api/update/download/{latest.version}" if update_available else None,
        }
    )


@update_bp.route("/download/latest", methods=["GET"])
def download_latest_update():
    """
    Download the latest update package.

    CHG-20251221-010: Convenience endpoint to download latest version without
    knowing the version number. Useful for automated update clients.

    Returns:
        The update package file (zip)
    """
    latest = Update.query.filter_by(is_current=True).first()

    if not latest:
        return jsonify({"error": "No updates available"}), 404

    updates_dir = Path(current_app.config.get("UPDATES_DIR", "updates"))

    if not updates_dir.exists():
        return jsonify({"error": "Updates directory not configured"}), 500

    package_path = updates_dir / latest.package_filename

    if not package_path.exists():
        return jsonify({"error": "Update package not found"}), 404

    return send_from_directory(str(updates_dir), latest.package_filename, as_attachment=True)


@update_bp.route("/download/<version>", methods=["GET"])
def download_update(version: str):
    """
    Download an update package.

    Args:
        version: The version to download

    Returns:
        The update package file
    """
    update = Update.query.filter_by(version=version).first()

    if not update:
        return jsonify({"error": f"Version {version} not found"}), 404

    updates_dir = Path(current_app.config.get("UPDATES_DIR", "updates"))

    if not updates_dir.exists():
        return jsonify({"error": "Updates directory not configured"}), 500

    package_path = updates_dir / update.package_filename

    if not package_path.exists():
        return jsonify({"error": "Update package not found"}), 404

    return send_from_directory(str(updates_dir), update.package_filename, as_attachment=True)


@update_bp.route("/history", methods=["GET"])
def get_update_history():
    """
    Get list of all available updates.

    Returns:
        [
            {"version": "1.0.0", "release_date": "...", "is_current": true},
            ...
        ]
    """
    updates = Update.query.order_by(Update.release_date.desc()).all()

    return jsonify(
        [
            {
                "version": u.version,
                "release_date": u.release_date.isoformat(),
                "is_current": u.is_current,
                "changelog": u.changelog,
            }
            for u in updates
        ]
    )


def _version_gte(version_a: str, version_b: str) -> bool:
    """Check if version_a >= version_b (simple semver comparison)."""
    try:
        parts_a = [int(x) for x in version_a.split(".")]
        parts_b = [int(x) for x in version_b.split(".")]

        # Pad to same length
        max_len = max(len(parts_a), len(parts_b))
        parts_a.extend([0] * (max_len - len(parts_a)))
        parts_b.extend([0] * (max_len - len(parts_b)))

        return parts_a >= parts_b
    except (ValueError, AttributeError):
        return False
