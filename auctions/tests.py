from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, PlatformConfig

from . import services
from .forms import LotForm, ModeratorLotForm
from .models import Auction, Category, Lot, Watchlist

User = get_user_model()


class AuctionTestCase(TestCase):
    """Shared users, a category and a helper to make lots."""

    def setUp(self):
        self.seller = User.objects.create_user(
            username="sam", password="x", role=User.Role.SELLER
        )
        self.other_seller = User.objects.create_user(
            username="sue", password="x", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            username="bob", password="x", role=User.Role.BIDDER
        )
        self.moderator = User.objects.create_user(
            username="mia", password="x", role=User.Role.MODERATOR
        )
        self.admin = User.objects.create_user(
            username="ada", password="x", role=User.Role.ADMIN
        )
        self.furniture = Category.objects.create(name="Furniture")
        self.coins = Category.objects.create(name="Coins")

    def make_lot(self, **overrides):
        data = {
            "seller": self.seller,
            "category": self.furniture,
            "title": "Cedar chest",
            "description": "Federation-era cedar chest.",
            "starting_price": Decimal("100.00"),
            "reserve_price": Decimal("250.00"),
            "duration_days": 7,
        }
        data.update(overrides)
        return Lot.objects.create(**data)

    def lot_post_data(self, **overrides):
        data = {
            "title": "Cedar chest",
            "category": self.furniture.pk,
            "description": "Federation-era cedar chest.",
            "starting_price": "100.00",
            "reserve_price": "250.00",
            "duration_days": "7",
        }
        data.update(overrides)
        return data


class LotFormTests(AuctionTestCase):
    def test_reserve_below_starting_price_is_invalid(self):
        form = LotForm(self.lot_post_data(reserve_price="50.00"))

        self.assertFalse(form.is_valid())
        self.assertIn("reserve_price", form.errors)

    def test_reserve_is_optional(self):
        form = LotForm(self.lot_post_data(reserve_price=""))

        self.assertTrue(form.is_valid())

    def test_starting_price_must_be_positive(self):
        form = LotForm(self.lot_post_data(starting_price="0"))

        self.assertFalse(form.is_valid())

    def test_moderator_form_has_no_price_fields(self):
        self.assertEqual(
            list(ModeratorLotForm.base_fields), ["category", "description"]
        )


class SellerViewTests(AuctionTestCase):
    def test_seller_creates_pending_lot(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("auctions:lot_create"), self.lot_post_data()
        )

        self.assertRedirects(response, reverse("auctions:my_lots"))
        lot = Lot.objects.get()
        self.assertEqual(lot.seller, self.seller)
        self.assertEqual(lot.status, Lot.Status.PENDING)
        self.assertTrue(AuditLog.objects.filter(action="LOT_CREATED").exists())

    def test_bidder_cannot_create_lot(self):
        self.client.force_login(self.bidder)

        response = self.client.get(reverse("auctions:lot_create"))

        self.assertEqual(response.status_code, 403)

    def test_my_lots_shows_only_own_lots(self):
        self.make_lot(title="Mine")
        self.make_lot(title="Not mine", seller=self.other_seller)
        self.client.force_login(self.seller)

        response = self.client.get(reverse("auctions:my_lots"))

        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Not mine")

    def test_seller_edits_pending_lot(self):
        lot = self.make_lot()
        self.client.force_login(self.seller)

        self.client.post(
            reverse("auctions:lot_edit", args=[lot.pk]),
            self.lot_post_data(title="Cedar blanket box"),
        )

        lot.refresh_from_db()
        self.assertEqual(lot.title, "Cedar blanket box")
        log = AuditLog.objects.get(action="LOT_UPDATED")
        self.assertIn("title", log.details)

    def test_seller_cannot_edit_someone_elses_lot(self):
        lot = self.make_lot(seller=self.other_seller)
        self.client.force_login(self.seller)

        response = self.client.get(reverse("auctions:lot_edit", args=[lot.pk]))

        self.assertEqual(response.status_code, 404)

    def test_seller_cannot_edit_approved_lot(self):
        lot = self.make_lot()
        services.approve_lot(self.moderator, lot)
        self.client.force_login(self.seller)

        self.client.post(
            reverse("auctions:lot_edit", args=[lot.pk]),
            self.lot_post_data(starting_price="1.00"),
        )

        lot.refresh_from_db()
        self.assertEqual(lot.starting_price, Decimal("100.00"))

    def test_editing_rejected_lot_resubmits_it(self):
        lot = self.make_lot()
        services.reject_lot(self.moderator, lot, "Please add measurements.")
        self.client.force_login(self.seller)

        self.client.post(
            reverse("auctions:lot_edit", args=[lot.pk]),
            self.lot_post_data(description="Cedar chest, 90 x 45 x 50 cm."),
        )

        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.PENDING)
        self.assertEqual(lot.rejection_reason, "")


