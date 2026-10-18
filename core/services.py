"""Business logic for the core app."""

from .models import AuditLog


def log_action(user, action, target=None, details=""):
    """
    Write one AuditLog entry.

    user    -- the user who did the action (None for system actions)
    action  -- short code such as "USER_REGISTERED"
    target  -- the model instance the action was done to (optional)
    details -- extra free text (optional)
    """
    # An anonymous visitor is not a real user row, so store None instead.
    if user is not None and not user.is_authenticated:
        user = None

    target_type = ""
    target_id = None
    if target is not None:
        # e.g. "User" or "Lot"
        target_type = target.__class__.__name__
        target_id = target.pk

    return AuditLog.objects.create(
        user=user,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
