"""
Business logic for payments.

The "Pay now" step is mocked: no real money moves. Pressing the button
simply marks the payment as PAID and stores a fake transaction reference.
"""

import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from auctions.models import Auction
from core.models import PlatformConfig
from core.services import log_action

from .models import Payment

# Australian GST is a flat 10%.
GST_RATE = Decimal("0.10")
# How long the buyer has to pay after the auction closes.
PAYMENT_WINDOW = timedelta(hours=48)

CENT = Decimal("0.01")


class PaymentError(Exception):
    """Raised when a payment action is not allowed."""


def to_cents(value):
    """Round a Decimal to whole cents, with .5 rounding up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_amounts(hammer_price, commission_percent):
    """
    Work out every amount for a sale. Returns a dict, e.g. for a $200
    hammer price and 10% commission:

        gst_amount 20.00, total_amount 220.00,
        commission_amount 20.00, seller_payout 180.00
    """
    gst_amount = to_cents(hammer_price * GST_RATE)
    commission_amount = to_cents(
        hammer_price * commission_percent / Decimal("100")
    )
    return {
        "hammer_price": hammer_price,
        "gst_amount": gst_amount,
        "total_amount": hammer_price + gst_amount,
        "commission_percent": commission_percent,
        "commission_amount": commission_amount,
        "seller_payout": hammer_price - commission_amount,
    }


def create_payment(auction, winning_bid):
    """
    Create the Payment for a SOLD auction.

    Called by auctions.services.close_auction, inside its transaction.
    """
    commission_percent = PlatformConfig.load().commission_percent
    amounts = calculate_amounts(winning_bid.amount, commission_percent)

    payment = Payment.objects.create(
        auction=auction,
        buyer=winning_bid.bidder,
        due_at=timezone.now() + PAYMENT_WINDOW,
        **amounts,  # passes each key of the dict as a field value
    )
    log_action(
        None,
        "PAYMENT_CREATED",
        target=payment,
        details=(
            f"Buyer {payment.buyer.username} owes ${payment.total_amount}, "
            f"due {payment.due_at:%Y-%m-%d %H:%M} UTC"
        ),
    )
    return payment


def pay(user, payment):
    """Mock "Pay now": mark the payment as PAID."""
    with transaction.atomic():
        # Lock the row so the expiry task cannot run at the same moment.
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        if payment.buyer_id != user.pk:
            raise PaymentError("Only the buyer can pay for this item.")
        if payment.status != Payment.Status.PENDING:
            raise PaymentError("This payment is no longer awaiting payment.")
        if timezone.now() >= payment.due_at:
            raise PaymentError("The time to pay for this item has passed.")

        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        # A made-up reference like "MOCK-3F9A1C2B7D".
        payment.reference = "MOCK-" + uuid.uuid4().hex[:10].upper()
        payment.save()

        log_action(user, "PAYMENT_PAID", target=payment,
                   details=f"${payment.total_amount}, ref {payment.reference}")
    return payment


def expire_payment(payment):
    """
    Expire one unpaid payment that is past its due time. The sale falls
    through, so the auction becomes NOT_SOLD.

    Returns True if the payment was expired.
    """
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        # Check again under the lock: it may have been paid meanwhile.
        if (payment.status != Payment.Status.PENDING
                or timezone.now() < payment.due_at):
            return False

        payment.status = Payment.Status.EXPIRED
        payment.save(update_fields=["status"])

        auction = Auction.objects.select_for_update().get(
            pk=payment.auction_id
        )
        auction.status = Auction.Status.NOT_SOLD
        auction.save(update_fields=["status"])

        log_action(None, "PAYMENT_EXPIRED", target=payment,
                   details="Not paid within 48 hours")
        log_action(None, "AUCTION_NOT_SOLD", target=auction,
                   details="Buyer did not pay")
    return True


def expire_overdue_payments():
    """Expire every overdue unpaid payment. Returns how many expired."""
    overdue = Payment.objects.filter(
        status=Payment.Status.PENDING,
        due_at__lte=timezone.now(),
    )

    expired = 0
    for payment in overdue:
        # Each payment gets its own transaction, so one failure does not
        # undo the others.
        if expire_payment(payment):
            expired += 1
    return expired
