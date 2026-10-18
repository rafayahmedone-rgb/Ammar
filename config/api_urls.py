"""
All REST API routes, mounted under /api/ in config/urls.py.

Authentication: POST username + password to /api/auth/token/ to get a
token, then send it on every request as the header
    Authorization: Token <your token>
Interactive docs: /api/docs/
"""

from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token

from accounts.api_views import MeView
from auctions import api_views as auctions
from notifications.api_views import MarkAllReadView, NotificationListView
from payments import api_views as payments

app_name = "api"

urlpatterns = [
    # Authentication
    path("auth/token/", obtain_auth_token, name="token"),
    path("me/", MeView.as_view(), name="me"),
    # Browsing and bidding
    path("categories/", auctions.CategoryListView.as_view(),
         name="categories"),
    path("auctions/", auctions.AuctionListView.as_view(), name="auctions"),
    path("auctions/<int:pk>/", auctions.AuctionDetailView.as_view(),
         name="auction_detail"),
    path("auctions/<int:pk>/bids/", auctions.PlaceBidView.as_view(),
         name="place_bid"),
    path("auctions/<int:pk>/watch/", auctions.WatchToggleView.as_view(),
         name="watch_toggle"),
    path("auctions/<int:pk>/cancel/", auctions.CancelAuctionView.as_view(),
         name="cancel_auction"),
    path("watchlist/", auctions.WatchlistView.as_view(), name="watchlist"),
    # Sellers
    path("lots/", auctions.SellerLotListView.as_view(), name="lots"),
    path("lots/<int:pk>/", auctions.SellerLotDetailView.as_view(),
         name="lot_detail"),
    # Moderators
    path("moderation/lots/", auctions.ModerationQueueView.as_view(),
         name="moderation_queue"),
    path("moderation/lots/<int:pk>/", auctions.ModerationLotView.as_view(),
         name="moderation_lot"),
    path("moderation/lots/<int:pk>/approve/",
         auctions.ApproveLotView.as_view(), name="approve_lot"),
    path("moderation/lots/<int:pk>/reject/",
         auctions.RejectLotView.as_view(), name="reject_lot"),
    path("bids/<int:pk>/withdraw/", auctions.WithdrawBidView.as_view(),
         name="withdraw_bid"),
    # Payments
    path("payments/", payments.MyPurchasesView.as_view(), name="payments"),
    path("payments/<int:pk>/", payments.PaymentDetailView.as_view(),
         name="payment_detail"),
    path("payments/<int:pk>/pay/", payments.PayNowView.as_view(),
         name="pay_now"),
    # Notifications
    path("notifications/", NotificationListView.as_view(),
         name="notifications"),
    path("notifications/mark-read/", MarkAllReadView.as_view(),
         name="notifications_mark_read"),
    # API docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"),
         name="docs"),
]
