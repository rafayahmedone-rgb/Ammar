"""
Business logic for lots and auctions.

Views call these functions instead of changing models directly, so every
rule (and every audit log entry) lives in one place.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.services import log_action

from .models import Auction, Lot


class LotStateError(Exception):
    """Raised when an action is not allowed in the lot's current status."""


def create_lot(seller, form):
    """Save a new lot from a valid LotForm. It always starts as PENDING."""
    with transaction.atomic():
        lot = form.save(commit=False)
        lot.seller = seller
        lot.status = Lot.Status.PENDING
        lot.save()
        log_action(seller, "LOT_CREATED", target=lot, details=lot.title)
    return lot


def update_lot_by_seller(seller, lot, form):
    """
    Save a seller's changes to their own lot.

    Only PENDING or REJECTED lots may be edited. Editing a REJECTED lot
    sends it back to the Moderators as PENDING.
    """
    if lot.seller_id != seller.pk:
        raise LotStateError("You can only edit your own lots.")

    with transaction.atomic():
        # Re-read the status under a lock, in case a Moderator approved
        # the lot while the seller had the edit form open.
        current = Lot.objects.select_for_update().get(pk=lot.pk)
        if not current.seller_can_edit:
            raise LotStateError("This lot can no longer be edited.")

        lot = form.save(commit=False)
        details = "Changed: " + ", ".join(form.changed_data)
        lot.status = Lot.Status.PENDING
        if current.status == Lot.Status.REJECTED:
            lot.rejection_reason = ""
            details += " (resubmitted for review)"
        # update_fields saves only these columns, never reviewed_by etc.
        lot.save(update_fields=list(form.Meta.fields) + [
            "status", "rejection_reason", "updated_at",
        ])
        log_action(seller, "LOT_UPDATED", target=lot, details=details)
    return lot


def update_lot_by_moderator(moderator, lot, form):
    """
    Save a Moderator's changes. The form only contains category and
    description, so prices can never be changed here.
    """
    with transaction.atomic():
        lot = form.save(commit=False)
        # Save only the fields on the form, so the lot's status and
        # prices in the database are never touched.
        lot.save(update_fields=["category", "description", "updated_at"])
        log_action(
            moderator,
            "LOT_EDITED_BY_MODERATOR",
            target=lot,
            details="Changed: " + ", ".join(form.changed_data),
        )
    return lot


def approve_lot(moderator, lot):
    """
    Approve a PENDING lot and create its Auction.

    The auction starts now and ends after the lot's chosen duration.
    """
    with transaction.atomic():
        # Lock the row so two Moderators cannot approve it at the same time.
        lot = Lot.objects.select_for_update().get(pk=lot.pk)
        if lot.status != Lot.Status.PENDING:
            raise LotStateError("Only pending lots can be approved.")

        now = timezone.now()
        lot.status = Lot.Status.APPROVED
        lot.reviewed_by = moderator
        lot.reviewed_at = now
        lot.save()

        auction = Auction.objects.create(
            lot=lot,
            start_time=now,
            end_time=now + timedelta(days=lot.duration_days),
        )

        log_action(moderator, "LOT_APPROVED", target=lot)
        log_action(
            moderator,
            "AUCTION_CREATED",
            target=auction,
            details=f"Ends {auction.end_time:%Y-%m-%d %H:%M} UTC",
        )
    return auction


def reject_lot(moderator, lot, reason):
    """Reject a PENDING lot. The reason is shown to the seller."""
    with transaction.atomic():
        lot = Lot.objects.select_for_update().get(pk=lot.pk)
        if lot.status != Lot.Status.PENDING:
            raise LotStateError("Only pending lots can be rejected.")

        lot.status = Lot.Status.REJECTED
        lot.reviewed_by = moderator
        lot.reviewed_at = timezone.now()
        lot.rejection_reason = reason
        lot.save()

        log_action(moderator, "LOT_REJECTED", target=lot, details=reason)
    return lot
