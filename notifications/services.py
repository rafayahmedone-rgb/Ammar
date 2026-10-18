"""
Creating notifications.

Other apps call the notify_... functions below. Each one saves a
Notification and queues an email for it.
"""

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Notification
from .tasks import send_notification_email


def site_link(url_name, *args):
    """Full link for an email, e.g. http://127.0.0.1:8000/auctions/lots/3/"""
    return settings.SITE_URL + reverse(url_name, args=args)


def local_time(value):
    """Format a datetime in Australia/Sydney time for an email."""
    return timezone.localtime(value).strftime("%d %b %Y, %I:%M %p")


def notify(user, subject, message):
    """
    Save a Notification for the user and queue its email.

    transaction.on_commit() waits until the surrounding database
    transaction has been saved before queueing the email. If the
    transaction is rolled back (e.g. a bid fails), no email goes out.
    robust=True means a problem queueing the email (e.g. Redis is down)
    is logged instead of breaking the user's request.
    """
    notification = Notification.objects.create(
        user=user, subject=subject, message=message
    )
    transaction.on_commit(
        lambda: send_notification_email.delay(notification.pk),
        robust=True,
    )
    return notification


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------


def notify_lot_approved(lot, auction):
    notify(
        lot.seller,
        f'Your lot "{lot.title}" is live',
        f'Good news! "{lot.title}" was approved and its auction is now '
        f"open.\n\nIt ends {local_time(auction.end_time)}.\n\n"
        f"{site_link('auctions:lot_detail', lot.pk)}",
    )


def notify_lot_rejected(lot):
    notify(
        lot.seller,
        f'Your lot "{lot.title}" was not approved',
        f'A Moderator did not approve "{lot.title}".\n\n'
        f"Reason: {lot.rejection_reason}\n\n"
        f"You can edit the lot and resubmit it:\n"
        f"{site_link('auctions:lot_edit', lot.pk)}",
    )


# ---------------------------------------------------------------------------
# Bidding
# ---------------------------------------------------------------------------


def notify_outbid(previous_bid, new_bid):
    lot = new_bid.auction.lot
    notify(
        previous_bid.bidder,
        f'You have been outbid on "{lot.title}"',
        f"Your bid of ${previous_bid.amount} has been beaten by a bid of "
        f"${new_bid.amount}.\n\nBid again before "
        f"{local_time(new_bid.auction.end_time)}:\n"
        f"{site_link('auctions:lot_detail', lot.pk)}",
    )


def notify_auction_cancelled(auction, bidders):
    lot = auction.lot
    message = (
        f'The auction for "{lot.title}" has been cancelled.\n'
        f"Reason: {auction.cancellation_reason}\n\n"
        f"Your bids on it no longer count."
    )
    for bidder in bidders:
        notify(bidder, f'Auction cancelled: "{lot.title}"', message)

    # Tell the seller too, unless they cancelled it themselves.
    if auction.cancelled_by_id != lot.seller_id:
        notify(
            lot.seller,
            f'Your auction for "{lot.title}" was cancelled',
            f'An Admin cancelled the auction for "{lot.title}".\n'
            f"Reason: {auction.cancellation_reason}",
        )


# ---------------------------------------------------------------------------
# Auction results
# ---------------------------------------------------------------------------


def notify_auction_sold(payment):
    lot = payment.auction.lot
    payment_link = site_link("payments:payment_detail", payment.pk)
    notify(
        payment.buyer,
        f'You won "{lot.title}"',
        f'Congratulations! You won "{lot.title}" with a bid of '
        f"${payment.hammer_price}.\n\n"
        f"Total to pay (including GST): ${payment.total_amount}\n"
        f"Please pay by {local_time(payment.due_at)}, or the sale will be "
        f"cancelled.\n\n{payment_link}",
    )
    notify(
        lot.seller,
        f'"{lot.title}" sold for ${payment.hammer_price}',
        f'Your lot "{lot.title}" sold for ${payment.hammer_price}.\n'
        f"After commission you will receive ${payment.seller_payout} once "
        f"the buyer pays.\n\n{payment_link}",
    )


def notify_auction_not_sold(auction, reason):
    lot = auction.lot
    notify(
        lot.seller,
        f'"{lot.title}" did not sell',
        f'The auction for "{lot.title}" has ended without a sale.\n'
        f"Reason: {reason}\n\n{site_link('auctions:lot_detail', lot.pk)}",
    )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


def notify_payment_received(payment):
    lot = payment.auction.lot
    payment_link = site_link("payments:payment_detail", payment.pk)
    notify(
        payment.buyer,
        f'Receipt for "{lot.title}"',
        f"Thank you. We received ${payment.total_amount} "
        f"(including ${payment.gst_amount} GST).\n"
        f"Reference: {payment.reference}\n\n{payment_link}",
    )
    notify(
        lot.seller,
        f'The buyer has paid for "{lot.title}"',
        f'The buyer of "{lot.title}" has paid. Your payout is '
        f"${payment.seller_payout}.\n\n{payment_link}",
    )


def notify_payment_reminder(payment):
    lot = payment.auction.lot
    notify(
        payment.buyer,
        f'Reminder: please pay for "{lot.title}"',
        f'You still need to pay ${payment.total_amount} for "{lot.title}".'
        f"\nThe sale will be cancelled if not paid by "
        f"{local_time(payment.due_at)}.\n\n"
        f"{site_link('payments:payment_detail', payment.pk)}",
    )


def notify_payment_expired(payment):
    lot = payment.auction.lot
    notify(
        payment.buyer,
        f'Sale cancelled: "{lot.title}"',
        f'Your purchase of "{lot.title}" was cancelled because payment '
        f"was not received within 48 hours.",
    )
    notify(
        lot.seller,
        f'Sale cancelled: "{lot.title}"',
        f'The buyer did not pay for "{lot.title}" within 48 hours, so the '
        f"sale has been cancelled and the lot is marked as not sold.",
    )


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


def notify_dispute_raised(dispute):
    """Tell the other party in the sale that a dispute was opened."""
    payment = dispute.payment
    lot = payment.auction.lot
    if dispute.raised_by_id == payment.buyer_id:
        other_party = lot.seller
    else:
        other_party = payment.buyer
    notify(
        other_party,
        f'A dispute was raised about "{lot.title}"',
        f"{dispute.raised_by.username} raised a dispute: "
        f"{dispute.get_reason_display()}.\n"
        f"An Admin will review it.\n\n"
        f"{site_link('core:dispute_detail', dispute.pk)}",
    )


def notify_dispute_resolved(dispute):
    """Tell both the buyer and the seller how the dispute was resolved."""
    payment = dispute.payment
    lot = payment.auction.lot
    for user in (payment.buyer, lot.seller):
        notify(
            user,
            f'Dispute resolved: "{lot.title}"',
            f"The dispute about \"{lot.title}\" has been resolved.\n"
            f"Resolution: {dispute.resolution}\n\n"
            f"{site_link('core:dispute_detail', dispute.pk)}",
        )
