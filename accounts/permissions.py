"""
Helpers that limit a view to users with certain roles.

- Not logged in   -> sent to the login page.
- Wrong role      -> 403 Forbidden.

Function view:
    @role_required(User.Role.MODERATOR, User.Role.ADMIN)
    def approve_lot(request, pk): ...

Class-based view:
    class LotCreateView(RoleRequiredMixin, CreateView):
        allowed_roles = (User.Role.SELLER,)
"""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import User


def role_required(*roles):
    """Decorator for function views. Pass the roles that are allowed."""

    def decorator(view_func):
        # wraps() keeps the original view's name and docstring.
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    """Mixin for class-based views. Set allowed_roles on the view."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            # LoginRequiredMixin's method that redirects to the login page.
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# The same idea for the REST API (Django REST Framework permission classes)
# ---------------------------------------------------------------------------


class HasRole(BasePermission):
    """
    API permission: the user must be logged in and have one of
    allowed_roles. Subclass it and set allowed_roles.
    """

    allowed_roles = ()

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in self.allowed_roles
        )


class IsSeller(HasRole):
    allowed_roles = (User.Role.SELLER,)


class IsModerator(HasRole):
    allowed_roles = (User.Role.MODERATOR,)


class CanBid(HasRole):
    allowed_roles = (User.Role.BIDDER, User.Role.SELLER)
