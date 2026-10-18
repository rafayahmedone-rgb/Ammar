"""Tests for the payments and notifications REST API."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from auctions import services as auction_services
from auctions.models import Auction, Category, Lot
from notifications.models import Notification

from .models import Payment

User = get_user_model()


class PaymentApiTests(APITestCase):
    def setUp(self):
        def make_user(name, role):
            return User.objects.create_user(
                username=name, password="x", role=role
            )

        self.seller = make_user("sam", User.Role.SELLER)
        self.buyer = make_user("bob", User.Role.BIDDER)
        self.stranger = make_user("eve", User.Role.BIDDER)
        self.admin = make_user("ada", User.Role.ADMIN)
        moderator = make_user("mia", User.Role.MODERATOR)

        lot = Lot.objects.create(
            seller=self.seller,
            category=Category.objects.create(name="Clocks"),
            title="Mantel clock",
            description="Working 1920s mantel clock.",
            starting_price=Decimal("100.00"),
        )
        auction = auction_services.approve_lot(moderator, lot)
        auction_services.place_bid(self.buyer, auction, Decimal("200.00"))
        Auction.objects.filter(pk=auction.pk).update(
            end_time=timezone.now() - timedelta(seconds=1)
        )
        auction_services.close_ended_auctions()
        self.payment = Payment.objects.get()

    def test_my_purchases(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.get(reverse("api:payments"))

        result = response.data["results"][0]
        self.assertEqual(result["lot_title"], "Mantel clock")
        self.assertEqual(result["gst_amount"], "20.00")
        self.assertEqual(result["total_amount"], "220.00")
        self.assertEqual(result["status"], "PENDING")

    def test_payment_detail_access(self):
        url = reverse("api:payment_detail", args=[self.payment.pk])
        for user, expected in (
            (self.buyer, 200),
            (self.seller, 200),
            (self.admin, 200),
            (self.stranger, 404),
        ):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(url).status_code, expected)

    def test_pay_now(self):
        url = reverse("api:pay_now", args=[self.payment.pk])

        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.post(url).status_code, 400)

        self.client.force_authenticate(self.buyer)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "PAID")
        self.assertTrue(response.data["reference"].startswith("MOCK-"))

        # Paying twice is refused.
        self.assertEqual(self.client.post(url).status_code, 400)

    def test_requires_login(self):
        self.assertEqual(
            self.client.get(reverse("api:payments")).status_code, 401
        )

    def test_notifications_list_and_mark_read(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.get(reverse("api:notifications"))
        subjects = [n["subject"] for n in response.data["results"]]
        self.assertIn('You won "Mantel clock"', subjects)

        response = self.client.post(reverse("api:notifications_mark_read"))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Notification.objects.filter(user=self.buyer, is_read=False)
            .exists()
        )
        # Other users' notifications are untouched.
        self.assertTrue(
            Notification.objects.filter(user=self.seller, is_read=False)
            .exists()
        )
