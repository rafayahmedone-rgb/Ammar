from django.contrib import admin

from auctions.admin import ViewOnlyAdmin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(ViewOnlyAdmin):
    list_display = ("auction", "buyer", "total_amount", "status", "due_at",
                    "paid_at")
    list_filter = ("status",)
    search_fields = ("buyer__username", "auction__lot__title", "reference")
