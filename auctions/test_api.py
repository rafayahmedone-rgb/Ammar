"""Tests for the REST API (accounts, auctions, bids, lots, moderation)."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core.models import AuditLog

from . import services
from .models import Auction, Category, Lot, Watchlist

User = get_user_model()


class ApiTestCase(APITestCase):
    def setUp(self):
        def make_user(name, role):
            return User.objects.create_user(
                username=name, password="pass12345", role=role
            )

        self.seller = make_user("sam", User.Role.SELLER)
        self.bidder = make_user("bob", User.Role.BIDDER)
        self.bidder2 = make_user("bea", User.Role.BIDDER)
        self.moderator = make_user("mia", User.Role.MODERATOR)
        self.category = Category.objects.create(name="Clocks")
        self.other_category = Category.objects.create(name="Coins")

    def make_lot(self, **overrides):
        data = {
            "seller": self.seller,
            "category": self.category,
            "title": "Mantel clock",
            "description": "Working 1920s mantel clock.",
            "starting_price": Decimal("100.00"),
            "reserve_price": Decimal("150.00"),
        }
        data.update(overrides)
        return Lot.objects.create(**data)

    def make_auction(self):
        self.lot = self.make_lot()
        self.auction = services.approve_lot(self.moderator, self.lot)
        return self.auction

    def login(self, user):
        # Skips the token step for most tests; TokenAuthTests checks it.
        self.client.force_authenticate(user)


class TokenAuthTests(ApiTestCase):
    def test_get_token_and_use_it(self):
        response = self.client.post(
            reverse("api:token"),
            {"username": "bob", "password": "pass12345"},
        )
        self.assertEqual(response.status_code, 200)
        token = response.data["token"]
        self.assertEqual(token, Token.objects.get(user=self.bidder).key)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(reverse("api:me"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "bob")
        self.assertEqual(response.data["role"], "BIDDER")

    def test_wrong_password_gets_no_token(self):
        response = self.client.post(
            reverse("api:token"), {"username": "bob", "password": "nope"}
        )

        self.assertEqual(response.status_code, 400)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse("api:me"))

        self.assertEqual(response.status_code, 401)

    def test_bad_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")

        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)


class PublicApiTests(ApiTestCase):
    def test_categories(self):
        response = self.client.get(reverse("api:categories"))

        names = [category["name"] for category in response.data]
        self.assertEqual(names, ["Clocks", "Coins"])

    def test_auction_list_is_public_and_paginated(self):
        self.make_auction()
        services.place_bid(self.bidder, self.auction, Decimal("120.00"))
        self.make_lot(title="Pending lot")

        response = self.client.get(reverse("api:auctions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        auction = response.data["results"][0]
        self.assertEqual(auction["lot"]["title"], "Mantel clock")
        self.assertEqual(auction["current_price"], "120.00")
        # The reserve price is secret.
        self.assertNotIn("reserve_price", auction["lot"])

    def test_auction_list_ends_soonest_first(self):
        later = services.approve_lot(
            self.moderator, self.make_lot(title="Later", duration_days=10)
        )
        sooner = services.approve_lot(
            self.moderator, self.make_lot(title="Sooner", duration_days=1)
        )
        services.place_bid(self.bidder, later, Decimal("100.00"))

        api_titles = [
            a["lot"]["title"]
            for a in self.client.get(reverse("api:auctions")).data["results"]
        ]
        web_titles = [
            a.lot.title
            for a in self.client.get(
                reverse("auctions:auction_list")
            ).context["auctions"]
        ]

        self.assertEqual(api_titles, ["Sooner", "Later"])
        self.assertEqual(web_titles, ["Sooner", "Later"])
        self.assertLess(sooner.end_time, later.end_time)

    def test_auction_list_category_filter(self):
        self.make_auction()

        response = self.client.get(
            reverse("api:auctions"), {"category": self.other_category.pk}
        )

        self.assertEqual(response.data["count"], 0)

    def test_auction_detail_hides_withdrawn_bids(self):
        self.make_auction()
        services.place_bid(self.bidder, self.auction, Decimal("100.00"))
        bad = services.place_bid(self.bidder2, self.auction, Decimal("500"))
        services.withdraw_bid(self.moderator, bad, "Shill bid")

        response = self.client.get(
            reverse("api:auction_detail", args=[self.auction.pk])
        )

        amounts = [bid["amount"] for bid in response.data["bids"]]
        self.assertEqual(amounts, ["100.00"])
        self.assertEqual(response.data["minimum_bid"], "105.00")


class BiddingApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.make_auction()
        self.url = reverse("api:place_bid", args=[self.auction.pk])

    def test_place_bid(self):
        self.login(self.bidder)

        response = self.client.post(self.url, {"amount": "100.00"},
                                    format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["amount"], "100.00")
        self.assertEqual(response.data["bidder"], "bob")
        self.assertTrue(AuditLog.objects.filter(action="BID_PLACED").exists())

    def test_bid_rules_come_from_the_service(self):
        self.login(self.bidder)

        response = self.client.post(self.url, {"amount": "99.00"},
                                    format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"], "Your bid must be at least $100.00."
        )

    def test_invalid_amount(self):
        self.login(self.bidder)

        response = self.client.post(self.url, {"amount": "lots"},
                                    format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.data)

    def test_seller_cannot_bid_on_own_lot(self):
        self.login(self.seller)

        response = self.client.post(self.url, {"amount": "200.00"},
                                    format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("own lot", response.data["detail"])

    def test_moderator_cannot_bid(self):
        self.login(self.moderator)

        response = self.client.post(self.url, {"amount": "200.00"},
                                    format="json")

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_bid(self):
        response = self.client.post(self.url, {"amount": "200.00"},
                                    format="json")

        self.assertEqual(response.status_code, 401)

    def test_anti_sniping_applies_through_api(self):
        Auction.objects.filter(pk=self.auction.pk).update(
            end_time=timezone.now() + timedelta(seconds=30)
        )
        self.login(self.bidder)

        self.client.post(self.url, {"amount": "100.00"}, format="json")

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.extension_count, 1)

    def test_withdraw_bid_moderator_only(self):
        bid = services.place_bid(self.bidder, self.auction, Decimal("100"))
        url = reverse("api:withdraw_bid", args=[bid.pk])

        self.login(self.bidder)
        response = self.client.post(url, {"reason": "Oops"}, format="json")
        self.assertEqual(response.status_code, 403)

        self.login(self.moderator)
        response = self.client.post(url, {"reason": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {"reason": "Typo"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_withdrawn"])

    def test_cancel_through_api(self):
        url = reverse("api:cancel_auction", args=[self.auction.pk])
        services.place_bid(self.bidder, self.auction, Decimal("100"))

        self.login(self.seller)
        response = self.client.post(url, {"reason": "Oops"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("only an Admin", response.data["detail"])

        admin = User.objects.create_user(
            username="ada", password="x", role=User.Role.ADMIN
        )
        self.login(admin)
        response = self.client.post(url, {"reason": "Fraud"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "CANCELLED")

    def test_watch_toggle_and_watchlist(self):
        self.login(self.bidder)
        url = reverse("api:watch_toggle", args=[self.auction.pk])

        self.assertTrue(self.client.post(url).data["watching"])
        response = self.client.get(reverse("api:watchlist"))
        self.assertEqual(response.data["count"], 1)

        self.assertFalse(self.client.post(url).data["watching"])
        self.assertFalse(Watchlist.objects.exists())


class SellerApiTests(ApiTestCase):
    def lot_data(self, **overrides):
        data = {
            "title": "Cedar chest",
            "category": self.category.pk,
            "description": "Federation-era cedar chest.",
            "starting_price": "100.00",
            "reserve_price": "250.00",
            "duration_days": 7,
        }
        data.update(overrides)
        return data

    def test_create_lot(self):
        self.login(self.seller)

        response = self.client.post(reverse("api:lots"), self.lot_data(),
                                    format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(response.data["seller"], "sam")
        self.assertTrue(
            AuditLog.objects.filter(action="LOT_CREATED").exists()
        )

    def test_create_lot_uses_form_validation(self):
        self.login(self.seller)

        response = self.client.post(
            reverse("api:lots"),
            self.lot_data(reserve_price="50.00"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reserve_price", response.data)

    def test_bidder_cannot_use_lot_endpoints(self):
        self.login(self.bidder)

        self.assertEqual(self.client.get(reverse("api:lots")).status_code,
                         403)

    def test_list_only_own_lots(self):
        other = User.objects.create_user(
            username="sue", password="x", role=User.Role.SELLER
        )
        self.make_lot(title="Mine")
        self.make_lot(title="Not mine", seller=other)
        self.login(self.seller)

        response = self.client.get(reverse("api:lots"))

        titles = [lot["title"] for lot in response.data["results"]]
        self.assertEqual(titles, ["Mine"])

    def test_patch_changes_only_sent_fields(self):
        lot = self.make_lot()
        self.login(self.seller)

        response = self.client.patch(
            reverse("api:lot_detail", args=[lot.pk]),
            {"title": "Oak mantel clock"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        lot.refresh_from_db()
        self.assertEqual(lot.title, "Oak mantel clock")
        self.assertEqual(lot.starting_price, Decimal("100.00"))

    def test_cannot_edit_approved_lot(self):
        lot = self.make_lot()
        services.approve_lot(self.moderator, lot)
        self.login(self.seller)

        response = self.client.patch(
            reverse("api:lot_detail", args=[lot.pk]),
            {"starting_price": "1.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        lot.refresh_from_db()
        self.assertEqual(lot.starting_price, Decimal("100.00"))


class ModerationApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.lot = self.make_lot()

    def test_queue_moderator_only(self):
        self.login(self.seller)
        url = reverse("api:moderation_queue")
        self.assertEqual(self.client.get(url).status_code, 403)

        self.login(self.moderator)
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 1)

    def test_approve(self):
        self.login(self.moderator)

        response = self.client.post(
            reverse("api:approve_lot", args=[self.lot.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ACTIVE")
        self.assertIsNone(response.data["current_price"])
        self.assertTrue(Auction.objects.filter(lot=self.lot).exists())

        # Approving again is refused by the service.
        response = self.client.post(
            reverse("api:approve_lot", args=[self.lot.pk])
        )
        self.assertEqual(response.status_code, 400)

    def test_reject_needs_reason(self):
        self.login(self.moderator)
        url = reverse("api:reject_lot", args=[self.lot.pk])

        self.assertEqual(
            self.client.post(url, {}, format="json").status_code, 400
        )
        response = self.client.post(url, {"reason": "Need photos"},
                                    format="json")
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(response.data["rejection_reason"], "Need photos")

    def test_moderator_patch_ignores_prices(self):
        self.login(self.moderator)

        response = self.client.patch(
            reverse("api:moderation_lot", args=[self.lot.pk]),
            {"category": self.other_category.pk, "starting_price": "1.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.category, self.other_category)
        self.assertEqual(self.lot.starting_price, Decimal("100.00"))
        self.assertEqual(response.data["description"],
                         "Working 1920s mantel clock.")


class ApiDocsTests(ApiTestCase):
    def test_schema_and_docs_pages(self):
        response = self.client.get(reverse("api:schema"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("api:docs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "swagger")
