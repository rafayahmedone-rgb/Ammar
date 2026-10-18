from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from core.forms import BootstrapFormMixin

from .models import User


class RegistrationForm(BootstrapFormMixin, UserCreationForm):
    """Sign-up form. People may only register as a Seller or a Bidder."""

    # Moderators and Admins are created by an Admin, never by sign-up.
    SELF_SERVICE_ROLES = [
        (User.Role.BIDDER, "Bidder - I want to buy"),
        (User.Role.SELLER, "Seller - I want to sell"),
    ]

    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=SELF_SERVICE_ROLES, label="I am a")

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role")

    def clean_email(self):
        """Make sure no other account already uses this email address."""
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )
        return email


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Django's normal login form, styled with Bootstrap."""
