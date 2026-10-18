from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User

from . import services
from .models import Payment


@login_required
def my_purchases(request):
    """Every item the user has won."""
    payments = request.user.payments.select_related("auction__lot")
    return render(
        request, "payments/my_purchases.html", {"payments": payments}
    )


@login_required
def payment_detail(request, pk):
    """
    The price breakdown for one sale.

    The buyer sees what they owe (with GST). The seller sees the
    commission and their payout. Admins can see both.
    """
    payment = get_object_or_404(
        Payment.objects.select_related("auction__lot__seller", "buyer"),
        pk=pk,
    )
    user = request.user
    is_buyer = payment.buyer_id == user.pk
    is_seller = payment.auction.lot.seller_id == user.pk
    is_admin = user.role == User.Role.ADMIN

    if not (is_buyer or is_seller or is_admin):
        raise Http404

    context = {
        "payment": payment,
        "is_buyer": is_buyer,
        "show_seller_view": is_seller or is_admin,
        "gst_percent": int(services.GST_RATE * 100),
    }
    return render(request, "payments/payment_detail.html", context)


@require_POST
@login_required
def pay_now(request, pk):
    """Mock payment: no card details, the button simply marks it paid."""
    payment = get_object_or_404(Payment, pk=pk)
    try:
        payment = services.pay(request.user, payment)
    except services.PaymentError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request, f"Payment received. Reference: {payment.reference}"
        )
    return redirect("payments:payment_detail", pk=pk)
