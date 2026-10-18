from django.urls import path

from . import views

# app_name lets templates refer to URLs as "core:home".
app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
]
