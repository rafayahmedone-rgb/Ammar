from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user for the auction site.

    It keeps everything from Django's built-in user (username, email,
    password, ...) and adds a single "role" field.
    """

    class Role(models.TextChoices):
        # Each choice is stored as the first value and shown as the second.
        SELLER = "SELLER", "Seller"
        BIDDER = "BIDDER", "Bidder"
        MODERATOR = "MODERATOR", "Moderator"
        ADMIN = "ADMIN", "Admin"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.BIDDER,
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    # Small helpers so templates and views can write user.is_seller etc.
    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def is_bidder(self):
        return self.role == self.Role.BIDDER

    @property
    def is_moderator(self):
        return self.role == self.Role.MODERATOR

    @property
    def is_admin_role(self):
        # Named "is_admin_role" so it is not confused with Django's
        # is_staff / is_superuser flags.
        return self.role == self.Role.ADMIN
