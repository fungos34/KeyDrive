"""KeyDrive Server Tests.

CHG-20251221-009: Test suite for server endpoints.
Development-only component - not deployed to KeyDrive devices.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import create_app
from models import db, Device, Seed, Key, Update


@pytest.fixture
def app():
    """Create test application."""
    app = create_app("testing")
    yield app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def init_database(app):
    """Initialize test database."""
    with app.app_context():
        db.create_all()
        yield db
        db.drop_all()


class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_check(self, client, init_database):
        """Test /api/health returns healthy status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestVerifyEndpoint:
    """Test integrity verification endpoint."""

    def test_verify_success(self, client, init_database):
        """Test successful verification."""
        response = client.post(
            "/api/verify",
            json={
                "device_id": "test_device_hash",
                "hash": "test_integrity_hash",
                "version": "1.0.0",
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is True
        assert data["locked"] is False

    def test_verify_missing_fields(self, client, init_database):
        """Test verification with missing fields."""
        response = client.post(
            "/api/verify",
            json={"device_id": "test_device"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["valid"] is False


class TestSeedsEndpoint:
    """Test seed storage endpoints."""

    def test_store_seed(self, client, init_database):
        """Test storing a seed."""
        response = client.post(
            "/api/seeds",
            json={
                "device_id": "test_device_hash",
                "encrypted_seed": "base64_encrypted_seed_data",
                "key_fingerprints": ["fingerprint1", "fingerprint2"],
                "salt": "base64_salt",
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_get_seed(self, client, init_database):
        """Test retrieving a seed."""
        # First store a seed
        client.post(
            "/api/seeds",
            json={
                "device_id": "test_device_hash",
                "encrypted_seed": "base64_encrypted_seed_data",
                "key_fingerprints": ["fingerprint1"],
                "salt": "base64_salt",
            },
            content_type="application/json",
        )

        # Then retrieve it
        response = client.get("/api/seeds/test_device_hash")
        assert response.status_code == 200
        data = response.get_json()
        assert data["encrypted_seed"] == "base64_encrypted_seed_data"
        assert data["salt"] == "base64_salt"

    def test_get_seed_not_found(self, client, init_database):
        """Test retrieving non-existent seed."""
        response = client.get("/api/seeds/nonexistent_device")
        assert response.status_code == 404


class TestKeysEndpoint:
    """Test key lockout endpoints."""

    def test_report_key_lost(self, client, init_database):
        """Test reporting a key as lost."""
        # First store a seed with this key
        client.post(
            "/api/seeds",
            json={
                "device_id": "test_device_hash",
                "encrypted_seed": "base64_encrypted_seed_data",
                "key_fingerprints": ["lost_key_fingerprint"],
                "salt": "base64_salt",
            },
            content_type="application/json",
        )

        # Report key as lost
        response = client.post(
            "/api/keys/report-lost",
            json={
                "fingerprint": "lost_key_fingerprint",
                "reason": "Key was stolen",
                "admin_token": "test-admin-token",
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["affected_devices"] == 1

    def test_report_key_lost_unauthorized(self, client, init_database):
        """Test reporting key lost without admin token."""
        response = client.post(
            "/api/keys/report-lost",
            json={
                "fingerprint": "test_fingerprint",
                "reason": "Test",
                "admin_token": "wrong_token",
            },
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_key_status(self, client, init_database):
        """Test getting key status."""
        response = client.get("/api/keys/unknown_fingerprint/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "active"

    def test_seed_blocked_when_key_lost(self, client, init_database):
        """Test that seed retrieval is blocked when associated key is lost."""
        # Store seed
        client.post(
            "/api/seeds",
            json={
                "device_id": "blocked_device",
                "encrypted_seed": "data",
                "key_fingerprints": ["blocked_key"],
                "salt": "salt",
            },
            content_type="application/json",
        )

        # Report key as lost
        client.post(
            "/api/keys/report-lost",
            json={
                "fingerprint": "blocked_key",
                "reason": "Lost",
                "admin_token": "test-admin-token",
            },
            content_type="application/json",
        )

        # Try to get seed - should be blocked
        response = client.get("/api/seeds/blocked_device")
        assert response.status_code == 403
        data = response.get_json()
        assert data["locked"] is True


class TestUpdateEndpoint:
    """Test update distribution endpoints."""

    def test_get_latest_no_updates(self, client, init_database):
        """Test getting latest when no updates exist."""
        response = client.get("/api/update/latest")
        assert response.status_code == 404

    def test_check_for_update(self, client, init_database, app):
        """Test checking for updates."""
        # Add an update
        with app.app_context():
            update = Update(
                version="1.0.0",
                package_filename="update-1.0.0.zip",
                package_hash="sha512hash",
                package_size=12345,
                is_current=True,
            )
            db.session.add(update)
            db.session.commit()

        response = client.get("/api/update/check/0.9.0")
        assert response.status_code == 200
        data = response.get_json()
        assert data["update_available"] is True
        assert data["latest_version"] == "1.0.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
