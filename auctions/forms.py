from decimal import Decimal

from django import forms

from core.forms import BootstrapFormMixin

from .models import Lot


class LotForm(BootstrapFormMixin, forms.ModelForm):
    """Form a Seller uses to create or edit a lot."""

    class Meta:
        model = Lot
        fields = (
            "title",
            "category",
            "description",
            "starting_price",
            "reserve_price",
            "duration_days",
        )
        labels = {
            "starting_price": "Starting price (AUD)",
            "reserve_price": "Reserve price (AUD, optional)",
            "duration_days": "Auction length",
        }
        help_texts = {
            "reserve_price": "The lowest price you will accept. "
                             "Bidders cannot see it.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def clean(self):
        cleaned_data = super().clean()
        starting = cleaned_data.get("starting_price")
        reserve = cleaned_data.get("reserve_price")
        # Only compare when both prices were entered and are valid.
        if starting and reserve and reserve < starting:
            self.add_error(
                "reserve_price",
                "The reserve price cannot be lower than the starting price.",
            )
        return cleaned_data


class ModeratorLotForm(BootstrapFormMixin, forms.ModelForm):
    """
    Form a Moderator uses to tidy up a lot.

    Moderators may only change the category and description, never the
    prices, so only those two fields are listed here.
    """

    class Meta:
        model = Lot
        fields = ("category", "description")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }


class RejectLotForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="The seller will see this reason.",
    )


class BidForm(BootstrapFormMixin, forms.Form):
    """
    The amount box on the lot page.

    It only checks that the amount is a positive number with cents. The
    real rules (minimum bid etc.) are checked in services.place_bid,
    while the auction row is locked.
    """

    amount = forms.DecimalField(
        label="Your bid (AUD)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )


class WithdrawBidForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        max_length=500,
        help_text="Recorded in the audit log.",
    )
