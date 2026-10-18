"""Business logic for the accounts app."""

from django.db import transaction

from core.services import log_action


def register_user(form):
    """
    Create a new user from a valid RegistrationForm and audit log it.

    transaction.atomic() means the user and the log entry are saved
    together: if either fails, neither is kept.
    """
    with transaction.atomic():
        user = form.save()
        log_action(
            user,
            "USER_REGISTERED",
            target=user,
            details=f"Registered as {user.get_role_display()}",
        )
    return user
