from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.my_purchases, name="my_purchases"),
    path("<int:pk>/", views.payment_detail, name="payment_detail"),
    path("<int:pk>/pay/", views.pay_now, name="pay_now"),
]
