from django.urls import path

from . import views

# app_name lets templates refer to URLs as "core:home".
app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    # Disputes
    path("disputes/", views.dispute_list, name="dispute_list"),
    path("disputes/<int:pk>/", views.dispute_detail, name="dispute_detail"),
    path("disputes/<int:pk>/resolve/", views.dispute_resolve,
         name="dispute_resolve"),
    path("disputes/new/<int:payment_pk>/", views.dispute_create,
         name="dispute_create"),
    # Reports
    path("reports/", views.report_dashboard, name="reports"),
    path("reports/sales.csv", views.report_payments_csv,
         name="report_payments_csv"),
]
