from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from . import services
from .forms import (
    BidForm,
    LotForm,
    ModeratorLotForm,
    RejectLotForm,
    WithdrawBidForm,
)
from .models import Auction, Bid, Category, Lot, Watchlist

# Highest bid per auction, ignoring withdrawn bids. Used with annotate()
# so a list of auctions gets each one's current price in a single query.
# Note: Django ignores Meta.ordering on these grouped queries, so every
# list that uses it needs its own .order_by().
CURRENT_PRICE = Max("bids__amount", filter=Q(bids__is_withdrawn=False))

# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


def auction_list(request):
    """List auctions that are open for bidding, optionally by category."""
    auctions = (
        Auction.objects.filter(
            status=Auction.Status.ACTIVE,
            end_time__gt=timezone.now(),
        )
        # select_related fetches the lot and category in the same query.
        .select_related("lot", "lot__category")
        .annotate(current_price=CURRENT_PRICE)
        .order_by("end_time")
    )

    category_id = request.GET.get("category")
    if category_id and category_id.isdigit():
        auctions = auctions.filter(lot__category_id=category_id)

    context = {
        "auctions": auctions,
        "categories": Category.objects.all(),
        "selected_category": category_id,
    }
    return render(request, "auctions/auction_list.html", context)


def lot_detail(request, pk):
    """
    Show one lot.

    Approved lots are public. Pending or rejected lots can only be seen by
    their seller and by Moderators/Admins.
    """
    lot = get_object_or_404(
        Lot.objects.select_related("seller", "category"), pk=pk
    )

    if lot.status != Lot.Status.APPROVED:
        user = request.user
        is_owner = user.is_authenticated and lot.seller_id == user.pk
        is_staff_role = user.is_authenticated and user.role in (
            User.Role.MODERATOR,
            User.Role.ADMIN,
        )
        if not (is_owner or is_staff_role):
            # Pretend it does not exist rather than reveal it.
            raise Http404

    # getattr(...) returns None when the lot has no auction yet.
    auction = getattr(lot, "auction", None)
    context = {"lot": lot, "auction": auction}
    if auction is not None:
        context.update(auction_context(request.user, auction))
    return render(request, "auctions/lot_detail.html", context)


def auction_context(user, auction):
    """Everything the lot page needs to show the bidding panel."""
    is_moderator = user.is_authenticated and user.is_moderator
    is_open = (
        auction.status == Auction.Status.ACTIVE
        and timezone.now() < auction.end_time
    )
    can_bid = (
        is_open
        and user.is_authenticated
        and user.role in services.BIDDING_ROLES
        and auction.lot.seller_id != user.pk
    )

    bids = auction.bids.select_related("bidder")
    if not is_moderator:
        # Only Moderators see withdrawn bids.
        bids = bids.filter(is_withdrawn=False)

    return {
        # None unless the auction was SOLD.
        "payment": getattr(auction, "payment", None),
        "highest_bid": auction.highest_bid(),
        "minimum_bid": services.minimum_bid(auction),
        "bids": bids,
        "is_open": is_open,
        "can_bid": can_bid,
        "bid_form": BidForm(),
        "is_moderator": is_moderator,
        "withdraw_form": WithdrawBidForm(),
        "is_watching": (
            user.is_authenticated
            and Watchlist.objects.filter(user=user, auction=auction).exists()
        ),
    }


# ---------------------------------------------------------------------------
# Bidding and watchlist
# ---------------------------------------------------------------------------


