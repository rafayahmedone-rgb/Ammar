from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    lot_title = serializers.CharField(
        source="auction.lot.title", read_only=True
    )
    buyer = serializers.CharField(source="buyer.username", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "auction",
            "lot_title",
            "buyer",
            "hammer_price",
            "gst_amount",
            "total_amount",
            "commission_percent",
            "commission_amount",
            "seller_payout",
            "status",
            "due_at",
            "paid_at",
            "reference",
        )
        read_only_fields = fields