class SellerServiceTests(AuctionTestCase):
    def test_stale_edit_cannot_undo_an_approval(self):
        # The seller opens the edit form...
        lot = self.make_lot()
        form = LotForm(self.lot_post_data(title="New title"), instance=lot)
        self.assertTrue(form.is_valid())
        # ...a Moderator approves the lot before the seller saves...
        services.approve_lot(self.moderator, Lot.objects.get(pk=lot.pk))

        # ...so the seller's save is refused.
        with self.assertRaises(services.LotStateError):
            services.update_lot_by_seller(self.seller, lot, form)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.APPROVED)
        self.assertEqual(lot.title, "Cedar chest")


class ModerationTests(AuctionTestCase):
    def test_queue_lists_only_pending_lots(self):
        self.make_lot(title="Waiting")
        rejected = self.make_lot(title="Already rejected")
        services.reject_lot(self.moderator, rejected, "No")
        self.client.force_login(self.moderator)

        response = self.client.get(reverse("auctions:moderation_queue"))

        self.assertContains(response, "Waiting")
        self.assertNotContains(response, "Already rejected")

    def test_only_moderators_can_use_moderation_pages(self):
        lot = self.make_lot()
        urls = [
            reverse("auctions:moderation_queue"),
            reverse("auctions:moderation_review", args=[lot.pk]),
            reverse("auctions:moderator_edit", args=[lot.pk]),
        ]
        for user in (self.seller, self.bidder, self.admin):
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_seller_cannot_approve(self):
        lot = self.make_lot()
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("auctions:lot_approve", args=[lot.pk])
        )

        self.assertEqual(response.status_code, 403)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.PENDING)

    def test_approve_creates_auction(self):
        lot = self.make_lot(duration_days=3)
        self.client.force_login(self.moderator)
        before = timezone.now()

        response = self.client.post(
            reverse("auctions:lot_approve", args=[lot.pk])
        )

        self.assertRedirects(response, reverse("auctions:moderation_queue"))
        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.APPROVED)
        self.assertEqual(lot.reviewed_by, self.moderator)
        auction = Auction.objects.get(lot=lot)
        self.assertEqual(auction.status, Auction.Status.ACTIVE)
        self.assertEqual(
            auction.end_time - auction.start_time, timedelta(days=3)
        )
        self.assertGreaterEqual(auction.start_time, before)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"LOT_APPROVED", "AUCTION_CREATED"} <= actions)

    def test_cannot_approve_twice(self):
        lot = self.make_lot()
        services.approve_lot(self.moderator, lot)

        with self.assertRaises(services.LotStateError):
            services.approve_lot(self.moderator, lot)
        self.assertEqual(Auction.objects.count(), 1)

    def test_approve_must_be_post(self):
        lot = self.make_lot()
        self.client.force_login(self.moderator)

        response = self.client.get(
            reverse("auctions:lot_approve", args=[lot.pk])
        )

        self.assertEqual(response.status_code, 405)

    def test_reject_with_reason(self):
        lot = self.make_lot()
        self.client.force_login(self.moderator)

        self.client.post(
            reverse("auctions:lot_reject", args=[lot.pk]),
            {"reason": "Photos needed."},
        )

        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.REJECTED)
        self.assertEqual(lot.rejection_reason, "Photos needed.")
        self.assertFalse(Auction.objects.exists())
        log = AuditLog.objects.get(action="LOT_REJECTED")
        self.assertEqual(log.details, "Photos needed.")

    def test_reject_needs_a_reason(self):
        lot = self.make_lot()
        self.client.force_login(self.moderator)

        response = self.client.post(
            reverse("auctions:lot_reject", args=[lot.pk]), {"reason": ""}
        )

        self.assertEqual(response.status_code, 200)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Lot.Status.PENDING)

    def test_moderator_edits_category_and_description_only(self):
        lot = self.make_lot()
        self.client.force_login(self.moderator)

        # Prices are sent too, but the form ignores them.
        self.client.post(
            reverse("auctions:moderator_edit", args=[lot.pk]),
            {
                "category": self.coins.pk,
                "description": "Tidied description.",
                "starting_price": "1.00",
                "reserve_price": "1.00",
            },
        )

        lot.refresh_from_db()
        self.assertEqual(lot.category, self.coins)
        self.assertEqual(lot.description, "Tidied description.")
        self.assertEqual(lot.starting_price, Decimal("100.00"))
        self.assertEqual(lot.reserve_price, Decimal("250.00"))
        self.assertTrue(
            AuditLog.objects.filter(action="LOT_EDITED_BY_MODERATOR").exists()
        )


