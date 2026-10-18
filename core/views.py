import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required
from payments.models import Payment

from . import reports, services
from .forms import DisputeForm, ReportFilterForm, ResolveDisputeForm
from .models import Dispute


def home(request):
    """Show the landing page."""
    return render(request, "core/home.html")


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


@login_required
def dispute_create(request, payment_pk):
    """The buyer or seller of a sale raises a dispute about it."""
    payment = get_object_or_404(
        Payment.objects.select_related("auction__lot"), pk=payment_pk
    )
    if not services.is_party_to(request.user, payment):
        raise Http404

    if request.method == "POST":
        form = DisputeForm(request.POST)
        if form.is_valid():
            try:
                dispute = services.raise_dispute(request.user, payment, form)
            except services.DisputeError as error:
                messages.error(request, str(error))
                return redirect("payments:payment_detail", pk=payment.pk)
            messages.success(request, "Your dispute was sent to an Admin.")
            return redirect("core:dispute_detail", pk=dispute.pk)
    else:
        form = DisputeForm()

    return render(
        request, "core/dispute_form.html", {"form": form, "payment": payment}
    )


@login_required
def dispute_list(request):
    """
    Admins see every dispute (open ones first). Everyone else sees the
    disputes about their own purchases and sales.
    """
    disputes = Dispute.objects.select_related(
        "payment__auction__lot", "raised_by"
    )
    if request.user.role == User.Role.ADMIN:
        # "OPEN" sorts before "RESOLVED", so open disputes come first.
        disputes = disputes.order_by("status", "created_at")
    else:
        # Q objects combine conditions with | (OR).
        disputes = disputes.filter(
            Q(payment__buyer=request.user)
            | Q(payment__auction__lot__seller=request.user)
        )
    return render(request, "core/dispute_list.html", {"disputes": disputes})


@login_required
def dispute_detail(request, pk):
    dispute = get_object_or_404(
        Dispute.objects.select_related(
            "payment__auction__lot__seller", "payment__buyer", "raised_by"
        ),
        pk=pk,
    )
    is_admin = request.user.role == User.Role.ADMIN
    if not (is_admin or services.is_party_to(request.user, dispute.payment)):
        raise Http404

    context = {
        "dispute": dispute,
        "is_admin": is_admin,
        "resolve_form": ResolveDisputeForm(),
    }
    return render(request, "core/dispute_detail.html", context)


@require_POST
@role_required(User.Role.ADMIN)
def dispute_resolve(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    form = ResolveDisputeForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please write a resolution.")
    else:
        try:
            services.resolve_dispute(
                request.user, dispute, form.cleaned_data["resolution"]
            )
        except services.DisputeError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The dispute was resolved.")

    return redirect("core:dispute_detail", pk=dispute.pk)


# ---------------------------------------------------------------------------
# Reports (Admins only)
# ---------------------------------------------------------------------------


def report_dates(request):
    """
    Read ?start=YYYY-MM-DD&end=YYYY-MM-DD from the URL. Defaults to the
    last 30 days. Returns (form, start_datetime, end_datetime).
    """
    today = timezone.localdate()
    form = ReportFilterForm(
        request.GET or {"start": today - timedelta(days=29), "end": today}
    )
    if form.is_valid():
        start_date = form.cleaned_data["start"]
        end_date = form.cleaned_data["end"]
    else:
        start_date, end_date = today - timedelta(days=29), today
    start, end = reports.date_range(start_date, end_date)
    return form, start, end


@role_required(User.Role.ADMIN)
def report_dashboard(request):
    form, start, end = report_dates(request)
    context = {
        "form": form,
        "sales": reports.sales_summary(start, end),
        "auctions": reports.auction_summary(start, end),
        "activity": reports.activity_summary(start, end),
        "categories": reports.sales_by_category(start, end),
        # Passed on to the CSV link so it uses the same dates.
        "query_string": request.GET.urlencode(),
    }
    return render(request, "core/reports.html", context)


@role_required(User.Role.ADMIN)
def report_payments_csv(request):
    """Download every sale in the date range as a spreadsheet (CSV)."""
    _form, start, end = report_dates(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="southern-cross-sales.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        "Closed", "Lot", "Category", "Seller", "Buyer", "Status",
        "Hammer price", "GST", "Total", "Commission", "Seller payout",
        "Paid at", "Reference",
    ])
    for payment in reports.payments_in_range(start, end):
        lot = payment.auction.lot
        paid_at = ""
        if payment.paid_at:
            paid_at = timezone.localtime(payment.paid_at).strftime(
                "%Y-%m-%d %H:%M"
            )
        writer.writerow([
            timezone.localtime(payment.created_at).strftime("%Y-%m-%d %H:%M"),
            lot.title,
            lot.category.name,
            lot.seller.username,
            payment.buyer.username,
            payment.get_status_display(),
            payment.hammer_price,
            payment.gst_amount,
            payment.total_amount,
            payment.commission_amount,
            payment.seller_payout,
            paid_at,
            payment.reference,
        ])
    return response
