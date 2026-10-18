"""
Serializers turn model objects into JSON for the API.

Input is NOT validated here: the API views use the same Django forms as
the website (auctions/forms.py), so both follow exactly the same rules.
The small "...Input" serializers at the bottom only describe the request
bodies for the API docs at /api/docs/.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import services
from .models import Auction, Bid, Category, Lot


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "description")


class LotSerializer(serializers.ModelSerializer):
    """
    Full lot details, including the reserve price. Only used for the
    seller's own lots and for Moderators.
    """

    category_name = serializers.CharField(
        source="category.name", read_only=True
    )
    seller = serializers.CharField(source="seller.username", read_only=True)

    class Meta:
        model = Lot
        fields = (
            "id",
            "title",
            "category",
            "category_name",
            "description",
            "starting_price",
            "reserve_price",
            "duration_days",
            "seller",
            "status",
            "rejection_reason",
            "created_at",
        )
        read_only_fields = ("status", "rejection_reason", "created_at")


class PublicLotSerializer(serializers.ModelSerializer):
    """Lot details anyone may see. The reserve price is left out."""

    category_name = serializers.CharField(
        source="category.name", read_only=True
    )
    seller = serializers.CharField(source="seller.username", read_only=True)

    class Meta:
        model = Lot
        fields = ("id", "title", "category", "category_name", "description",
                  "starting_price", "seller")


class BidSerializer(serializers.ModelSerializer):
    bidder = serializers.CharField(source="bidder.username", read_only=True)

    class Meta:
        model = Bid
        fields = ("id", "amount", "bidder", "created_at", "is_withdrawn")


class AuctionSerializer(serializers.ModelSerializer):
    lot = PublicLotSerializer(read_only=True)
    # Filled in by .annotate(current_price=...) in the view's queryset.
    # default=None is used when the auction was not annotated.
    current_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True,
        default=None,
    )

    class Meta:
        model = Auction
        fields = ("id", "lot", "status", "start_time", "end_time",
                  "extension_count", "current_price")


class AuctionDetailSerializer(AuctionSerializer):
    """One auction, with the minimum next bid and the bid history."""

    minimum_bid = serializers.SerializerMethodField()
    bids = serializers.SerializerMethodField()

    class Meta(AuctionSerializer.Meta):
        fields = AuctionSerializer.Meta.fields + ("minimum_bid", "bids")

    def get_minimum_bid(self, auction) -> str:
        return str(services.minimum_bid(auction))

    @extend_schema_field(BidSerializer(many=True))
    def get_bids(self, auction):
        # Withdrawn bids are not public.
        bids = auction.bids.filter(is_withdrawn=False).select_related(
            "bidder"
        )
        return BidSerializer(bids, many=True).data


# ---------------------------------------------------------------------------
# Request bodies (for the API docs only)
# ---------------------------------------------------------------------------


class BidInputSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField()


class ModeratorLotInputSerializer(serializers.Serializer):
    category = serializers.IntegerField(required=False)
    description = serializers.CharField(required=False)


class WatchResultSerializer(serializers.Serializer):
    watching = serializers.BooleanField()
