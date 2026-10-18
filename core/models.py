from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AuditLog(models.Model):
    """
    One row for every state-changing action on the platform.

    Rows are only ever added, never edited or deleted, so they form a
    permanent history of who did what and when.
    """

    # SET_NULL keeps the log entry even if the user is deleted later.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    # A short code for the action, e.g. "USER_REGISTERED".
    action = models.CharField(max_length=50)
    # What the action was done to, e.g. target_type="Lot", target_id=7.
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    # Free text with any extra information.
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.user.username if self.user else "system"
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action}"


class PlatformConfig(models.Model):
    """
    Site-wide settings that an Admin can change without touching code.

    There is only ever one row (a "singleton"). Always read it with
    PlatformConfig.load().
    """

    percent_validators = [MinValueValidator(0), MaxValueValidator(100)]

    # Each new bid must beat the current highest bid by this percentage.
    bid_increment_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        validators=percent_validators,
    )
    # The platform's commission on a sale, as a percentage.
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        validators=percent_validators,
    )
    # How many times anti-sniping may extend one auction.
    max_extensions = models.PositiveSmallIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "platform configuration"
        verbose_name_plural = "platform configuration"

    def __str__(self):
        return "Platform configuration"

    def save(self, *args, **kwargs):
        # Force the primary key to 1 so a second row can never be created.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the single config row, creating it with defaults."""
        config, _created = cls.objects.get_or_create(pk=1)
        return config


class Dispute(models.Model):
    """
    A problem with a sale, raised by its buyer or seller and resolved by
    an Admin.
    """

    class Reason(models.TextChoices):
        NOT_RECEIVED = "NOT_RECEIVED", "Item not received"
        NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED", "Item not as described"
        NON_PAYMENT = "NON_PAYMENT", "Buyer has not paid"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    # A string reference ("app.Model") avoids importing the payments app.
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="disputes",
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="disputes_raised",
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    resolution = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disputes_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dispute {self.pk}: {self.get_reason_display()}"
