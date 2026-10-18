from django.urls import path

from . import views

app_name = "auctions"

urlpatterns = [
    # Public
    path("", views.auction_list, name="auction_list"),
    path("lots/<int:pk>/", views.lot_detail, name="lot_detail"),
    # Bidding and watchlist
    path("<int:pk>/bid/", views.bid_place, name="bid_place"),
    path("<int:pk>/watch/", views.watch_toggle, name="watch_toggle"),
    path("<int:pk>/cancel/", views.auction_cancel, name="auction_cancel"),
    path("watchlist/", views.watchlist, name="watchlist"),
    path("my-bids/", views.my_bids, name="my_bids"),
    path("bids/<int:pk>/withdraw/", views.bid_withdraw, name="bid_withdraw"),
    # Sellers
    path("lots/mine/", views.my_lots, name="my_lots"),
    path("lots/new/", views.lot_create, name="lot_create"),
    path("lots/<int:pk>/edit/", views.lot_edit, name="lot_edit"),
    # Moderators
    path("moderation/", views.moderation_queue, name="moderation_queue"),
    path(
        "moderation/lots/<int:pk>/",
        views.moderation_review,
        name="moderation_review",
    ),
    path(
        "moderation/lots/<int:pk>/approve/",
        views.lot_approve,
        name="lot_approve",
    ),
    path(
        "moderation/lots/<int:pk>/reject/",
        views.lot_reject,
        name="lot_reject",
    ),
    path(
        "moderation/lots/<int:pk>/edit/",
        views.moderator_edit,
        name="moderator_edit",
    ),
]
