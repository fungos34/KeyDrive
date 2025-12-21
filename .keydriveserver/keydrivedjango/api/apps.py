"""App configuration for the API app."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """API application configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "KeyDrive API"
