"""
Top-level URL configuration.

Web pages use normal URLs; the REST API will live under /api/ in a later
phase.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
