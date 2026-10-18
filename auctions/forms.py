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
