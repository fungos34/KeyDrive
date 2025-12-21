"""
DRF Views for KeyDrive Server API.

CHG-20251221-013: API views for verification, updates, seeds, and key management.
"""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Device, Key, Seed, Update, VerificationLog
from .serializers import (
    DeviceSerializer,
    KeySerializer,
    KeyStatusUpdateSerializer,
    SeedCreateSerializer,
    SeedRetrieveSerializer,
    SeedSerializer,
    UpdateCheckResponseSerializer,
    UpdateCheckSerializer,
    UpdateSerializer,
    VerificationLogSerializer,
    VerifyRequestSerializer,
    VerifyResponseSerializer,
)


# =============================================================================
# Verification Views
# =============================================================================


class VerifyView(APIView):
    """
    Integrity verification endpoint.
    
    POST /api/verify
    Verifies integrity hash for a device.
    """

    def post(self, request):
        """Handle verification request (Flask-compatible)."""
        # Flask compatibility: accept both 'id' and 'device_id_hash'
        data = request.data
        if not data:
            return Response({"valid": False, "message": "No data provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        device_id_hash = data.get("id") or data.get("device_id_hash")
        hash_value = data.get("hash")
        version = data.get("version")
        
        if not device_id_hash or not hash_value:
            return Response({"valid": False, "message": "Missing required fields: id, hash"}, status=status.HTTP_400_BAD_REQUEST)

        # Get or create device
        device, _ = Device.objects.get_or_create(device_id_hash=device_id_hash)

        # Check if device is locked
        if device.locked:
            log = VerificationLog.objects.create(
                device=device,
                hash_value=hash_value,
                result="blocked",
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:256],
            )
            return Response(
                {
                    "valid": False,
                    "message": "Device is locked",
                    "locked": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check hash against expected values (from settings or manifest)
        expected_hashes = getattr(settings, "EXPECTED_HASHES", {})
        hash_valid = self._verify_hash(hash_value, expected_hashes)

        result = "pass" if hash_valid else "fail"

        # Update device record
        device.last_verified = timezone.now()
        if version:
            device.current_version = version
        device.save()

        # Create verification log
        log = VerificationLog.objects.create(
            device=device,
            hash_value=hash_value,
            result=result,
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:256],
        )

        # Check for updates
        update_available = False
        latest_version = None
        try:
            current_update = Update.objects.filter(is_current=True).first()
            if current_update and version:
                update_available = self._version_less_than(version, current_update.version)
                latest_version = current_update.version
        except Exception:
            pass

        response_data = {
            "valid": hash_valid,
            "message": "Integrity verified" if hash_valid else "Integrity check failed",
            "locked": False,
        }

        if update_available:
            response_data["update_available"] = True
            response_data["latest_version"] = latest_version

        return Response(response_data, status=status.HTTP_200_OK)

    def _get_client_ip(self, request):
        """Extract client IP from request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    def _verify_hash(self, hash_value: str, expected_hashes: dict) -> bool:
        """Verify hash against expected values."""
        # If no expected hashes configured, allow all (development mode)
        if not expected_hashes:
            return True
        return hash_value in expected_hashes.values()

    def _version_less_than(self, v1: str, v2: str) -> bool:
        """Compare version strings (semver-like)."""
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]
            return parts1 < parts2
        except Exception:
            return False


# =============================================================================
# Update Views
# =============================================================================


class UpdateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for software updates.
    
    GET /api/update/          - List all updates
    GET /api/update/{version} - Get specific update details
    GET /api/update/check     - Check for updates
    GET /api/update/download/latest - Download latest update
    GET /api/update/download/{version} - Download specific version
    """

    queryset = Update.objects.all()
    serializer_class = UpdateSerializer
    lookup_field = "version"

    @action(detail=False, methods=["post"])
    def check(self, request):
        """Check if updates are available."""
        serializer = UpdateCheckSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        current_version = serializer.validated_data["current_version"]
        current_update = Update.objects.filter(is_current=True).first()

        if not current_update:
            return Response(
                {"update_available": False},
                status=status.HTTP_200_OK,
            )

        # Compare versions
        update_available = self._version_less_than(current_version, current_update.version)

        response_data = {"update_available": update_available}

        if update_available:
            response_data.update(
                {
                    "latest_version": current_update.version,
                    "changelog": current_update.changelog or "",
                    "package_hash": current_update.package_hash,
                    "package_size": current_update.package_size,
                    "download_url": request.build_absolute_uri(
                        f"/api/update/download/{current_update.version}"
                    ),
                }
            )

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="download/latest")
    def download_latest(self, request):
        """Download the latest update package."""
        current_update = Update.objects.filter(is_current=True).first()
        if not current_update:
            raise Http404("No current update available")
        return self._serve_update_file(current_update)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, version=None):
        """Download a specific update package."""
        try:
            update = Update.objects.get(version=version)
        except Update.DoesNotExist:
            raise Http404(f"Update version {version} not found")
        return self._serve_update_file(update)

    def _serve_update_file(self, update: Update):
        """Serve update file for download."""
        updates_dir = getattr(settings, "UPDATES_DIR", Path("updates"))
        file_path = Path(updates_dir) / update.package_filename

        if not file_path.exists():
            raise Http404(f"Update package file not found: {update.package_filename}")

        response = FileResponse(
            open(file_path, "rb"),
            content_type="application/zip",
        )
        response["Content-Disposition"] = f'attachment; filename="{update.package_filename}"'
        response["Content-Length"] = update.package_size
        response["X-Package-Hash"] = update.package_hash
        return response

    def _version_less_than(self, v1: str, v2: str) -> bool:
        """Compare version strings (semver-like)."""
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]
            return parts1 < parts2
        except Exception:
            return False


