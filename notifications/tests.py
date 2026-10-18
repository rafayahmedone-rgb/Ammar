from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auctions import services as auction_services
from auctions.models import Auction, Category, Lot
from payments import services as payment_services
from payments.models import Payment

from .models import Notification
from .services import notify

User = get_user_model()


class NotifyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bob", email="bob@example.com", password="x"
        )

    def test_notify_saves_and_emails_after_commit(self):
        # captureOnCommitCallbacks runs the on_commit() callbacks that a
        # TestCase would otherwise never run.
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.user, "Hello", "Test message")

        notification = Notification.objects.get()
        self.assertEqual(notification.subject, "Hello")
        self.assertIsNotNone(notification.emailed_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].subject, "[Southern Cross Auctions] Hello"
        )
        self.assertEqual(mail.outbox[0].to, ["bob@example.com"])

    def test_no_email_without_commit(self):
        # Without running the on_commit callbacks, nothing is emailed.
        notify(self.user, "Hello", "Test message")

        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_user_without_email_gets_notification_only(self):
        user = User.objects.create_user(username="noemail", password="x")

        with self.captureOnCommitCallbacks(execute=True):
            notify(user, "Hello", "Test message")

        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)


class NotificationTestCase(TestCase):
    """Shared users, a lot and helpers. Contains no tests itself."""

    def setUp(self):
        def make_user(name, role):
            return User.objects.create_user(
                username=name,
                email=f"{name}@example.com",
                password="x",
                role=role,
            )

        self.seller = make_user("sam", User.Role.SELLER)
        self.bidder = make_user("bob", User.Role.BIDDER)
        self.bidder2 = make_user("bea", User.Role.BIDDER)
        self.moderator = make_user("mia", User.Role.MODERATOR)
        self.lot = Lot.objects.create(
            seller=self.seller,
            category=Category.objects.create(name="Clocks"),
            title="Mantel clock",
            description="Working 1920s mantel clock.",
            starting_price=Decimal("100.00"),
            reserve_price=Decimal("150.00"),
        )

    def subjects_for(self, user):
        return list(
            Notification.objects.filter(user=user)
            .order_by("created_at")
            .values_list("subject", flat=True)
        )

    def approve(self):
        self.auction = auction_services.approve_lot(self.moderator, self.lot)

    def bid(self, user, amount):
        return auction_services.place_bid(user, self.auction, Decimal(amount))

    def close(self):
        Auction.objects.filter(pk=self.auction.pk).update(
            end_time=timezone.now() - timedelta(seconds=1)
        )
        auction_services.close_ended_auctions()


class NotificationEventTests(NotificationTestCase):
    """Each business event sends the right people the right message."""

    def test_lot_approved(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.approve()

        self.assertEqual(
            self.subjects_for(self.seller), ['Your lot "Mantel clock" is live']
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/auctions/lots/", mail.outbox[0].body)

    def test_lot_rejected_includes_reason(self):
        auction_services.reject_lot(self.moderator, self.lot, "Blurry photo")

        notification = Notification.objects.get(user=self.seller)
        self.assertIn("not approved", notification.subject)
        self.assertIn("Blurry photo", notification.message)

    def test_outbid_notifies_previous_leader_only(self):
        self.approve()
        self.bid(self.bidder, "100.00")
        self.bid(self.bidder2, "110.00")

        self.assertEqual(
            self.subjects_for(self.bidder),
            ['You have been outbid on "Mantel clock"'],
        )
        self.assertEqual(self.subjects_for(self.bidder2), [])

    def test_raising_own_bid_sends_no_outbid(self):
        self.approve()
        self.bid(self.bidder, "100.00")
        self.bid(self.bidder, "110.00")

        self.assertEqual(self.subjects_for(self.bidder), [])

    def test_failed_bid_sends_nothing(self):
        self.approve()
        self.bid(self.bidder, "100.00")

        with self.assertRaises(auction_services.BidError):
            self.bid(self.bidder2, "101.00")

        self.assertEqual(self.subjects_for(self.bidder), [])

    def test_sold_notifies_buyer_and_seller(self):
        self.approve()
        self.bid(self.bidder, "200.00")
        self.close()

        won = Notification.objects.get(user=self.bidder)
        self.assertEqual(won.subject, 'You won "Mantel clock"')
        self.assertIn("$220.00", won.message)
        self.assertIn('"Mantel clock" sold for $200.00',
                      self.subjects_for(self.seller))

    def test_not_sold_notifies_seller(self):
        self.approve()
        self.bid(self.bidder, "120.00")
        self.close()

        # Default ordering is newest first, so first() is the latest.
        notification = Notification.objects.filter(user=self.seller).first()
        self.assertEqual(notification.subject, '"Mantel clock" did not sell')
        self.assertIn("Reserve not met", notification.message)

    def test_payment_received(self):
        self.approve()
        self.bid(self.bidder, "200.00")
        self.close()
        payment = Payment.objects.get()

        payment_services.pay(self.bidder, payment)

        self.assertIn('Receipt for "Mantel clock"',
                      self.subjects_for(self.bidder))
        self.assertIn('The buyer has paid for "Mantel clock"',
                      self.subjects_for(self.seller))

    def test_payment_expired(self):
        self.approve()
        self.bid(self.bidder, "200.00")
        self.close()
        Payment.objects.update(due_at=timezone.now() - timedelta(seconds=1))

        payment_services.expire_overdue_payments()

        cancelled = 'Sale cancelled: "Mantel clock"'
        self.assertIn(cancelled, self.subjects_for(self.bidder))
        self.assertIn(cancelled, self.subjects_for(self.seller))


class PaymentReminderTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.approve()
        self.bid(self.bidder, "200.00")
        self.close()
        self.payment = Payment.objects.get()

    def set_time_left(self, delta):
        Payment.objects.update(due_at=timezone.now() + delta)

    def reminders(self):
        return Notification.objects.filter(subject__startswith="Reminder")

    def test_no_reminder_with_more_than_24_hours_left(self):
        self.set_time_left(timedelta(hours=30))

        self.assertEqual(payment_services.send_payment_reminders(), 0)
        self.assertFalse(self.reminders().exists())

    def test_reminder_sent_once_with_24_hours_left(self):
        self.set_time_left(timedelta(hours=23))

        self.assertEqual(payment_services.send_payment_reminders(), 1)
        self.assertEqual(payment_services.send_payment_reminders(), 0)

        reminder = self.reminders().get()
        self.assertEqual(reminder.user, self.bidder)
        self.payment.refresh_from_db()
        self.assertIsNotNone(self.payment.reminder_sent_at)

    def test_no_reminder_once_paid(self):
        payment_services.pay(self.bidder, self.payment)
        self.set_time_left(timedelta(hours=1))

        self.assertEqual(payment_services.send_payment_reminders(), 0)


class NotificationPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="x")
        self.client.force_login(self.user)

    def test_page_lists_and_marks_read(self):
        notify(self.user, "First", "See http://example.com/lot/1/")

        # The navbar badge shows 1 unread notification.
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["unread_notification_count"], 1)

        response = self.client.get(
            reverse("notifications:notification_list")
        )
        self.assertContains(response, "First")
        self.assertContains(response, "New")
        # urlize made the link clickable.
        self.assertContains(response, '<a href="http://example.com/lot/1/"')
        self.assertFalse(
            Notification.objects.filter(is_read=False).exists()
        )

    def test_users_only_see_their_own(self):
        other = User.objects.create_user(username="eve", password="x")
        notify(other, "Secret", "Not for bob")

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertNotContains(response, "Secret")
