from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, PlatformConfig
from .services import log_action

User = get_user_model()


class HomePageTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "Southern Cross Auctions")


class LogActionTests(TestCase):
    def test_log_action_records_user_and_target(self):
        user = User.objects.create_user(username="bob", password="x")

        log = log_action(user, "TEST_ACTION", target=user, details="hello")

        self.assertEqual(log.user, user)
        self.assertEqual(log.action, "TEST_ACTION")
        self.assertEqual(log.target_type, "User")
        self.assertEqual(log.target_id, user.pk)
        self.assertEqual(log.details, "hello")

    def test_log_action_without_user_or_target(self):
        log = log_action(None, "SYSTEM_TASK")

        self.assertIsNone(log.user)
        self.assertEqual(log.target_type, "")
        self.assertIsNone(log.target_id)

    def test_anonymous_user_is_stored_as_none(self):
        log = log_action(AnonymousUser(), "VISIT")

        self.assertIsNone(log.user)


class PlatformConfigTests(TestCase):
    def test_load_creates_row_with_defaults(self):
        config = PlatformConfig.load()

        self.assertEqual(config.pk, 1)
        self.assertEqual(config.bid_increment_percent, Decimal("5"))
        self.assertEqual(config.commission_percent, Decimal("10"))
        self.assertEqual(config.max_extensions, 5)

    def test_only_one_row_can_exist(self):
        PlatformConfig.load()
        # Saving a "new" object overwrites row 1 instead of adding row 2.
        PlatformConfig(bid_increment_percent=Decimal("7.5")).save()

        self.assertEqual(PlatformConfig.objects.count(), 1)
        self.assertEqual(
            PlatformConfig.load().bid_increment_percent, Decimal("7.5")
        )


class AdminAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="pass12345"
        )
        self.client.force_login(self.admin)

    def test_editing_config_in_admin_is_audit_logged(self):
        config = PlatformConfig.load()

        response = self.client.post(
            reverse("admin:core_platformconfig_change", args=[config.pk]),
            {
                "bid_increment_percent": "6.00",
                "commission_percent": "10.00",
                "max_extensions": "5",
            },
        )

        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(action="CONFIG_UPDATED")
        self.assertEqual(log.user, self.admin)
        self.assertIn("bid_increment_percent=6.00", log.details)
        self.assertNotIn("commission_percent", log.details)

    def test_audit_log_cannot_be_edited_in_admin(self):
        log = log_action(self.admin, "TEST_ACTION")

        response = self.client.post(
            reverse("admin:core_auditlog_change", args=[log.pk]),
            {"action": "CHANGED"},
        )

        log.refresh_from_db()
        self.assertEqual(log.action, "TEST_ACTION")
        self.assertNotEqual(response.status_code, 302)
