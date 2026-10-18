from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auctions import services as auction_services
from auctions.models import Auction, Category, Lot
from auctions.tasks import close_ended_auctions_task
from core.models import AuditLog, PlatformConfig

from . import services
from .models import Payment
from .tasks import expire_overdue_payments_task

User = get_user_model()


class CalculateAmountsTests(TestCase):
    def test_breakdown_for_200_dollars_at_10_percent(self):
        amounts = services.calculate_amounts(Decimal("200.00"), Decimal("10"))

        self.assertEqual(amounts["gst_amount"], Decimal("20.00"))
        self.assertEqual(amounts["total_amount"], Decimal("220.00"))
        self.assertEqual(amounts["commission_amount"], Decimal("20.00"))
        self.assertEqual(amounts["seller_payout"], Decimal("180.00"))

    def test_rounds_to_nearest_cent(self):
        amounts = services.calculate_amounts(Decimal("123.45"), Decimal("7.5"))

        # GST 12.345 -> 12.35, commission 9.25875 -> 9.26
        self.assertEqual(amounts["gst_amount"], Decimal("12.35"))
        self.assertEqual(amounts["total_amount"], Decimal("135.80"))
        self.assertEqual(amounts["commission_amount"], Decimal("9.26"))
        self.assertEqual(amounts["seller_payout"], Decimal("114.19"))


class SaleTestCase(TestCase):
    """A live auction: starting price $100, reserve $150."""

    def setUp(self):
        self.seller = User.objects.create_user(
            username="sam", password="x", role=User.Role.SELLER
        )
        self.bidder = User.objects.create_user(
            username="bob", password="x", role=User.Role.BIDDER
        )
        self.bidder2 = User.objects.create_user(
            username="bea", password="x", role=User.Role.BIDDER
        )
        self.moderator = User.objects.create_user(
            username="mia", password="x", role=User.Role.MODERATOR
        )
        self.lot = Lot.objects.create(
            seller=self.seller,
            category=Category.objects.create(name="Clocks"),
            title="Mantel clock",
            description="Working 1920s mantel clock.",
            starting_price=Decimal("100.00"),
            reserve_price=Decimal("150.00"),
        )
        self.auction = auction_services.approve_lot(self.moderator, self.lot)

    def bid(self, user, amount):
        return auction_services.place_bid(user, self.auction, Decimal(amount))

    def end_auction(self):
        """Move the end time into the past so it is ready to close."""
        Auction.objects.filter(pk=self.auction.pk).update(
            end_time=timezone.now() - timedelta(seconds=1)
        )

    def close(self):
        self.end_auction()
        closed = auction_services.close_ended_auctions()
        self.auction.refresh_from_db()
        return closed


class CloseAuctionTests(SaleTestCase):
    def test_active_auction_is_not_closed_early(self):
        self.bid(self.bidder, "200.00")

        self.assertEqual(auction_services.close_ended_auctions(), 0)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.ACTIVE)

    def test_reserve_met_is_sold_and_creates_payment(self):
        self.bid(self.bidder, "120.00")
        self.bid(self.bidder2, "200.00")

        self.assertEqual(self.close(), 1)

        self.assertEqual(self.auction.status, Auction.Status.SOLD)
        payment = Payment.objects.get(auction=self.auction)
        self.assertEqual(payment.buyer, self.bidder2)
        self.assertEqual(payment.hammer_price, Decimal("200.00"))
        self.assertEqual(payment.total_amount, Decimal("220.00"))
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertAlmostEqual(
            payment.due_at,
            timezone.now() + timedelta(hours=48),
            delta=timedelta(minutes=1),
        )
        log = AuditLog.objects.get(action="AUCTION_CLOSED")
        self.assertIn("Sold to bea", log.details)
        self.assertTrue(
            AuditLog.objects.filter(action="PAYMENT_CREATED").exists()
        )

    def test_bid_equal_to_reserve_is_sold(self):
        self.bid(self.bidder, "150.00")

        self.close()

        self.assertEqual(self.auction.status, Auction.Status.SOLD)

    def test_reserve_not_met_is_not_sold(self):
        self.bid(self.bidder, "149.99")

        self.close()

        self.assertEqual(self.auction.status, Auction.Status.NOT_SOLD)
        self.assertFalse(Payment.objects.exists())
        log = AuditLog.objects.get(action="AUCTION_CLOSED")
        self.assertIn("Reserve not met", log.details)

    def test_no_bids_is_not_sold(self):
        self.close()

        self.assertEqual(self.auction.status, Auction.Status.NOT_SOLD)
        self.assertFalse(Payment.objects.exists())

    def test_no_reserve_any_bid_sells(self):
        Lot.objects.filter(pk=self.lot.pk).update(reserve_price=None)
        self.bid(self.bidder, "100.00")

        self.close()

        self.assertEqual(self.auction.status, Auction.Status.SOLD)

    def test_withdrawn_top_bid_does_not_win(self):
        self.bid(self.bidder, "160.00")
        top = self.bid(self.bidder2, "300.00")
        auction_services.withdraw_bid(self.moderator, top, "Shill bid")

        self.close()

        payment = Payment.objects.get()
        self.assertEqual(payment.buyer, self.bidder)
        self.assertEqual(payment.hammer_price, Decimal("160.00"))

    def test_closing_twice_does_nothing_the_second_time(self):
        self.bid(self.bidder, "200.00")
        self.close()

        self.assertEqual(auction_services.close_ended_auctions(), 0)
        self.assertFalse(
            auction_services.close_auction(self.auction)
        )
        self.assertEqual(Payment.objects.count(), 1)

    def test_commission_uses_platform_config(self):
        config = PlatformConfig.load()
        config.commission_percent = Decimal("15")
        config.save()
        self.bid(self.bidder, "200.00")

        self.close()

        payment = Payment.objects.get()
        self.assertEqual(payment.commission_percent, Decimal("15"))
        self.assertEqual(payment.commission_amount, Decimal("30.00"))
        self.assertEqual(payment.seller_payout, Decimal("170.00"))

    def test_no_bids_after_close(self):
        self.close()
        # Even if the end time is moved forward again, a closed auction
        # takes no bids.
        Auction.objects.filter(pk=self.auction.pk).update(
            end_time=timezone.now() + timedelta(hours=1)
        )

        with self.assertRaises(auction_services.BidError):
            self.bid(self.bidder, "200.00")


class PayTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.bid(self.bidder, "200.00")
        self.close()
        self.payment = Payment.objects.get()
        self.url = reverse("payments:pay_now", args=[self.payment.pk])

    def test_buyer_pays(self):
        self.client.force_login(self.bidder)

        response = self.client.post(self.url, follow=True)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertIsNotNone(self.payment.paid_at)
        self.assertTrue(self.payment.reference.startswith("MOCK-"))
        self.assertContains(response, self.payment.reference)
        self.assertTrue(
            AuditLog.objects.filter(action="PAYMENT_PAID").exists()
        )

    def test_only_buyer_can_pay(self):
        for user in (self.seller, self.bidder2):
            with self.assertRaises(services.PaymentError):
                services.pay(user, self.payment)

    def test_cannot_pay_twice(self):
        services.pay(self.bidder, self.payment)

        with self.assertRaises(services.PaymentError):
            services.pay(self.bidder, self.payment)

    def test_cannot_pay_after_due_time(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            due_at=timezone.now() - timedelta(seconds=1)
        )

        with self.assertRaises(services.PaymentError):
            services.pay(self.bidder, self.payment)

    def test_pay_must_be_post(self):
        self.client.force_login(self.bidder)

        self.assertEqual(self.client.get(self.url).status_code, 405)


class ExpiryTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.bid(self.bidder, "200.00")
        self.close()
        self.payment = Payment.objects.get()

    def make_overdue(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            due_at=timezone.now() - timedelta(seconds=1)
        )

    def test_payment_not_expired_before_48_hours(self):
        self.assertEqual(services.expire_overdue_payments(), 0)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_overdue_payment_expires_and_sale_becomes_not_sold(self):
        self.make_overdue()

        self.assertEqual(services.expire_overdue_payments(), 1)

        self.payment.refresh_from_db()
        self.auction.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.EXPIRED)
        self.assertEqual(self.auction.status, Auction.Status.NOT_SOLD)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"PAYMENT_EXPIRED", "AUCTION_NOT_SOLD"} <= actions)

    def test_paid_payment_never_expires(self):
        services.pay(self.bidder, self.payment)
        self.make_overdue()

        self.assertEqual(services.expire_overdue_payments(), 0)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.SOLD)


class TaskTests(SaleTestCase):
    """The Celery tasks and the management command call the services."""

    def test_close_task(self):
        self.bid(self.bidder, "200.00")
        self.end_auction()

        # CELERY_TASK_ALWAYS_EAGER is on in tests, so this runs right away.
        result = close_ended_auctions_task.delay()

        self.assertEqual(result.get(), 1)
        self.assertTrue(Payment.objects.exists())

    def test_expire_task(self):
        self.bid(self.bidder, "200.00")
        self.close()
        Payment.objects.update(due_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(expire_overdue_payments_task.delay().get(), 1)

    def test_beat_schedule_lists_both_tasks(self):
        tasks = {
            entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()
        }

        self.assertEqual(
            tasks,
            {
                "auctions.tasks.close_ended_auctions_task",
                "payments.tasks.expire_overdue_payments_task",
                "payments.tasks.send_payment_reminders_task",
            },
        )

    def test_management_command(self):
        self.end_auction()
        out = StringIO()

        call_command("run_periodic_tasks", stdout=out)

        self.assertIn(
            "Closed 1 auction(s), sent 0 reminder(s), expired 0 payment(s).",
            out.getvalue(),
        )


class PaymentPageTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username="ada", password="x", role=User.Role.ADMIN
        )
        self.bid(self.bidder, "200.00")
        self.close()
        self.payment = Payment.objects.get()
        self.url = reverse("payments:payment_detail", args=[self.payment.pk])

    def test_buyer_sees_gst_breakdown_and_pay_button(self):
        self.client.force_login(self.bidder)

        response = self.client.get(self.url)

        self.assertContains(response, "GST (10%)")
        self.assertContains(response, "$220.00")
        self.assertContains(response, "Pay now")
        self.assertNotContains(response, "Payout")

    def test_seller_sees_commission_and_payout(self):
        self.client.force_login(self.seller)

        response = self.client.get(self.url)

        self.assertContains(response, "Platform commission (10.00%)")
        self.assertContains(response, "$180.00")
        self.assertNotContains(response, "Pay now")

    def test_admin_can_view_but_others_cannot(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

        self.client.force_login(self.bidder2)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_my_purchases_lists_won_items(self):
        self.client.force_login(self.bidder)

        response = self.client.get(reverse("payments:my_purchases"))

        self.assertContains(response, "Mantel clock")
        self.assertContains(response, "$220.00")

    def test_lot_page_and_my_lots_show_result(self):
        self.client.force_login(self.bidder)
        response = self.client.get(
            reverse("auctions:lot_detail", args=[self.lot.pk])
        )
        self.assertContains(response, "Sold")
        self.assertContains(response, self.url)

        self.client.force_login(self.seller)
        response = self.client.get(reverse("auctions:my_lots"))
        self.assertContains(response, "Awaiting payment")
