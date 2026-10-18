"""
Top-level URL configuration.

Web pages use normal URLs; the REST API lives under /api/
(see config/api_urls.py).
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("auctions/", include("auctions.urls")),
    path("payments/", include("payments.urls")),
    path("notifications/", include("notifications.urls")),
    path("api/", include("config.api_urls")),
    path("", include("core.urls")),
]
