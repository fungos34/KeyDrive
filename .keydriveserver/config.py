"""KeyDrive Server Configuration.

CHG-20251221-009: Server configuration with environment variable support.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

import os
from pathlib import Path


class Config:
    """Server configuration loaded from environment variables."""

    # Base directory
    BASE_DIR = Path(__file__).parent.resolve()

    # Flask settings
    SECRET_KEY = os.environ.get("KEYDRIVE_SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = os.environ.get("KEYDRIVE_DEBUG", "false").lower() == "true"

    # Database
    DATABASE_PATH = Path(os.environ.get("KEYDRIVE_DATABASE_URL", str(BASE_DIR / "keydrive.db")))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Admin authentication
    ADMIN_TOKEN = os.environ.get("KEYDRIVE_ADMIN_TOKEN", "")

    # Rate limiting
    RATELIMIT_DEFAULT = "100 per minute"
    RATELIMIT_STORAGE_URL = "memory://"

    # CORS
    CORS_ORIGINS = os.environ.get("KEYDRIVE_CORS_ORIGINS", "*").split(",")

    # Update distribution
    UPDATES_DIR = Path(os.environ.get("KEYDRIVE_UPDATES_DIR", str(BASE_DIR / "updates")))

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of warnings."""
        warnings = []

        if cls.SECRET_KEY == "dev-secret-key-change-in-production":
            warnings.append("WARNING: Using default secret key. Set KEYDRIVE_SECRET_KEY in production.")

        if not cls.ADMIN_TOKEN:
            warnings.append("WARNING: No admin token set. Key lockout will be disabled.")

        if cls.DEBUG:
            warnings.append("WARNING: Debug mode enabled. Disable in production.")

        return warnings


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    RATELIMIT_DEFAULT = "60 per minute"


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    ADMIN_TOKEN = "test-admin-token"


# Configuration map
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(env: str | None = None) -> type[Config]:
    """Get configuration class based on environment."""
    if env is None:
        env = os.environ.get("KEYDRIVE_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
