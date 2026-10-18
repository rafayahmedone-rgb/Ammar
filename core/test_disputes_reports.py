"""Tests for disputes and admin reports."""

import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auctions import services as auction_services
from auctions.models import Auction, Category, Lot
from notifications.models import Notification
from payments import services as payment_services
from payments.models import Payment

from . import services
from .models import AuditLog, Dispute

User = get_user_model()


class SaleTestCase(TestCase):
    """Creates sales: make_sale() runs a lot through to a Payment."""

    def setUp(self):
        def make_user(name, role):
            return User.objects.create_user(
                username=name, password="x", role=role
            )

        self.seller = make_user("sam", User.Role.SELLER)
        self.buyer = make_user("bob", User.Role.BIDDER)
        self.stranger = make_user("eve", User.Role.BIDDER)
        self.moderator = make_user("mia", User.Role.MODERATOR)
        self.admin = make_user("ada", User.Role.ADMIN)
        self.clocks = Category.objects.create(name="Clocks")
        self.coins = Category.objects.create(name="Coins")

    def make_sale(self, amount="200.00", category=None, title="Mantel clock"):
        lot = Lot.objects.create(
            seller=self.seller,
            category=category or self.clocks,
            title=title,
            description="Old and lovely.",
            starting_price=Decimal("10.00"),
        )
        auction = auction_services.approve_lot(self.moderator, lot)
        auction_services.place_bid(self.buyer, auction, Decimal(amount))
        Auction.objects.filter(pk=auction.pk).update(
            end_time=timezone.now() - timedelta(seconds=1)
        )
        auction_services.close_auction(auction)
        return Payment.objects.get(auction=auction)


class DisputeTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.payment = self.make_sale()
        self.create_url = reverse("core:dispute_create",
                                  args=[self.payment.pk])

    def raise_as(self, user, reason="NOT_RECEIVED"):
        self.client.force_login(user)
        return self.client.post(
            self.create_url,
            {"reason": reason, "description": "Nothing arrived."},
        )

    def test_buyer_raises_dispute_and_seller_is_told(self):
        response = self.raise_as(self.buyer)

        dispute = Dispute.objects.get()
        self.assertRedirects(
            response, reverse("core:dispute_detail", args=[dispute.pk])
        )
        self.assertEqual(dispute.raised_by, self.buyer)
        self.assertEqual(dispute.status, Dispute.Status.OPEN)
        self.assertTrue(
            AuditLog.objects.filter(action="DISPUTE_RAISED").exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.seller, subject__startswith="A dispute"
            ).exists()
        )

    def test_dispute_form_page_loads(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.create_url)

        self.assertContains(response, "Item not as described")

    def test_seller_can_raise_dispute(self):
        self.raise_as(self.seller, reason="NON_PAYMENT")

        self.assertEqual(Dispute.objects.get().raised_by, self.seller)

    def test_stranger_cannot_raise_dispute(self):
        response = self.raise_as(self.stranger)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Dispute.objects.exists())

    def test_only_one_open_dispute_per_person(self):
        self.raise_as(self.buyer)
        self.raise_as(self.buyer)

        self.assertEqual(Dispute.objects.count(), 1)

    def test_admin_resolves_and_both_parties_are_told(self):
        self.raise_as(self.buyer)
        dispute = Dispute.objects.get()
        self.client.force_login(self.admin)

        self.client.post(
            reverse("core:dispute_resolve", args=[dispute.pk]),
            {"resolution": "Seller sent tracking number; item delivered."},
        )

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.RESOLVED)
        self.assertEqual(dispute.resolved_by, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(action="DISPUTE_RESOLVED").exists()
        )
        told = set(
            Notification.objects.filter(
                subject__startswith="Dispute resolved"
            ).values_list("user__username", flat=True)
        )
        self.assertEqual(told, {"bob", "sam"})

    def test_cannot_resolve_twice(self):
        self.raise_as(self.buyer)
        dispute = Dispute.objects.get()
        services.resolve_dispute(self.admin, dispute, "Done")

        with self.assertRaises(services.DisputeError):
            services.resolve_dispute(self.admin, dispute, "Again")

    def test_only_admin_can_resolve(self):
        self.raise_as(self.buyer)
        dispute = Dispute.objects.get()

        for user in (self.buyer, self.seller, self.moderator):
            self.client.force_login(user)
            response = self.client.post(
                reverse("core:dispute_resolve", args=[dispute.pk]),
                {"resolution": "I win"},
            )
            self.assertEqual(response.status_code, 403)

    def test_who_can_see_a_dispute(self):
        self.raise_as(self.buyer)
        dispute = Dispute.objects.get()
        url = reverse("core:dispute_detail", args=[dispute.pk])

        for user, expected in (
            (self.buyer, 200),
            (self.seller, 200),
            (self.admin, 200),
            (self.stranger, 404),
        ):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, expected)

    def test_dispute_list(self):
        self.raise_as(self.buyer)

        self.client.force_login(self.seller)
        self.assertContains(
            self.client.get(reverse("core:dispute_list")), "Mantel clock"
        )
        self.client.force_login(self.stranger)
        self.assertNotContains(
            self.client.get(reverse("core:dispute_list")), "Mantel clock"
        )


class ReportTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        # Two paid sales and one unpaid one.
        clock = self.make_sale("200.00")
        coin = self.make_sale("100.00", category=self.coins, title="Coin")
        self.make_sale("50.00", title="Unpaid clock")
        payment_services.pay(self.buyer, clock)
        payment_services.pay(self.buyer, coin)
        self.url = reverse("core:reports")

    def test_only_admins_can_see_reports(self):
        for user in (self.buyer, self.seller, self.moderator):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_sales_numbers(self):
        self.client.force_login(self.admin)

        sales = self.client.get(self.url).context["sales"]

        self.assertEqual(sales["sales_closed"], 3)
        self.assertEqual(sales["awaiting_payment"], 1)
        self.assertEqual(sales["payments_received"], 2)
        self.assertEqual(sales["hammer_total"], Decimal("300.00"))
        self.assertEqual(sales["gst_total"], Decimal("30.00"))
        self.assertEqual(sales["commission_total"], Decimal("30.00"))
        self.assertEqual(sales["payout_total"], Decimal("270.00"))

    def test_auction_and_activity_numbers(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.context["auctions"]["sold"], 3)
        self.assertEqual(response.context["activity"]["bids_placed"], 3)
        self.assertEqual(response.context["activity"]["lots_submitted"], 3)

    def test_sales_by_category_biggest_first(self):
        self.client.force_login(self.admin)

        rows = self.client.get(self.url).context["categories"]

        names = [row["auction__lot__category__name"] for row in rows]
        self.assertEqual(names, ["Clocks", "Coins"])

    def test_date_range_excludes_other_days(self):
        self.client.force_login(self.admin)
        last_year = timezone.localdate() - timedelta(days=365)

        response = self.client.get(
            self.url, {"start": last_year, "end": last_year}
        )

        self.assertEqual(response.context["sales"]["sales_closed"], 0)
        self.assertEqual(
            response.context["sales"]["hammer_total"], Decimal("0.00")
        )

    def test_bad_date_range_falls_back_to_last_30_days(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()

        response = self.client.get(
            self.url, {"start": today, "end": today - timedelta(days=5)}
        )

        self.assertContains(response, "The start date must be first.")
        self.assertEqual(response.context["sales"]["sales_closed"], 3)

    def test_csv_export(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("core:report_payments_csv"))

        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(response.content.decode().splitlines()))
        self.assertEqual(rows[0][:3], ["Closed", "Lot", "Category"])
        self.assertEqual(len(rows), 4)  # header + 3 sales
        self.assertEqual(rows[1][1], "Mantel clock")
        self.assertEqual(rows[1][8], "220.00")
