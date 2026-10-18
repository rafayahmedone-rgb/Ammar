"""
REST API views for categories, auctions, bids, lots and moderation.

Each view follows the same three steps as the website views:
  1. check permissions,
  2. validate the input with the SAME Django form the website uses,
  3. call the SAME service function (which applies the business rules and
     writes the audit log).
Errors from a service come back as HTTP 400 with {"detail": "..."}.
"""

from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CanBid, IsModerator, IsSeller

from . import services
from .forms import (
    BidForm,
    LotForm,
    ModeratorLotForm,
    RejectLotForm,
    WithdrawBidForm,
)
from .models import Auction, Bid, Category, Lot
from .serializers import (
    AuctionDetailSerializer,
    AuctionSerializer,
    BidInputSerializer,
    BidSerializer,
    CategorySerializer,
    LotSerializer,
    ModeratorLotInputSerializer,
    ReasonInputSerializer,
    WatchResultSerializer,
)
from .views import CURRENT_PRICE


def error(message):
    """A 400 Bad Request response with a single error message."""
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def merge_with_current_values(form_class, instance, data):
    """
    For PATCH requests, which may send only some fields.

    Django forms expect every field, so start from the lot's current
    values and overwrite them with whatever the client sent.
    """
    merged = model_to_dict(instance, fields=form_class.Meta.fields)
    merged.update(data.items())
    return merged


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


