"""KeyDrive Server - Main Application.

CHG-20251221-009: Flask server for verification, updates, seeds, and key lockout.
Development-only component - not deployed to KeyDrive devices.

Usage:
    # Development
    python server.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:8000 server:app
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add the current directory to sys.path to enable relative imports
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import get_config
from models import db, init_db
from routes import register_blueprints


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load configuration
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    # Validate configuration
    warnings = config_class.validate()
    for warning in warnings:
        print(warning, file=sys.stderr)

    # Initialize extensions
    init_db(app)

    # Enable CORS
    CORS(app, origins=app.config.get("CORS_ORIGINS", "*"))

    # Enable rate limiting
    Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[app.config.get("RATELIMIT_DEFAULT", "100 per minute")],
        storage_uri=app.config.get("RATELIMIT_STORAGE_URL", "memory://"),
    )

    # Register route blueprints
    register_blueprints(app)

    # Create updates directory if it doesn't exist
    updates_dir = Path(app.config.get("UPDATES_DIR", "updates"))
    updates_dir.mkdir(parents=True, exist_ok=True)

    return app


# Create the app instance for gunicorn (only when run as module, not when imported)
if __name__ != "__main__":
    app = create_app()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KeyDrive Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    print("=" * 60)
    print("KeyDrive Server - Development Only")
    print("NOT for deployment to KeyDrive devices")
    print("=" * 60)
    print(f"Starting server on http://{args.host}:{args.port}")
    print()

    # Create app for direct execution
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
else:
    # For gunicorn/wsgi servers - create app instance
    app = create_app()