class PagesRenderTests(AuctionTestCase):
    """Every page opens without errors for a user who is allowed in."""

    def test_pages_render(self):
        lot = self.make_lot()
        pages = [
            (self.seller, reverse("auctions:lot_create")),
            (self.seller, reverse("auctions:lot_edit", args=[lot.pk])),
            (self.seller, reverse("auctions:my_lots")),
            (self.moderator, reverse("auctions:moderation_queue")),
            (
                self.moderator,
                reverse("auctions:moderation_review", args=[lot.pk]),
            ),
            (
                self.moderator,
                reverse("auctions:moderator_edit", args=[lot.pk]),
            ),
        ]
        for user, url in pages:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)


class PublicPageTests(AuctionTestCase):
    def test_auction_list_shows_only_active_auctions(self):
        live = self.make_lot(title="Live lot")
        services.approve_lot(self.moderator, live)
        self.make_lot(title="Pending lot")

        response = self.client.get(reverse("auctions:auction_list"))

        self.assertContains(response, "Live lot")
        self.assertNotContains(response, "Pending lot")
        # The reserve price is secret.
        self.assertNotContains(response, "250.00")

    def test_auction_list_filters_by_category(self):
        chest = self.make_lot(title="Cedar chest")
        coin = self.make_lot(title="Holey dollar", category=self.coins)
        services.approve_lot(self.moderator, chest)
        services.approve_lot(self.moderator, coin)

        response = self.client.get(
            reverse("auctions:auction_list"), {"category": self.coins.pk}
        )

        self.assertContains(response, "Holey dollar")
        self.assertNotContains(response, "Cedar chest")

    def test_pending_lot_is_hidden_from_public(self):
        lot = self.make_lot()
        url = reverse("auctions:lot_detail", args=[lot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other_seller)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_pending_lot_visible_to_owner_and_moderator(self):
        lot = self.make_lot()
        url = reverse("auctions:lot_detail", args=[lot.pk])

        for user in (self.seller, self.moderator, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_approved_lot_is_public(self):
        lot = self.make_lot()
        services.approve_lot(self.moderator, lot)

        response = self.client.get(
            reverse("auctions:lot_detail", args=[lot.pk])
        )

        self.assertContains(response, "Cedar chest")
        self.assertNotContains(response, "250.00")


class BiddingTestCase(AuctionTestCase):
    """Adds a second bidder and a live auction (starting price $100)."""

    def setUp(self):
        super().setUp()
        self.bidder2 = User.objects.create_user(
            username="bea", password="x", role=User.Role.BIDDER
        )
        self.lot = self.make_lot()
        self.auction = services.approve_lot(self.moderator, self.lot)

    def bid(self, user, amount):
        return services.place_bid(user, self.auction, Decimal(amount))


class MinimumBidTests(BiddingTestCase):
    def test_first_bid_minimum_is_starting_price(self):
        self.assertEqual(
            services.minimum_bid(self.auction), Decimal("100.00")
        )

    def test_later_minimum_adds_increment(self):
        self.bid(self.bidder, "100.00")

        # 100 x 1.05 = 105
        self.assertEqual(
            services.minimum_bid(self.auction), Decimal("105.00")
        )

    def test_minimum_rounds_up_to_cents(self):
        self.bid(self.bidder, "133.33")

        # 133.33 x 1.05 = 139.9965, rounded up to 140.00
        self.assertEqual(
            services.minimum_bid(self.auction), Decimal("140.00")
        )

    def test_increment_comes_from_platform_config(self):
        config = PlatformConfig.load()
        config.bid_increment_percent = Decimal("10")
        config.save()
        self.bid(self.bidder, "100.00")

        self.assertEqual(
            services.minimum_bid(self.auction), Decimal("110.00")
        )


class PlaceBidTests(BiddingTestCase):
    def test_first_bid_below_starting_price_is_refused(self):
        with self.assertRaises(services.BidError):
            self.bid(self.bidder, "99.99")

    def test_first_bid_at_starting_price_is_accepted(self):
        bid = self.bid(self.bidder, "100.00")

        self.assertEqual(self.auction.highest_bid(), bid)
        log = AuditLog.objects.get(action="BID_PLACED")
        self.assertEqual(log.user, self.bidder)

    def test_bid_below_increment_is_refused(self):
        self.bid(self.bidder, "100.00")

        with self.assertRaises(services.BidError):
            self.bid(self.bidder2, "104.99")
        self.bid(self.bidder2, "105.00")
        self.assertEqual(
            self.auction.highest_bid().amount, Decimal("105.00")
        )

    def test_seller_cannot_bid_on_own_lot(self):
        with self.assertRaises(services.BidError):
            self.bid(self.seller, "200.00")

    def test_seller_can_bid_on_another_sellers_lot(self):
        bid = self.bid(self.other_seller, "100.00")

        self.assertEqual(bid.bidder, self.other_seller)

    def test_moderator_and_admin_cannot_bid(self):
        for user in (self.moderator, self.admin):
            with self.assertRaises(services.BidError):
                self.bid(user, "100.00")

    def test_cannot_bid_after_end_time(self):
        self.auction.end_time = timezone.now() - timedelta(seconds=1)
        self.auction.save()

        with self.assertRaises(services.BidError):
            self.bid(self.bidder, "100.00")

    def test_cannot_bid_on_closed_auction(self):
        self.auction.status = Auction.Status.CANCELLED
        self.auction.save()

        with self.assertRaises(services.BidError):
            self.bid(self.bidder, "100.00")


class AntiSnipingTests(BiddingTestCase):
    def set_time_left(self, delta):
        self.auction.end_time = timezone.now() + delta
        self.auction.save()
        return self.auction.end_time

    def test_bid_in_last_two_minutes_extends_auction(self):
        old_end = self.set_time_left(timedelta(seconds=90))

        self.bid(self.bidder, "100.00")

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.end_time, old_end + timedelta(minutes=2))
        self.assertEqual(self.auction.extension_count, 1)
        self.assertTrue(
            AuditLog.objects.filter(action="AUCTION_EXTENDED").exists()
        )

    def test_earlier_bid_does_not_extend(self):
        old_end = self.set_time_left(timedelta(minutes=10))

        self.bid(self.bidder, "100.00")

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.end_time, old_end)
        self.assertEqual(self.auction.extension_count, 0)

    def test_extensions_stop_at_configured_maximum(self):
        config = PlatformConfig.load()
        config.max_extensions = 2
        config.save()
        self.set_time_left(timedelta(seconds=30))

        # Each bid lands in the last 2 minutes, so would extend if allowed.
        for amount in ("100.00", "105.00", "111.00"):
            self.auction.end_time = timezone.now() + timedelta(seconds=30)
            self.auction.save()
            self.bid(self.bidder, amount)
            self.auction.refresh_from_db()

        self.assertEqual(self.auction.extension_count, 2)


