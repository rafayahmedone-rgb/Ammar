from django.contrib import admin

from core.services import log_action

from .models import Auction, Bid, Category, Lot, Watchlist


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log_action(
            request.user,
            "CATEGORY_UPDATED" if change else "CATEGORY_CREATED",
            target=obj,
            details=obj.name,
        )

    def delete_model(self, request, obj):
        # Log first, while the object still has its primary key.
        log_action(request.user, "CATEGORY_DELETED", target=obj,
                   details=obj.name)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        # Used by the "delete selected" action on the list page.
        for category in queryset:
            log_action(request.user, "CATEGORY_DELETED", target=category,
                       details=category.name)
        super().delete_queryset(request, queryset)


class ViewOnlyAdmin(admin.ModelAdmin):
    """
    Lots and auctions can be looked at here, but all changes go through
    the website so the business rules and audit log are always applied.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Lot)
class LotAdmin(ViewOnlyAdmin):
    list_display = ("title", "seller", "category", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "seller__username")


@admin.register(Auction)
class AuctionAdmin(ViewOnlyAdmin):
    list_display = ("lot", "status", "start_time", "end_time")
    list_filter = ("status",)


@admin.register(Bid)
class BidAdmin(ViewOnlyAdmin):
    list_display = ("auction", "bidder", "amount", "created_at",
                    "is_withdrawn")
    list_filter = ("is_withdrawn",)
    search_fields = ("bidder__username", "auction__lot__title")


@admin.register(Watchlist)
class WatchlistAdmin(ViewOnlyAdmin):
    list_display = ("user", "auction", "created_at")
