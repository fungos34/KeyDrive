"""
Django Admin configuration for KeyDrive Server.

CHG-20251221-013: Admin site for all models.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Device, Key, Seed, Update, VerificationLog


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Admin for Device model."""

    list_display = [
        "device_id_hash_short",
        "first_seen",
        "last_verified",
        "current_version",
        "locked_display",
    ]
    list_filter = ["locked", "current_version"]
    search_fields = ["device_id_hash"]
    readonly_fields = ["first_seen"]
    date_hierarchy = "first_seen"
    ordering = ["-first_seen"]

    def device_id_hash_short(self, obj):
        """Display truncated device hash."""
        return f"{obj.device_id_hash[:16]}..."

    device_id_hash_short.short_description = "Device Hash"

    def locked_display(self, obj):
        """Display lock status with color."""
        if obj.locked:
            return format_html('<span style="color: red;">🔒 LOCKED</span>')
        return format_html('<span style="color: green;">✓ Active</span>')

    locked_display.short_description = "Status"

    actions = ["lock_devices", "unlock_devices"]

    @admin.action(description="🔒 Lock selected devices")
    def lock_devices(self, request, queryset):
        count = queryset.update(locked=True)
        # Also lock related seeds
        Seed.objects.filter(device__in=queryset).update(locked=True)
        self.message_user(request, f"{count} device(s) locked.")

    @admin.action(description="🔓 Unlock selected devices")
    def unlock_devices(self, request, queryset):
        count = queryset.update(locked=False)
        self.message_user(request, f"{count} device(s) unlocked.")


@admin.register(Seed)
class SeedAdmin(admin.ModelAdmin):
    """Admin for Seed model."""

    list_display = [
        "id",
        "device_hash_short",
        "created_at",
        "fingerprints_short",
        "locked_display",
    ]
    list_filter = ["locked", "created_at"]
    search_fields = ["device__device_id_hash", "key_fingerprints"]
    readonly_fields = ["created_at"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def device_hash_short(self, obj):
        """Display truncated device hash."""
        return f"{obj.device.device_id_hash[:16]}..."

    device_hash_short.short_description = "Device"

    def fingerprints_short(self, obj):
        """Display truncated fingerprints."""
        fps = obj.key_fingerprints
        if len(fps) > 40:
            return f"{fps[:40]}..."
        return fps

    fingerprints_short.short_description = "Key Fingerprints"

    def locked_display(self, obj):
        """Display lock status with color."""
        if obj.locked:
            return format_html('<span style="color: red;">🔒 LOCKED</span>')
        return format_html('<span style="color: green;">✓ Available</span>')

    locked_display.short_description = "Status"

    actions = ["lock_seeds", "unlock_seeds"]

    @admin.action(description="🔒 Lock selected seeds")
    def lock_seeds(self, request, queryset):
        count = queryset.update(locked=True)
        self.message_user(request, f"{count} seed(s) locked.")

    @admin.action(description="🔓 Unlock selected seeds")
    def unlock_seeds(self, request, queryset):
        count = queryset.update(locked=False)
        self.message_user(request, f"{count} seed(s) unlocked.")


@admin.register(Key)
class KeyAdmin(admin.ModelAdmin):
    """Admin for Key model."""

    list_display = [
        "fingerprint_short",
        "status_display",
        "reported_at",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["fingerprint", "reason"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def fingerprint_short(self, obj):
        """Display truncated fingerprint."""
        return f"{obj.fingerprint[:16]}..."

    fingerprint_short.short_description = "Fingerprint"

    def status_display(self, obj):
        """Display status with color."""
        colors = {
            "active": "green",
            "lost": "orange",
            "revoked": "red",
        }
        icons = {
            "active": "✓",
            "lost": "⚠️",
            "revoked": "❌",
        }
        return format_html(
            '<span style="color: {};">{} {}</span>',
            colors.get(obj.status, "gray"),
            icons.get(obj.status, "?"),
            obj.status.upper(),
        )

    status_display.short_description = "Status"

    actions = ["mark_lost", "mark_revoked", "mark_active"]

    @admin.action(description="⚠️ Mark as LOST")
    def mark_lost(self, request, queryset):
        from django.utils import timezone

        count = queryset.update(status="lost", reported_at=timezone.now())
        # Lock seeds using these keys
        for key in queryset:
            Seed.objects.filter(key_fingerprints__contains=key.fingerprint).update(locked=True)
        self.message_user(request, f"{count} key(s) marked as lost.")

    @admin.action(description="❌ Mark as REVOKED")
    def mark_revoked(self, request, queryset):
        from django.utils import timezone

        count = queryset.update(status="revoked", reported_at=timezone.now())
        # Lock seeds using these keys
        for key in queryset:
            Seed.objects.filter(key_fingerprints__contains=key.fingerprint).update(locked=True)
        self.message_user(request, f"{count} key(s) revoked.")

    @admin.action(description="✓ Mark as ACTIVE")
    def mark_active(self, request, queryset):
        count = queryset.update(status="active", reported_at=None)
        self.message_user(request, f"{count} key(s) marked as active.")


@admin.register(VerificationLog)
class VerificationLogAdmin(admin.ModelAdmin):
    """Admin for VerificationLog model."""

    list_display = [
        "id",
        "device_hash_short",
        "timestamp",
        "result_display",
        "ip_address",
    ]
    list_filter = ["result", "timestamp"]
    search_fields = ["device__device_id_hash", "hash_value", "ip_address"]
    readonly_fields = ["timestamp"]
    date_hierarchy = "timestamp"
    ordering = ["-timestamp"]

    def device_hash_short(self, obj):
        """Display truncated device hash."""
        return f"{obj.device.device_id_hash[:16]}..."

    device_hash_short.short_description = "Device"

    def result_display(self, obj):
        """Display result with color."""
        colors = {
            "pass": "green",
            "fail": "red",
            "error": "orange",
        }
        icons = {
            "pass": "✅",
            "fail": "❌",
            "error": "⚠️",
        }
        return format_html(
            '<span style="color: {};">{} {}</span>',
            colors.get(obj.result, "gray"),
            icons.get(obj.result, "?"),
            obj.result.upper(),
        )

    result_display.short_description = "Result"


@admin.register(Update)
class UpdateAdmin(admin.ModelAdmin):
    """Admin for Update model."""

    list_display = [
        "version",
        "release_date",
        "package_size_display",
        "is_current_display",
    ]
    list_filter = ["is_current", "release_date"]
    search_fields = ["version", "changelog"]
    readonly_fields = ["release_date"]
    date_hierarchy = "release_date"
    ordering = ["-release_date"]

    def package_size_display(self, obj):
        """Display human-readable package size."""
        size = obj.package_size
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} bytes"

    package_size_display.short_description = "Size"

    def is_current_display(self, obj):
        """Display current status with indicator."""
        if obj.is_current:
            return format_html('<span style="color: green; font-weight: bold;">★ CURRENT</span>')
        return ""

    is_current_display.short_description = "Current"

    actions = ["set_as_current"]

    @admin.action(description="★ Set as CURRENT version")
    def set_as_current(self, request, queryset):
        if queryset.count() > 1:
            self.message_user(request, "Please select only one update to set as current.", level="error")
            return
        # Unset all current
        Update.objects.update(is_current=False)
        # Set selected as current
        queryset.update(is_current=True)
        self.message_user(request, f"Version {queryset.first().version} set as current.")


# Customize admin site
admin.site.site_header = "KeyDrive Server Administration"
admin.site.site_title = "KeyDrive Admin"
admin.site.index_title = "Server Management"