class WithdrawBidTests(BiddingTestCase):
    def test_moderator_withdraws_bid_and_next_bid_leads(self):
        first = self.bid(self.bidder, "100.00")
        second = self.bid(self.bidder2, "105.00")
        self.client.force_login(self.moderator)

        self.client.post(
            reverse("auctions:bid_withdraw", args=[second.pk]),
            {"reason": "Bidder asked, typing error."},
        )

        second.refresh_from_db()
        self.assertTrue(second.is_withdrawn)
        self.assertEqual(second.withdrawn_by, self.moderator)
        self.assertEqual(self.auction.highest_bid(), first)
        # The minimum is now based on the remaining $100 bid.
        self.assertEqual(
            services.minimum_bid(self.auction), Decimal("105.00")
        )
        log = AuditLog.objects.get(action="BID_WITHDRAWN")
        self.assertIn("typing error", log.details)

    def test_bidder_cannot_withdraw_bid(self):
        bid = self.bid(self.bidder, "100.00")
        self.client.force_login(self.bidder)

        response = self.client.post(
            reverse("auctions:bid_withdraw", args=[bid.pk]),
            {"reason": "Changed my mind"},
        )

        self.assertEqual(response.status_code, 403)
        bid.refresh_from_db()
        self.assertFalse(bid.is_withdrawn)

    def test_withdraw_needs_a_reason(self):
        bid = self.bid(self.bidder, "100.00")
        self.client.force_login(self.moderator)

        self.client.post(
            reverse("auctions:bid_withdraw", args=[bid.pk]), {"reason": ""}
        )

        bid.refresh_from_db()
        self.assertFalse(bid.is_withdrawn)

    def test_cannot_withdraw_twice(self):
        bid = self.bid(self.bidder, "100.00")
        services.withdraw_bid(self.moderator, bid, "First")

        with self.assertRaises(services.BidError):
            services.withdraw_bid(self.moderator, bid, "Second")


