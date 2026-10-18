"""
Business logic for lots and auctions.

Views call these functions instead of changing models directly, so every
rule (and every audit log entry) lives in one place.
"""

from datetime import timedelta
from decimal import ROUND_UP, Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from core.models import PlatformConfig
from core.services import log_action
from notifications import services as notifications

from .models import Auction, Bid, Lot, Watchlist

# Anti-sniping: a bid placed in the last SNIPING_WINDOW pushes the end
# time back by EXTENSION (up to PlatformConfig.max_extensions times).
SNIPING_WINDOW = timedelta(minutes=2)
EXTENSION = timedelta(minutes=2)

# Only these roles may place bids.
BIDDING_ROLES = (User.Role.BIDDER, User.Role.SELLER)


class LotStateError(Exception):
    """Raised when an action is not allowed in the lot's current status."""


class BidError(Exception):
    """Raised when a bid breaks one of the bidding rules."""


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
        notifications.notify_lot_approved(lot, auction)
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
        notifications.notify_lot_rejected(lot)
    return lot


# ---------------------------------------------------------------------------
# Bidding
# ---------------------------------------------------------------------------


def minimum_bid(auction):
    """
    Return the lowest amount the next bid may be.

    - No bids yet: the lot's starting price.
    - Otherwise: highest bid x (1 + increment%), rounded UP to whole cents
      so the minimum is never below the exact percentage.
    """
    highest = auction.highest_bid()
    if highest is None:
        return auction.lot.starting_price

    increment = PlatformConfig.load().bid_increment_percent
    minimum = highest.amount * (1 + increment / Decimal("100"))
    return minimum.quantize(Decimal("0.01"), rounding=ROUND_UP)


def place_bid(bidder, auction, amount):
    """
    Place a bid, applying every bidding rule.

    Everything runs inside one transaction. select_for_update() locks the
    auction row, so if two people bid at the same moment the second one
    waits until the first has finished. That way both bids are checked
    against the real current highest bid (no race condition).
    """
    if bidder.role not in BIDDING_ROLES:
        raise BidError("Your account type cannot place bids.")

    with transaction.atomic():
        auction = (
            Auction.objects.select_for_update()
            .select_related("lot")
            .get(pk=auction.pk)
        )
        now = timezone.now()

        if auction.lot.seller_id == bidder.pk:
            raise BidError("You cannot bid on your own lot.")
        if auction.status != Auction.Status.ACTIVE or now >= auction.end_time:
            raise BidError("This auction is closed.")

        minimum = minimum_bid(auction)
        if amount < minimum:
            raise BidError(f"Your bid must be at least ${minimum}.")

        # Remember who was winning, so they can be told they were outbid.
        previous_bid = auction.highest_bid()
        bid = Bid.objects.create(auction=auction, bidder=bidder, amount=amount)
        if previous_bid and previous_bid.bidder_id != bidder.pk:
            notifications.notify_outbid(previous_bid, bid)
        log_action(bidder, "BID_PLACED", target=bid,
                   details=f"${amount} on auction {auction.pk}")

        # Anti-sniping: a late bid gives everyone else time to respond.
        max_extensions = PlatformConfig.load().max_extensions
        time_left = auction.end_time - now
        if (time_left <= SNIPING_WINDOW
                and auction.extension_count < max_extensions):
            auction.end_time += EXTENSION
            auction.extension_count += 1
            auction.save(update_fields=["end_time", "extension_count"])
            log_action(
                None,
                "AUCTION_EXTENDED",
                target=auction,
                details=(
                    f"Extension {auction.extension_count} of "
                    f"{max_extensions}, new end "
                    f"{auction.end_time:%Y-%m-%d %H:%M:%S} UTC"
                ),
            )
    return bid


def withdraw_bid(moderator, bid, reason):
    """
    Withdraw a bid (Moderators only). The bid is kept but marked as
    withdrawn, so the next highest bid becomes the leader.
    """
    with transaction.atomic():
        # Lock the auction, just like place_bid, so a withdrawal and a new
        # bid cannot interleave.
        auction = Auction.objects.select_for_update().get(pk=bid.auction_id)
        bid = Bid.objects.get(pk=bid.pk)

        if auction.status != Auction.Status.ACTIVE:
            raise BidError("Bids can only be withdrawn while the auction "
                           "is active.")
        if bid.is_withdrawn:
            raise BidError("This bid has already been withdrawn.")

        bid.is_withdrawn = True
        bid.withdrawn_by = moderator
        bid.withdrawn_at = timezone.now()
        bid.withdrawal_reason = reason
        bid.save()
        log_action(moderator, "BID_WITHDRAWN", target=bid,
                   details=f"${bid.amount} by {bid.bidder.username}: {reason}")
    return bid


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


def toggle_watch(user, auction):
    """
    Add the auction to the user's watchlist, or remove it if it is
    already there. Returns True if the auction is now being watched.
    """
    with transaction.atomic():
        deleted, _ = Watchlist.objects.filter(
            user=user, auction=auction
        ).delete()
        if deleted:
            log_action(user, "WATCHLIST_REMOVED", target=auction)
            return False

        Watchlist.objects.create(user=user, auction=auction)
        log_action(user, "WATCHLIST_ADDED", target=auction)
        return True


# ---------------------------------------------------------------------------
# Closing auctions
# ---------------------------------------------------------------------------


def close_auction(auction):
    """
    Close one auction whose end time has passed.

    - Highest bid >= reserve (or no reserve): SOLD, and a Payment is
      created for the winning bidder.
    - Otherwise (no bids, or reserve not met): NOT_SOLD.

    Returns True if the auction was closed by this call.
    """
    # Imported here, not at the top, because payments.services imports
    # auctions.models; importing it at the top could cause a circular
    # import.
    from payments.services import create_payment

    with transaction.atomic():
        # Same lock as place_bid, so no bid can sneak in while closing.
        auction = (
            Auction.objects.select_for_update()
            .select_related("lot")
            .get(pk=auction.pk)
        )
        # Check again under the lock: another worker may have closed it,
        # or a last-second bid may have extended it.
        if (auction.status != Auction.Status.ACTIVE
                or timezone.now() < auction.end_time):
            return False

        winning_bid = auction.highest_bid()
        reserve = auction.lot.reserve_price
        reserve_met = winning_bid is not None and (
            reserve is None or winning_bid.amount >= reserve
        )

        if reserve_met:
            auction.status = Auction.Status.SOLD
            auction.save(update_fields=["status"])
            payment = create_payment(auction, winning_bid)
            notifications.notify_auction_sold(payment)
            details = (f"Sold to {winning_bid.bidder.username} "
                       f"for ${winning_bid.amount}")
        else:
            auction.status = Auction.Status.NOT_SOLD
            auction.save(update_fields=["status"])
            if winning_bid is None:
                details = "No bids"
            else:
                details = (f"Reserve not met (highest bid "
                           f"${winning_bid.amount})")
            notifications.notify_auction_not_sold(auction, details)

        log_action(None, "AUCTION_CLOSED", target=auction, details=details)
    return True


def close_ended_auctions():
    """Close every ACTIVE auction past its end time. Returns how many."""
    ended = Auction.objects.filter(
        status=Auction.Status.ACTIVE,
        end_time__lte=timezone.now(),
    )

    closed = 0
    for auction in ended:
        # One transaction per auction, so one failure does not undo the
        # others.
        if close_auction(auction):
            closed += 1
    return closed
