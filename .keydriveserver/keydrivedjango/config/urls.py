"""
URL configuration for KeyDrive Server.

CHG-20251221-013: Django URL routing.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]