@require_POST
@role_required(*services.BIDDING_ROLES)
def bid_place(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    form = BidForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please enter a valid amount, e.g. 125.50.")
    else:
        try:
            bid = services.place_bid(
                request.user, auction, form.cleaned_data["amount"]
            )
        except services.BidError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Your bid of ${bid.amount} was placed.")

    return redirect("auctions:lot_detail", pk=auction.lot_id)


@require_POST
@role_required(User.Role.MODERATOR)
def bid_withdraw(request, pk):
    bid = get_object_or_404(Bid.objects.select_related("auction"), pk=pk)
    form = WithdrawBidForm(request.POST)

    if not form.is_valid():
        messages.error(request, "A reason is required to withdraw a bid.")
    else:
        try:
            services.withdraw_bid(
                request.user, bid, form.cleaned_data["reason"]
            )
        except services.BidError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The bid was withdrawn.")

    return redirect("auctions:lot_detail", pk=bid.auction.lot_id)


@require_POST
@login_required
def watch_toggle(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    if services.toggle_watch(request.user, auction):
        messages.success(request, "Added to your watchlist.")
    else:
        messages.info(request, "Removed from your watchlist.")
    return redirect("auctions:lot_detail", pk=auction.lot_id)


@login_required
def watchlist(request):
    auctions = (
        Auction.objects.filter(watchers__user=request.user)
        .select_related("lot", "lot__category")
        .annotate(current_price=CURRENT_PRICE)
        .order_by("end_time")
    )
    return render(
        request, "auctions/watchlist.html", {"auctions": auctions}
    )


@role_required(*services.BIDDING_ROLES)
def my_bids(request):
    """Auctions the user has bid on, with their best bid in each."""
    # A subquery is used instead of filter(bids__bidder=...) because that
    # filter would also limit CURRENT_PRICE to this user's bids only.
    my_auction_ids = Bid.objects.filter(bidder=request.user).values(
        "auction_id"
    )
    auctions = (
        Auction.objects.filter(pk__in=my_auction_ids)
        .select_related("lot")
        .annotate(
            current_price=CURRENT_PRICE,
            my_best=Max(
                "bids__amount",
                filter=Q(bids__bidder=request.user, bids__is_withdrawn=False),
            ),
        )
        .order_by("end_time")
    )
    return render(request, "auctions/my_bids.html", {"auctions": auctions})


# ---------------------------------------------------------------------------
# Seller pages
# ---------------------------------------------------------------------------


@role_required(User.Role.SELLER)
def my_lots(request):
    lots = request.user.lots.select_related(
        "category", "auction", "auction__payment"
    )
    return render(request, "auctions/my_lots.html", {"lots": lots})


@role_required(User.Role.SELLER)
def lot_create(request):
    if request.method == "POST":
        form = LotForm(request.POST)
        if form.is_valid():
            lot = services.create_lot(request.user, form)
            messages.success(
                request, f'"{lot.title}" was submitted for review.'
            )
            return redirect("auctions:my_lots")
    else:
        form = LotForm()

    return render(
        request, "auctions/lot_form.html", {"form": form, "is_new": True}
    )


@role_required(User.Role.SELLER)
def lot_edit(request, pk):
    # Filtering by seller means other sellers get a 404 for this lot.
    lot = get_object_or_404(Lot, pk=pk, seller=request.user)
    if not lot.seller_can_edit:
        messages.error(request, "This lot can no longer be edited.")
        return redirect("auctions:lot_detail", pk=lot.pk)

    if request.method == "POST":
        form = LotForm(request.POST, instance=lot)
        if form.is_valid():
            try:
                services.update_lot_by_seller(request.user, lot, form)
            except services.LotStateError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, "Your changes were saved.")
            return redirect("auctions:my_lots")
    else:
        form = LotForm(instance=lot)

    return render(
        request,
        "auctions/lot_form.html",
        {"form": form, "lot": lot, "is_new": False},
    )


# ---------------------------------------------------------------------------
# Moderator pages
# ---------------------------------------------------------------------------


@role_required(User.Role.MODERATOR)
def moderation_queue(request):
    """Pending lots, oldest first, so nothing waits too long."""
    lots = (
        Lot.objects.filter(status=Lot.Status.PENDING)
        .select_related("seller", "category")
        .order_by("created_at")
    )
    return render(request, "auctions/moderation_queue.html", {"lots": lots})


@role_required(User.Role.MODERATOR)
def moderation_review(request, pk):
    """Review page with the Approve button and the Reject form."""
    lot = get_object_or_404(
        Lot.objects.select_related("seller", "category"), pk=pk
    )
    return render(
        request,
        "auctions/moderation_review.html",
        {"lot": lot, "reject_form": RejectLotForm()},
    )


@require_POST
@role_required(User.Role.MODERATOR)
def lot_approve(request, pk):
    lot = get_object_or_404(Lot, pk=pk)
    try:
        services.approve_lot(request.user, lot)
    except services.LotStateError as error:
        messages.error(request, str(error))
        return redirect("auctions:moderation_review", pk=lot.pk)

    messages.success(request, f'"{lot.title}" approved. Its auction is live.')
    return redirect("auctions:moderation_queue")


@require_POST
@role_required(User.Role.MODERATOR)
def lot_reject(request, pk):
    lot = get_object_or_404(Lot, pk=pk)
    form = RejectLotForm(request.POST)
    if not form.is_valid():
        # Show the review page again with the "reason is required" error.
        return render(
            request,
            "auctions/moderation_review.html",
            {"lot": lot, "reject_form": form},
        )

    try:
        services.reject_lot(request.user, lot, form.cleaned_data["reason"])
    except services.LotStateError as error:
        messages.error(request, str(error))
        return redirect("auctions:moderation_review", pk=lot.pk)

    messages.success(request, f'"{lot.title}" was rejected.')
    return redirect("auctions:moderation_queue")


@role_required(User.Role.MODERATOR)
def moderator_edit(request, pk):
    lot = get_object_or_404(Lot, pk=pk)

    if request.method == "POST":
        form = ModeratorLotForm(request.POST, instance=lot)
        if form.is_valid():
            services.update_lot_by_moderator(request.user, lot, form)
            messages.success(request, "Lot updated.")
            return redirect("auctions:moderation_review", pk=lot.pk)
    else:
        form = ModeratorLotForm(instance=lot)

    return render(
        request, "auctions/moderator_edit.html", {"form": form, "lot": lot}
    )
