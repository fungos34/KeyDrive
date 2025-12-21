"""
DRF Serializers for KeyDrive Server API.

CHG-20251221-013: Serializers for API endpoints.
"""

from rest_framework import serializers

from .models import Device, Key, Seed, Update, VerificationLog


class DeviceSerializer(serializers.ModelSerializer):
    """Serializer for Device model."""

    class Meta:
        model = Device
        fields = [
            "id",
            "device_id_hash",
            "first_seen",
            "last_verified",
            "current_version",
            "locked",
        ]
        read_only_fields = ["id", "first_seen"]


class SeedSerializer(serializers.ModelSerializer):
    """Serializer for Seed model."""

    device_id_hash = serializers.CharField(source="device.device_id_hash", read_only=True)

    class Meta:
        model = Seed
        fields = [
            "id",
            "device_id_hash",
            "encrypted_seed",
            "key_fingerprints",
            "salt",
            "created_at",
            "locked",
        ]
        read_only_fields = ["id", "created_at"]


class SeedCreateSerializer(serializers.Serializer):
    """Serializer for creating seeds."""

    device_id_hash = serializers.CharField(max_length=64)
    encrypted_seed = serializers.CharField()
    key_fingerprints = serializers.CharField()
    salt = serializers.CharField(max_length=64)


class SeedRetrieveSerializer(serializers.Serializer):
    """Serializer for seed retrieval request."""

    device_id_hash = serializers.CharField(max_length=64)
    key_fingerprint = serializers.CharField(max_length=64)


class KeySerializer(serializers.ModelSerializer):
    """Serializer for Key model."""

    class Meta:
        model = Key
        fields = [
            "id",
            "fingerprint",
            "status",
            "reported_at",
            "reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class KeyStatusUpdateSerializer(serializers.Serializer):
    """Serializer for key status updates (lost/revoke)."""

    fingerprint = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(choices=["lost", "revoked"])
    reason = serializers.CharField(required=False, allow_blank=True)


class VerificationLogSerializer(serializers.ModelSerializer):
    """Serializer for VerificationLog model."""

    device_id_hash = serializers.CharField(source="device.device_id_hash", read_only=True)

    class Meta:
        model = VerificationLog
        fields = [
            "id",
            "device_id_hash",
            "timestamp",
            "hash_value",
            "result",
            "ip_address",
            "user_agent",
        ]
        read_only_fields = ["id", "timestamp"]


class UpdateSerializer(serializers.ModelSerializer):
    """Serializer for Update model."""

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Update
        fields = [
            "id",
            "version",
            "release_date",
            "package_filename",
            "package_hash",
            "package_size",
            "changelog",
            "min_version",
            "is_current",
            "download_url",
        ]
        read_only_fields = ["id", "release_date"]

    def get_download_url(self, obj) -> str:
        """Generate download URL for the update package."""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/update/download/{obj.version}")
        return f"/api/update/download/{obj.version}"


class VerifyRequestSerializer(serializers.Serializer):
    """Serializer for integrity verification requests."""

    device_id_hash = serializers.CharField(max_length=64)
    hash = serializers.CharField(max_length=128)
    version = serializers.CharField(max_length=32, required=False)


class VerifyResponseSerializer(serializers.Serializer):
    """Serializer for integrity verification responses."""

    status = serializers.ChoiceField(choices=["verified", "failed", "error"])
    message = serializers.CharField()
    timestamp = serializers.DateTimeField()
    update_available = serializers.BooleanField(required=False)
    latest_version = serializers.CharField(required=False)


class UpdateCheckSerializer(serializers.Serializer):
    """Serializer for update check requests."""

    current_version = serializers.CharField(max_length=32)


class UpdateCheckResponseSerializer(serializers.Serializer):
    """Serializer for update check responses."""

    update_available = serializers.BooleanField()
    latest_version = serializers.CharField(required=False)
    changelog = serializers.CharField(required=False)
    package_hash = serializers.CharField(required=False)
    package_size = serializers.IntegerField(required=False)
    download_url = serializers.CharField(required=False)