class CategoryListView(generics.ListAPIView):
    """All categories."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    pagination_class = None


@extend_schema(
    parameters=[
        OpenApiParameter("category", int, description="Category id"),
    ]
)
class AuctionListView(generics.ListAPIView):
    """Auctions that are open for bidding."""

    serializer_class = AuctionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        auctions = (
            Auction.objects.filter(
                status=Auction.Status.ACTIVE,
                end_time__gt=timezone.now(),
            )
            .select_related("lot__category", "lot__seller")
            .annotate(current_price=CURRENT_PRICE)
            .order_by("end_time")
        )
        category_id = self.request.query_params.get("category")
        if category_id and category_id.isdigit():
            auctions = auctions.filter(lot__category_id=category_id)
        return auctions


class AuctionDetailView(generics.RetrieveAPIView):
    """One auction with its minimum next bid and bid history."""

    serializer_class = AuctionDetailSerializer
    permission_classes = [AllowAny]
    queryset = Auction.objects.select_related(
        "lot__category", "lot__seller"
    ).annotate(current_price=CURRENT_PRICE)


# ---------------------------------------------------------------------------
# Bidding and watchlist
# ---------------------------------------------------------------------------


class PlaceBidView(APIView):
    permission_classes = [CanBid]

    @extend_schema(
        request=BidInputSerializer, responses={201: BidSerializer}
    )
    def post(self, request, pk):
        """Place a bid. Bids cannot be retracted."""
        auction = get_object_or_404(Auction, pk=pk)
        form = BidForm(request.data)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            bid = services.place_bid(
                request.user, auction, form.cleaned_data["amount"]
            )
        except services.BidError as exc:
            return error(str(exc))
        return Response(
            BidSerializer(bid).data, status=status.HTTP_201_CREATED
        )


class WithdrawBidView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(
        request=ReasonInputSerializer, responses={200: BidSerializer}
    )
    def post(self, request, pk):
        """Withdraw a bid (Moderators only). A reason is required."""
        bid = get_object_or_404(Bid, pk=pk)
        form = WithdrawBidForm(request.data)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            bid = services.withdraw_bid(
                request.user, bid, form.cleaned_data["reason"]
            )
        except services.BidError as exc:
            return error(str(exc))
        return Response(BidSerializer(bid).data)


class WatchToggleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: WatchResultSerializer})
    def post(self, request, pk):
        """Add the auction to your watchlist, or remove it if present."""
        auction = get_object_or_404(Auction, pk=pk)
        watching = services.toggle_watch(request.user, auction)
        return Response({"watching": watching})


class WatchlistView(generics.ListAPIView):
    """Auctions you are watching."""

    serializer_class = AuctionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Auction.objects.filter(watchers__user=self.request.user)
            .select_related("lot__category", "lot__seller")
            .annotate(current_price=CURRENT_PRICE)
            .order_by("end_time")
        )


# ---------------------------------------------------------------------------
# Sellers
# ---------------------------------------------------------------------------


class SellerLotListView(generics.ListAPIView):
    """Your own lots (Sellers only)."""

    serializer_class = LotSerializer
    permission_classes = [IsSeller]

    def get_queryset(self):
        return self.request.user.lots.select_related("category", "seller")

    @extend_schema(request=LotSerializer, responses={201: LotSerializer})
    def post(self, request):
        """Submit a new lot. It starts as PENDING."""
        form = LotForm(request.data)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        lot = services.create_lot(request.user, form)
        return Response(
            LotSerializer(lot).data, status=status.HTTP_201_CREATED
        )


class SellerLotDetailView(APIView):
    """One of your own lots. It can be edited until it is approved."""

    permission_classes = [IsSeller]

    def get_lot(self, request, pk):
        # Filtering by seller gives other sellers a 404.
        return get_object_or_404(Lot, pk=pk, seller=request.user)

    @extend_schema(responses={200: LotSerializer})
    def get(self, request, pk):
        return Response(LotSerializer(self.get_lot(request, pk)).data)

    @extend_schema(request=LotSerializer, responses={200: LotSerializer})
    def put(self, request, pk):
        """Replace all editable fields."""
        lot = self.get_lot(request, pk)
        return self.save(request, lot, LotForm(request.data, instance=lot))

    @extend_schema(request=LotSerializer, responses={200: LotSerializer})
    def patch(self, request, pk):
        """Change only the fields sent."""
        lot = self.get_lot(request, pk)
        data = merge_with_current_values(LotForm, lot, request.data)
        return self.save(request, lot, LotForm(data, instance=lot))

    def save(self, request, lot, form):
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            lot = services.update_lot_by_seller(request.user, lot, form)
        except services.LotStateError as exc:
            return error(str(exc))
        return Response(LotSerializer(lot).data)


# ---------------------------------------------------------------------------
# Moderators
# ---------------------------------------------------------------------------


class ModerationQueueView(generics.ListAPIView):
    """Lots waiting for review, oldest first (Moderators only)."""

    serializer_class = LotSerializer
    permission_classes = [IsModerator]

    def get_queryset(self):
        return (
            Lot.objects.filter(status=Lot.Status.PENDING)
            .select_related("category", "seller")
            .order_by("created_at")
        )


class ModerationLotView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses={200: LotSerializer})
    def get(self, request, pk):
        """Any lot, with full details."""
        lot = get_object_or_404(Lot, pk=pk)
        return Response(LotSerializer(lot).data)

    @extend_schema(
        request=ModeratorLotInputSerializer, responses={200: LotSerializer}
    )
    def patch(self, request, pk):
        """Change the category and/or description. Prices are ignored."""
        lot = get_object_or_404(Lot, pk=pk)
        data = merge_with_current_values(ModeratorLotForm, lot, request.data)
        form = ModeratorLotForm(data, instance=lot)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        lot = services.update_lot_by_moderator(request.user, lot, form)
        return Response(LotSerializer(lot).data)


class ApproveLotView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=None, responses={200: AuctionSerializer})
    def post(self, request, pk):
        """Approve a pending lot. Its auction starts straight away."""
        lot = get_object_or_404(Lot, pk=pk)
        try:
            auction = services.approve_lot(request.user, lot)
        except services.LotStateError as exc:
            return error(str(exc))
        return Response(AuctionSerializer(auction).data)


class RejectLotView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(
        request=ReasonInputSerializer, responses={200: LotSerializer}
    )
    def post(self, request, pk):
        """Reject a pending lot. The reason is shown to the seller."""
        lot = get_object_or_404(Lot, pk=pk)
        form = RejectLotForm(request.data)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            lot = services.reject_lot(
                request.user, lot, form.cleaned_data["reason"]
            )
        except services.LotStateError as exc:
            return error(str(exc))
        return Response(LotSerializer(lot).data)
