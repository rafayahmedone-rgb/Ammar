from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

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
