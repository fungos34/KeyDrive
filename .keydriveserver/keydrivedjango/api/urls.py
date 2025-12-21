"""
API URL routing for KeyDrive Server.

CHG-20251221-013: Django REST Framework URL configuration matching Flask routes.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DeviceViewSet,
    KeyViewSet,
    SeedViewSet,
    UpdateViewSet,
    VerifyView,
)

router = DefaultRouter()
router.register(r"devices", DeviceViewSet)
router.register(r"keys", KeyViewSet)
router.register(r"seeds", SeedViewSet, basename="seeds")
router.register(r"update", UpdateViewSet)

urlpatterns = [
    # Verification endpoint (Flask compatibility with /api/check)
    path("check", VerifyView.as_view(), name="verify-check"),
    path("verify", VerifyView.as_view(), name="verify"),
    # ViewSet routes
    path("", include(router.urls)),
]
