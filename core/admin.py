from django.contrib import admin

from .models import AuditLog, Dispute, PlatformConfig
from .services import log_action


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only view of the audit log. Entries can never be changed."""

    list_display = ("created_at", "user", "action", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("user__username", "action", "details")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "bid_increment_percent",
        "commission_percent",
        "max_extensions",
        "updated_at",
    )

    def has_add_permission(self, request):
        # Only allow "add" while the single row does not exist yet.
        return not PlatformConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Record which fields changed and their new values.
        changes = ", ".join(
            f"{name}={form.cleaned_data[name]}" for name in form.changed_data
        )
        log_action(
            request.user,
            "CONFIG_UPDATED",
            target=obj,
            details=changes,
        )


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    """View-only: disputes are raised and resolved on the website."""

    list_display = ("created_at", "payment", "raised_by", "reason", "status")
    list_filter = ("status", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
