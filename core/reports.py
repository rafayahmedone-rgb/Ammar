"""
Admin reports.

Every function takes a start and end datetime and returns plain Python
values (numbers, dicts, lists) for the reports page and CSV export.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone

from auctions.models import Auction, Bid, Lot
from payments.models import Payment

from .models import Dispute

User = get_user_model()


def date_range(start_date, end_date):
    """
    Turn two dates into datetimes covering whole days in Sydney time:
    from midnight at the start of start_date up to (but not including)
    midnight after end_date.
    """
    start = timezone.make_aware(datetime.combine(start_date, time.min))
    end = timezone.make_aware(
        datetime.combine(end_date + timedelta(days=1), time.min)
    )
    return start, end


def money(value):
    """Sum() returns None when there are no rows; show $0.00 instead."""
    return value if value is not None else Decimal("0.00")


def sales_summary(start, end):
    """Sales closed in the period, and money actually received."""
    closed = Payment.objects.filter(created_at__gte=start, created_at__lt=end)
    paid = Payment.objects.filter(
        status=Payment.Status.PAID, paid_at__gte=start, paid_at__lt=end
    )
    totals = paid.aggregate(
        hammer=Sum("hammer_price"),
        gst=Sum("gst_amount"),
        total=Sum("total_amount"),
        commission=Sum("commission_amount"),
        payout=Sum("seller_payout"),
    )
    return {
        "sales_closed": closed.count(),
        "awaiting_payment": closed.filter(
            status=Payment.Status.PENDING
        ).count(),
        "expired": closed.filter(status=Payment.Status.EXPIRED).count(),
        "payments_received": paid.count(),
        "hammer_total": money(totals["hammer"]),
        "gst_total": money(totals["gst"]),
        "received_total": money(totals["total"]),
        "commission_total": money(totals["commission"]),
        "payout_total": money(totals["payout"]),
    }


def auction_summary(start, end):
    """How auctions that ended in the period finished, plus live ones."""
    ended = Auction.objects.filter(end_time__gte=start, end_time__lt=end)
    # values() + annotate() gives one row per status, e.g.
    # [{"status": "SOLD", "count": 3}, {"status": "NOT_SOLD", "count": 1}]
    rows = ended.values("status").annotate(count=Count("id"))
    counts = {row["status"]: row["count"] for row in rows}
    return {
        "active_now": Auction.objects.filter(
            status=Auction.Status.ACTIVE
        ).count(),
        "sold": counts.get(Auction.Status.SOLD, 0),
        "not_sold": counts.get(Auction.Status.NOT_SOLD, 0),
        "cancelled": counts.get(Auction.Status.CANCELLED, 0),
    }


def activity_summary(start, end):
    """What users did on the site during the period."""
    lots = Lot.objects.filter(created_at__gte=start, created_at__lt=end)
    return {
        "new_users": User.objects.filter(
            date_joined__gte=start, date_joined__lt=end
        ).count(),
        "lots_submitted": lots.count(),
        "bids_placed": Bid.objects.filter(
            created_at__gte=start, created_at__lt=end
        ).count(),
        "disputes_raised": Dispute.objects.filter(
            created_at__gte=start, created_at__lt=end
        ).count(),
        "disputes_open_now": Dispute.objects.filter(
            status=Dispute.Status.OPEN
        ).count(),
        "lots_pending_now": Lot.objects.filter(
            status=Lot.Status.PENDING
        ).count(),
    }


def sales_by_category(start, end):
    """Money received per category, biggest first."""
    return list(
        Payment.objects.filter(
            status=Payment.Status.PAID, paid_at__gte=start, paid_at__lt=end
        )
        .values("auction__lot__category__name")
        .annotate(
            sales=Count("id"),
            hammer=Sum("hammer_price"),
            commission=Sum("commission_amount"),
        )
        .order_by("-hammer")
    )


def payments_in_range(start, end):
    """Every payment created in the period, for the CSV export."""
    return (
        Payment.objects.filter(created_at__gte=start, created_at__lt=end)
        .select_related("auction__lot__category", "auction__lot__seller",
                        "buyer")
        .order_by("created_at")
    )
