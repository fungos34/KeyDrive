"""KeyDrive Server Route Blueprints.

CHG-20251221-009: Flask blueprint registration.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

from flask import Blueprint, Flask

# Create blueprints
verify_bp = Blueprint("verify", __name__, url_prefix="/api")
update_bp = Blueprint("update", __name__, url_prefix="/api/update")
seeds_bp = Blueprint("seeds", __name__, url_prefix="/api/seeds")
keys_bp = Blueprint("keys", __name__, url_prefix="/api/keys")


def register_blueprints(app: Flask) -> None:
    """Register all blueprints with the Flask app."""
    # Import routes to register handlers
    from . import keys, seeds, update, verify  # noqa: F401

    app.register_blueprint(verify_bp)
    app.register_blueprint(update_bp)
    app.register_blueprint(seeds_bp)
    app.register_blueprint(keys_bp)
