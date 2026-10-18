from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    """A group of lots, e.g. "Furniture" or "Coins and Banknotes"."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Lot(models.Model):
    """
    An item a Seller wants to sell.

    Every lot starts as PENDING. A Moderator then approves it (which
    creates its Auction) or rejects it with a reason.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    # How long the auction runs once the lot is approved.
    DURATION_CHOICES = [
        (1, "1 day"),
        (3, "3 days"),
        (5, "5 days"),
        (7, "7 days"),
        (10, "10 days"),
    ]

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lots",
    )
    # PROTECT stops a category from being deleted while lots still use it.
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="lots",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    starting_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    # The lowest price the seller will accept. Optional; if left empty,
    # any winning bid sells the lot.
    reserve_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    duration_days = models.PositiveSmallIntegerField(
        choices=DURATION_CHOICES,
        default=7,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    # Filled in by the Moderator who reviewed the lot.
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_lots",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def seller_can_edit(self):
        """Sellers may edit a lot until it is approved."""
        return self.status in (self.Status.PENDING, self.Status.REJECTED)


class Auction(models.Model):
    """The live auction for one approved Lot."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SOLD = "SOLD", "Sold"
        NOT_SOLD = "NOT_SOLD", "Not sold"
        CANCELLED = "CANCELLED", "Cancelled"

    # One lot has at most one auction.
    lot = models.OneToOneField(
        Lot,
        on_delete=models.PROTECT,
        related_name="auction",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(db_index=True)
    # How many times anti-sniping has pushed end_time back.
    extension_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["end_time"]

    def __str__(self):
        return f"Auction for {self.lot.title}"

    def highest_bid(self):
        """
        Return the current winning Bid, or None if there are no bids.

        Withdrawn bids are ignored. If two bids have the same amount, the
        earlier one wins.
        """
        return (
            self.bids.filter(is_withdrawn=False)
            .order_by("-amount", "created_at")
            .first()
        )


class Bid(models.Model):
    """
    One bid on an auction.

    Bids are never deleted. A Moderator can withdraw one, which only marks
    it as withdrawn so the history stays complete.
    """

    auction = models.ForeignKey(
        Auction,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    bidder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    is_withdrawn = models.BooleanField(default=False)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawn_bids",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-amount", "created_at"]

    def __str__(self):
        return f"${self.amount} by {self.bidder.username}"


class Watchlist(models.Model):
    """An auction a user wants to keep an eye on."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist",
    )
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name="watchers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        # A user can only watch the same auction once.
        constraints = [
            models.UniqueConstraint(
                fields=["user", "auction"], name="unique_watch"
            ),
        ]

    def __str__(self):
        return f"{self.user.username} watches {self.auction.lot.title}"
