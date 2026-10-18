from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.UserLoginView.as_view(), name="login"),
    # Django 5 only allows logout by POST (a form button), not a link.
    path("logout/", LogoutView.as_view(), name="logout"),
]