# =============================================================================
# Seed Views
# =============================================================================


class SeedViewSet(viewsets.ModelViewSet):
    """
    ViewSet for GPG-encrypted seed storage.
    
    POST /api/seeds/store    - Store encrypted seed
    POST /api/seeds/retrieve - Retrieve encrypted seed
    POST /api/seeds/lock     - Lock seed (prevent retrieval)
    """

    queryset = Seed.objects.all()
    serializer_class = SeedSerializer

    def create(self, request):
        """Store an encrypted seed (Flask-compatible: POST /api/seeds)."""
        data = request.data
        if not data:
            return Response({"success": False, "message": "No data provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Flask compatibility: accept 'device_id' or 'device_id_hash'
        device_id_hash = data.get("device_id") or data.get("device_id_hash")
        encrypted_seed = data.get("encrypted_seed")
        key_fingerprints_data = data.get("key_fingerprints", [])
        salt = data.get("salt")
        
        if not device_id_hash:
            return Response({"success": False, "message": "Missing device_id"}, status=status.HTTP_400_BAD_REQUEST)
        if not encrypted_seed:
            return Response({"success": False, "message": "Missing encrypted_seed"}, status=status.HTTP_400_BAD_REQUEST)
        if not salt:
            return Response({"success": False, "message": "Missing salt"}, status=status.HTTP_400_BAD_REQUEST)

        # Check key fingerprints for lost status
        fingerprints = key_fingerprints_data if isinstance(key_fingerprints_data, list) else []
        for fp in fingerprints:
            key = Key.objects.filter(fingerprint=fp).first()
            if key and key.status == "lost":
                return Response(
                    {"success": False, "message": f"Key {fp[:8]}... is marked as lost", "locked": True},
                    status=status.HTTP_403_FORBIDDEN,
                )
        
        # Get or create device
        device, _ = Device.objects.get_or_create(device_id_hash=device_id_hash)
        
        # Convert list to JSON string for storage
        key_fingerprints_json = json.dumps(fingerprints)

        # Check if seed already exists for this device (update or create)
        existing_seed = Seed.objects.filter(device=device).first()
        if existing_seed:
            existing_seed.encrypted_seed = encrypted_seed
            existing_seed.key_fingerprints = key_fingerprints_json
            existing_seed.salt = salt
            existing_seed.locked = False
            existing_seed.save()
        else:
            seed = Seed.objects.create(
                device=device,
                encrypted_seed=encrypted_seed,
                key_fingerprints=key_fingerprints_json,
                salt=salt,
            )

        return Response(
            {"success": True, "message": "Seed stored"},
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, pk=None):
        """Retrieve an encrypted seed (Flask-compatible: GET /api/seeds/<device_id>)."""
        device_id = pk
        
        if not device_id:
            return Response({"error": "Device ID required"}, status=status.HTTP_400_BAD_REQUEST)

        # Find seed by device_id_hash
        try:
            device = Device.objects.get(device_id_hash=device_id)
            seed = Seed.objects.filter(device=device).first()
        except Device.DoesNotExist:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        if not seed:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        # Check if seed is locked
        if seed.locked:
            return Response({"error": "Seed is locked", "locked": True}, status=status.HTTP_403_FORBIDDEN)

        # Check if any associated keys are locked
        fingerprints = json.loads(seed.key_fingerprints) if seed.key_fingerprints else []
        for fp in fingerprints:
            key = Key.objects.filter(fingerprint=fp).first()
            if key and key.status == "lost":
                return Response(
                    {"error": f"Associated key {fp[:8]}... is locked", "locked": True},
                    status=status.HTTP_403_FORBIDDEN,
                )

        return Response(
            {
                "encrypted_seed": seed.encrypted_seed,
                "salt": seed.salt,
                "key_fingerprints": fingerprints,
                "created_at": seed.created_at.isoformat(),
                "locked": seed.locked,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        """Lock a seed (Flask-compatible: POST /api/seeds/<device_id>/lock)."""
        device_id = pk
        if not device_id:
            return Response({"error": "Device ID required"}, status=status.HTTP_400_BAD_REQUEST)

        # Admin authentication (X-Admin-Token header)
        admin_token = request.headers.get("X-Admin-Token")
        expected_token = getattr(settings, "ADMIN_TOKEN", None)
        
        if not expected_token or admin_token != expected_token:
            return Response(
                {"success": False, "message": "Admin authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            device = Device.objects.get(device_id_hash=device_id)
            seed = Seed.objects.filter(device=device).first()
        except Device.DoesNotExist:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        if not seed:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        seed.locked = True
        seed.save()

        return Response(
            {"success": True, "message": "Seed locked"},
            status=status.HTTP_200_OK,
        )

    def destroy(self, request, pk=None):
        """Delete seed (Flask-compatible: DELETE /api/seeds/<device_id>)."""
        device_id = pk
        if not device_id:
            return Response({"error": "Device ID required"}, status=status.HTTP_400_BAD_REQUEST)

        # Admin authentication (X-Admin-Token header)
        admin_token = request.headers.get("X-Admin-Token")
        expected_token = getattr(settings, "ADMIN_TOKEN", None)
        
        if not expected_token or admin_token != expected_token:
            return Response(
                {"success": False, "message": "Admin authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            device = Device.objects.get(device_id_hash=device_id)
            seed = Seed.objects.filter(device=device).first()
        except Device.DoesNotExist:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        if not seed:
            return Response({"error": "Seed not found for device"}, status=status.HTTP_404_NOT_FOUND)

        seed.delete()

        return Response(
            {"success": True, "message": "Seed deleted"},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# Key Views
# =============================================================================


class KeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for hardware key status tracking.
    
    GET /api/keys/              - List all keys
    GET /api/keys/{fingerprint} - Get key status
    POST /api/keys/report-lost  - Report key as lost
    POST /api/keys/revoke       - Revoke a key
    GET /api/keys/check/{fp}    - Check if key is valid
    """

    queryset = Key.objects.all()
    serializer_class = KeySerializer
    lookup_field = "fingerprint"

    @action(detail=False, methods=["post"], url_path="report-lost")
    def report_lost(self, request):
        """Report a key as lost."""
        serializer = KeyStatusUpdateSerializer(data={**request.data, "status": "lost"})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        fingerprint = serializer.validated_data["fingerprint"]
        reason = serializer.validated_data.get("reason", "")

        key, created = Key.objects.get_or_create(fingerprint=fingerprint)
        key.status = "lost"
        key.reported_at = timezone.now()
        key.reason = reason
        key.save()

        # Lock all seeds that use this key
        affected_seeds = Seed.objects.filter(key_fingerprints__contains=fingerprint)
        seeds_locked = affected_seeds.update(locked=True)

        return Response(
            {
                "status": "key_reported_lost",
                "fingerprint": fingerprint,
                "seeds_locked": seeds_locked,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"])
    def revoke(self, request):
        """Revoke a key."""
        serializer = KeyStatusUpdateSerializer(data={**request.data, "status": "revoked"})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        fingerprint = serializer.validated_data["fingerprint"]
        reason = serializer.validated_data.get("reason", "")

        key, created = Key.objects.get_or_create(fingerprint=fingerprint)
        key.status = "revoked"
        key.reported_at = timezone.now()
        key.reason = reason
        key.save()

        # Lock all seeds that use this key
        affected_seeds = Seed.objects.filter(key_fingerprints__contains=fingerprint)
        seeds_locked = affected_seeds.update(locked=True)

        return Response(
            {
                "status": "key_revoked",
                "fingerprint": fingerprint,
                "seeds_locked": seeds_locked,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="check")
    def check_status(self, request, fingerprint=None):
        """Check if a key is valid (not lost/revoked)."""
        try:
            key = Key.objects.get(fingerprint=fingerprint)
            return Response(
                {
                    "fingerprint": fingerprint,
                    "status": key.status,
                    "valid": key.status == "active",
                },
                status=status.HTTP_200_OK,
            )
        except Key.DoesNotExist:
            return Response(
                {
                    "fingerprint": fingerprint,
                    "status": "unknown",
                    "valid": True,  # Unknown keys are considered valid
                },
                status=status.HTTP_200_OK,
            )


# =============================================================================
# Device Views
# =============================================================================


class DeviceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for device management.
    
    GET /api/devices/             - List all devices
    GET /api/devices/{hash}       - Get device details
    POST /api/devices/{hash}/lock - Lock a device
    """

    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = "device_id_hash"

    @action(detail=True, methods=["post"])
    def lock(self, request, device_id_hash=None):
        """Lock a device."""
        try:
            device = Device.objects.get(device_id_hash=device_id_hash)
        except Device.DoesNotExist:
            return Response(
                {"error": "Device not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        device.locked = True
        device.save()

        # Also lock all seeds for this device
        Seed.objects.filter(device=device).update(locked=True)

        return Response(
            {"status": "device_locked", "device_id_hash": device_id_hash},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def unlock(self, request, device_id_hash=None):
        """Unlock a device."""
        try:
            device = Device.objects.get(device_id_hash=device_id_hash)
        except Device.DoesNotExist:
            return Response(
                {"error": "Device not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        device.locked = False
        device.save()

        return Response(
            {"status": "device_unlocked", "device_id_hash": device_id_hash},
            status=status.HTTP_200_OK,
        )


# =============================================================================
# Update Views
# =============================================================================


class UpdateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for software update distribution.

    GET /api/update/             - List all updates
    GET /api/update/latest       - Get latest version info
    GET /api/update/check/<version> - Check for updates
    GET /api/update/download/latest - Download latest package
    GET /api/update/download/<version> - Download specific version
    GET /api/update/history      - Update history
    """

    queryset = Update.objects.all()
    serializer_class = UpdateSerializer

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        """Get information about the latest available version."""
        update = Update.objects.filter(is_current=True).first()

        if not update:
            return Response({"error": "No updates available"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "version": update.version,
                "release_date": update.release_date.isoformat(),
                "changelog": update.changelog,
                "package_size": update.package_size,
                "package_hash": update.package_hash,
                "min_version": update.min_version,
                "download_url": f"/api/update/download/{update.version}",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="check/(?P<current_version>[^/.]+)")
    def check_update(self, request, current_version=None):
        """Check if an update is available for the given version."""
        latest = Update.objects.filter(is_current=True).first()

        if not latest:
            return Response(
                {
                    "update_available": False,
                    "latest_version": None,
                    "can_upgrade": False,
                    "download_url": None,
                },
                status=status.HTTP_200_OK,
            )

        # Simple version comparison (assumes semver-like format)
        update_available = latest.version != current_version

        # Check if direct upgrade is possible
        can_upgrade = True
        if latest.min_version:
            can_upgrade = self._version_gte(current_version, latest.min_version)

        return Response(
            {
                "update_available": update_available,
                "latest_version": latest.version,
                "can_upgrade": can_upgrade,
                "download_url": f"/api/update/download/{latest.version}" if update_available else None,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="download/latest")
    def download_latest(self, request):
        """Download the latest update package."""
        latest = Update.objects.filter(is_current=True).first()

        if not latest:
            return Response({"error": "No updates available"}, status=status.HTTP_404_NOT_FOUND)

        return self._serve_update_file(latest)

    @action(detail=False, methods=["get"], url_path="download/(?P<version>[^/.]+)")
    def download_version(self, request, version=None):
        """Download an update package for a specific version."""
        update = Update.objects.filter(version=version).first()

        if not update:
            return Response({"error": f"Version {version} not found"}, status=status.HTTP_404_NOT_FOUND)

        return self._serve_update_file(update)

    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        """Get list of all available updates."""
        updates = Update.objects.order_by("-release_date").all()

        return Response(
            [
                {
                    "version": u.version,
                    "release_date": u.release_date.isoformat(),
                    "is_current": u.is_current,
                    "changelog": u.changelog,
                }
                for u in updates
            ],
            status=status.HTTP_200_OK,
        )

    def _serve_update_file(self, update):
        """Serve an update package file."""
        updates_dir = Path(getattr(settings, "UPDATES_DIR", "updates"))

        if not updates_dir.exists():
            return Response({"error": "Updates directory not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        package_path = updates_dir / update.package_filename

        if not package_path.exists():
            return Response({"error": "Update package not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            return FileResponse(
                open(package_path, "rb"),
                as_attachment=True,
                filename=update.package_filename,
                content_type="application/zip",
            )
        except Exception as e:
            return Response({"error": f"Error serving file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _version_gte(self, version_a: str, version_b: str) -> bool:
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
