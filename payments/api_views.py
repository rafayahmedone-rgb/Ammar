"""REST API views for payments. Business rules live in services.py."""

from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from . import services
from .models import Payment
from .serializers import PaymentSerializer


class MyPurchasesView(generics.ListAPIView):
    """Everything you have won."""

    serializer_class = PaymentSerializer

    def get_queryset(self):
        return self.request.user.payments.select_related(
            "auction__lot", "buyer"
        )


class PaymentDetailView(generics.RetrieveAPIView):
    """One payment. Visible to its buyer, its seller and Admins."""

    serializer_class = PaymentSerializer
    queryset = Payment.objects.select_related("auction__lot", "buyer")

    def get_object(self):
        payment = super().get_object()
        user = self.request.user
        allowed = (
            payment.buyer_id == user.pk
            or payment.auction.lot.seller_id == user.pk
            or user.role == User.Role.ADMIN
        )
        if not allowed:
            raise Http404
        return payment


class PayNowView(APIView):
    @extend_schema(request=None, responses={200: PaymentSerializer})
    def post(self, request, pk):
        """Mock payment: marks the payment as PAID (buyer only)."""
        payment = get_object_or_404(Payment, pk=pk)
        try:
            payment = services.pay(request.user, payment)
        except services.PaymentError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(PaymentSerializer(payment).data)
