from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import LoginForm, RegistrationForm
from .services import register_user


def register(request):
    """Show the sign-up form and create the account when it is valid."""
    if request.user.is_authenticated:
        return redirect("core:home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = register_user(form)
            # Log the new user straight in so they do not have to retype.
            login(request, user)
            messages.success(request, f"Welcome, {user.username}!")
            return redirect("core:home")
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    # Already logged-in users are sent to LOGIN_REDIRECT_URL.
    redirect_authenticated_user = True