class BidViewTests(BiddingTestCase):
    def detail_url(self):
        return reverse("auctions:lot_detail", args=[self.lot.pk])

    def test_bid_through_the_page(self):
        self.client.force_login(self.bidder)

        response = self.client.post(
            reverse("auctions:bid_place", args=[self.auction.pk]),
            {"amount": "120.00"},
        )

        self.assertRedirects(response, self.detail_url())
        self.assertEqual(
            self.auction.highest_bid().amount, Decimal("120.00")
        )

    def test_low_bid_shows_error_message(self):
        self.client.force_login(self.bidder)

        response = self.client.post(
            reverse("auctions:bid_place", args=[self.auction.pk]),
            {"amount": "50.00"},
            follow=True,
        )

        self.assertContains(response, "Your bid must be at least $100.00")
        self.assertIsNone(self.auction.highest_bid())

    def test_anonymous_user_must_log_in_to_bid(self):
        response = self.client.post(
            reverse("auctions:bid_place", args=[self.auction.pk]),
            {"amount": "120.00"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertIsNone(self.auction.highest_bid())

    def test_withdrawn_bids_hidden_from_public(self):
        bid = self.bid(self.bidder, "123.45")
        services.withdraw_bid(self.moderator, bid, "Shill bidding")

        response = self.client.get(self.detail_url())
        self.assertNotContains(response, "123.45")

        self.client.force_login(self.moderator)
        response = self.client.get(self.detail_url())
        self.assertContains(response, "123.45")
        self.assertContains(response, "Shill bidding")

    def test_seller_sees_no_bid_form_on_own_lot(self):
        self.client.force_login(self.seller)

        response = self.client.get(self.detail_url())

        self.assertNotContains(response, "Place bid")

    def test_lists_show_current_price(self):
        self.bid(self.bidder, "150.00")
        self.bid(self.bidder2, "200.00")

        response = self.client.get(reverse("auctions:auction_list"))
        self.assertContains(response, "$200.00")

        # My bids: bob's best is 150, but the current price is 200.
        self.client.force_login(self.bidder)
        response = self.client.get(reverse("auctions:my_bids"))
        self.assertContains(response, "$150.00")
        self.assertContains(response, "$200.00")
        self.assertContains(response, "Outbid")


class WatchlistTests(BiddingTestCase):
    def test_toggle_adds_then_removes(self):
        self.client.force_login(self.bidder)
        url = reverse("auctions:watch_toggle", args=[self.auction.pk])

        self.client.post(url)
        self.assertTrue(
            Watchlist.objects.filter(
                user=self.bidder, auction=self.auction
            ).exists()
        )
        response = self.client.get(reverse("auctions:watchlist"))
        self.assertContains(response, "Cedar chest")

        self.client.post(url)
        self.assertFalse(Watchlist.objects.exists())

        actions = list(
            AuditLog.objects.filter(action__startswith="WATCHLIST")
            .order_by("created_at")
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, ["WATCHLIST_ADDED", "WATCHLIST_REMOVED"])

    def test_watchlist_requires_login(self):
        response = self.client.get(reverse("auctions:watchlist"))

        self.assertEqual(response.status_code, 302)
