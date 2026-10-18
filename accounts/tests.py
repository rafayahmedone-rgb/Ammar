from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views import View

from core.models import AuditLog

from .permissions import RoleRequiredMixin, role_required

User = get_user_model()


class UserModelTests(TestCase):
    def test_custom_user_model_is_used(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(User, get_user_model())

    def test_new_user_defaults_to_bidder(self):
        user = User.objects.create_user(username="alice", password="pass12345")

        self.assertEqual(user.role, User.Role.BIDDER)
        self.assertTrue(user.is_bidder)
        self.assertFalse(user.is_seller)

    def test_role_helpers(self):
        seller = User.objects.create_user(
            username="sam", password="pass12345", role=User.Role.SELLER
        )
        moderator = User.objects.create_user(
            username="mia", password="pass12345", role=User.Role.MODERATOR
        )
        admin = User.objects.create_user(
            username="ada", password="pass12345", role=User.Role.ADMIN
        )

        self.assertTrue(seller.is_seller)
        self.assertTrue(moderator.is_moderator)
        self.assertTrue(admin.is_admin_role)

    def test_str_shows_username_and_role(self):
        user = User(username="sam", role=User.Role.SELLER)

        self.assertEqual(str(user), "sam (Seller)")

    def test_superuser_gets_admin_role(self):
        user = User.objects.create_superuser(
            username="root", email="root@example.com", password="pass12345"
        )

        self.assertEqual(user.role, User.Role.ADMIN)


class RegistrationTests(TestCase):
    url = reverse("accounts:register")

    def form_data(self, **overrides):
        data = {
            "username": "sally",
            "email": "sally@example.com",
            "first_name": "Sally",
            "last_name": "Seller",
            "role": User.Role.SELLER,
            "password1": "Sup3r-secret-pw",
            "password2": "Sup3r-secret-pw",
        }
        data.update(overrides)
        return data

    def test_register_page_loads(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_register_creates_user_logs_in_and_audits(self):
        response = self.client.post(self.url, self.form_data())

        self.assertRedirects(response, reverse("core:home"))
        user = User.objects.get(username="sally")
        self.assertEqual(user.role, User.Role.SELLER)
        # The new user is logged in straight away.
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        log = AuditLog.objects.get(action="USER_REGISTERED")
        self.assertEqual(log.user, user)
        self.assertEqual(log.target_type, "User")
        self.assertEqual(log.target_id, user.pk)

    def test_cannot_register_as_moderator_or_admin(self):
        for role in (User.Role.MODERATOR, User.Role.ADMIN):
            response = self.client.post(self.url, self.form_data(role=role))

            self.assertEqual(response.status_code, 200)
            self.assertFalse(User.objects.filter(username="sally").exists())

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            username="other", email="SALLY@example.com", password="x"
        )

        response = self.client.post(self.url, self.form_data())

        self.assertContains(response, "An account with this email already")
        self.assertFalse(User.objects.filter(username="sally").exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bob", password="pass12345"
        )

    def test_login_and_logout(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bob", "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("core:home"))
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bob", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


# Two tiny views used only to test the permission helpers.
@role_required(User.Role.MODERATOR, User.Role.ADMIN)
def moderator_only_view(request):
    return HttpResponse("ok")


class SellerOnlyView(RoleRequiredMixin, View):
    allowed_roles = (User.Role.SELLER,)

    def get(self, request):
        return HttpResponse("ok")


class PermissionHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.seller = User.objects.create_user(
            username="sam", password="x", role=User.Role.SELLER
        )
        self.moderator = User.objects.create_user(
            username="mia", password="x", role=User.Role.MODERATOR
        )

    def make_request(self, user):
        request = self.factory.get("/protected/")
        request.user = user
        return request

    def test_decorator_redirects_anonymous_user_to_login(self):
        response = moderator_only_view(self.make_request(AnonymousUser()))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_decorator_blocks_wrong_role(self):
        with self.assertRaises(PermissionDenied):
            moderator_only_view(self.make_request(self.seller))

    def test_decorator_allows_right_role(self):
        response = moderator_only_view(self.make_request(self.moderator))

        self.assertEqual(response.status_code, 200)

    def test_mixin_redirects_anonymous_user_to_login(self):
        view = SellerOnlyView.as_view()
        response = view(self.make_request(AnonymousUser()))

        self.assertEqual(response.status_code, 302)

    def test_mixin_blocks_wrong_role(self):
        view = SellerOnlyView.as_view()

        with self.assertRaises(PermissionDenied):
            view(self.make_request(self.moderator))

    def test_mixin_allows_right_role(self):
        view = SellerOnlyView.as_view()
        response = view(self.make_request(self.seller))

        self.assertEqual(response.status_code, 200)


class UserAdminAuditTests(TestCase):
    def test_changing_a_role_in_admin_is_audit_logged(self):
        admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="pass12345"
        )
        user = User.objects.create_user(username="bob", password="x")
        self.client.force_login(admin)

        # The admin change form needs all of these fields to be posted.
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[user.pk]),
            {
                "username": "bob",
                "role": User.Role.MODERATOR,
                "is_active": "on",
                "date_joined_0": "2026-01-01",
                "date_joined_1": "10:00:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.MODERATOR)
        log = AuditLog.objects.get(action="USER_UPDATED")
        self.assertEqual(log.user, admin)
        self.assertIn("role", log.details)
