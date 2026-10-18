"""Business logic for the core app."""

from django.db import transaction
from django.utils import timezone

from notifications import services as notifications

from .models import AuditLog, Dispute


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


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


class DisputeError(Exception):
    """Raised when a dispute action is not allowed."""


def is_party_to(user, payment):
    """True if the user is the buyer or the seller in this sale."""
    return user.pk in (payment.buyer_id, payment.auction.lot.seller_id)


def raise_dispute(user, payment, form):
    """
    Open a dispute from a valid DisputeForm. Only the buyer or seller may,
    and only one OPEN dispute per person per sale.
    """
    if not is_party_to(user, payment):
        raise DisputeError("Only the buyer or seller can raise a dispute.")
    if payment.disputes.filter(raised_by=user,
                               status=Dispute.Status.OPEN).exists():
        raise DisputeError("You already have an open dispute for this sale.")

    with transaction.atomic():
        dispute = form.save(commit=False)
        dispute.payment = payment
        dispute.raised_by = user
        dispute.save()
        log_action(user, "DISPUTE_RAISED", target=dispute,
                   details=dispute.get_reason_display())
        notifications.notify_dispute_raised(dispute)
    return dispute


def resolve_dispute(admin, dispute, resolution):
    """Close an OPEN dispute with a written resolution (Admins only)."""
    with transaction.atomic():
        dispute = Dispute.objects.select_for_update().get(pk=dispute.pk)
        if dispute.status != Dispute.Status.OPEN:
            raise DisputeError("This dispute is already resolved.")

        dispute.status = Dispute.Status.RESOLVED
        dispute.resolution = resolution
        dispute.resolved_by = admin
        dispute.resolved_at = timezone.now()
        dispute.save()
        log_action(admin, "DISPUTE_RESOLVED", target=dispute,
                   details=resolution)
        notifications.notify_dispute_resolved(dispute)
    return dispute
