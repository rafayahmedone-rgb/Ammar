from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    What the winning bidder owes for a SOLD auction.

    All amounts are worked out once, when the auction closes, and stored.
    That way a later change to the commission rate never changes an
    existing sale.

        hammer_price      the winning bid
        gst_amount        10% GST on the hammer price
        total_amount      what the buyer pays = hammer_price + gst_amount
        commission_amount the platform's cut of the hammer price
        seller_payout     what the seller receives
                          = hammer_price - commission_amount
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting payment"
        PAID = "PAID", "Paid"
        EXPIRED = "EXPIRED", "Expired (not paid in time)"

    auction = models.OneToOneField(
        "auctions.Auction",
        on_delete=models.PROTECT,
        related_name="payment",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    hammer_price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    # The commission rate used for this sale, kept for the record.
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    seller_payout = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    # The buyer must pay before this time (48 hours after the close).
    due_at = models.DateTimeField(db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # When the "please pay" reminder was sent (so it is only sent once).
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    # The (mock) payment provider's transaction reference.
    reference = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.pk} for {self.auction.lot.title}"
