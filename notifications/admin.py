from django.contrib import admin

from auctions.admin import ViewOnlyAdmin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(ViewOnlyAdmin):
    list_display = ("created_at", "user", "subject", "is_read", "emailed_at")
    list_filter = ("is_read",)
    search_fields = ("user__username", "subject")
