"""
Django models for KeyDrive Server.

CHG-20251221-013: Django ORM models migrated from SQLAlchemy.

Models:
- Device: Device registration and verification tracking
- Seed: GPG-encrypted seed storage
- Key: Hardware key status tracking
- VerificationLog: Audit log of verification attempts
- Update: Software update metadata
"""

from django.db import models


class Device(models.Model):
    """Device registration and verification tracking."""

    device_id_hash = models.CharField(max_length=64, unique=True, db_index=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_verified = models.DateTimeField(null=True, blank=True)
    current_version = models.CharField(max_length=32, null=True, blank=True)
    locked = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Device"
        verbose_name_plural = "Devices"
        ordering = ["-first_seen"]

    def __str__(self) -> str:
        return f"Device {self.device_id_hash[:8]}..."


class Seed(models.Model):
    """GPG-encrypted seed storage."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        to_field="device_id_hash",
        db_column="device_id_hash",
        related_name="seeds",
    )
    encrypted_seed = models.TextField(help_text="GPG-encrypted, base64-encoded")
    key_fingerprints = models.TextField(help_text="JSON array of fingerprints")
    salt = models.CharField(max_length=64, help_text="Base64-encoded salt")
    created_at = models.DateTimeField(auto_now_add=True)
    locked = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Seed"
        verbose_name_plural = "Seeds"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Seed for {self.device.device_id_hash[:8]}..."


class Key(models.Model):
    """Hardware key status tracking."""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("lost", "Lost"),
        ("revoked", "Revoked"),
    ]

    fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    reported_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hardware Key"
        verbose_name_plural = "Hardware Keys"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Key {self.fingerprint[:8]}... ({self.status})"


class VerificationLog(models.Model):
    """Audit log of verification attempts."""

    RESULT_CHOICES = [
        ("pass", "Pass"),
        ("fail", "Fail"),
        ("error", "Error"),
    ]

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        to_field="device_id_hash",
        db_column="device_id_hash",
        related_name="verification_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    hash_value = models.CharField(max_length=128)
    result = models.CharField(max_length=16, choices=RESULT_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, null=True, blank=True)

    class Meta:
        verbose_name = "Verification Log"
        verbose_name_plural = "Verification Logs"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"Verification {self.device.device_id_hash[:8]}... - {self.result}"


class Update(models.Model):
    """Software update metadata."""

    version = models.CharField(max_length=32, unique=True, db_index=True)
    release_date = models.DateTimeField(auto_now_add=True)
    package_filename = models.CharField(max_length=256)
    package_hash = models.CharField(max_length=128, help_text="SHA-512 hash")
    package_size = models.PositiveIntegerField(help_text="Size in bytes")
    changelog = models.TextField(null=True, blank=True)
    min_version = models.CharField(
        max_length=32, null=True, blank=True, help_text="Minimum version required to upgrade"
    )
    is_current = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Update"
        verbose_name_plural = "Updates"
        ordering = ["-release_date"]

    def __str__(self) -> str:
        current_marker = " (CURRENT)" if self.is_current else ""
        return f"Update {self.version}{current_marker}"

    def save(self, *args, **kwargs):
        """Override save to ensure only one update is marked as current."""
        if self.is_current:
            # Unmark all other updates as current
            Update.objects.exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)
