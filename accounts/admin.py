from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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
