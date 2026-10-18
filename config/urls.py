"""
Top-level URL configuration.

Web pages use normal URLs; the REST API will live under /api/ in a later
phase.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("auctions/", include("auctions.urls")),
    path("", include("core.urls")),
]
