from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from core.services import log_action

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Django admin for our User, with the role field added."""

    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")

    # Add "role" to the edit page and the "add user" page.
    role_section = (("Role", {"fields": ("role",)}),)
    fieldsets = UserAdmin.fieldsets + role_section
    add_fieldsets = UserAdmin.add_fieldsets + role_section

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Never write the password (even hashed) into the audit log.
        changed = [
            name for name in form.changed_data if "password" not in name
        ]
        log_action(
            request.user,
            "USER_UPDATED" if change else "USER_CREATED",
            target=obj,
            details="Changed: " + ", ".join(changed),
        )
