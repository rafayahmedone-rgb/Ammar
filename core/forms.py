from django import forms

from .models import Dispute


class BootstrapFormMixin:
    """Add Bootstrap 5 CSS classes to every field in a form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class DisputeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Dispute
        fields = ("reason", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "description": "Explain what happened. An Admin will review it.",
        }


class ResolveDisputeForm(BootstrapFormMixin, forms.Form):
    resolution = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Sent to both the buyer and the seller.",
    )


class ReportFilterForm(BootstrapFormMixin, forms.Form):
    """Date range for the reports page. Both dates are included."""

    # type="date" shows the browser's date picker.
    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start")
        end = cleaned_data.get("end")
        if start and end and start > end:
            raise forms.ValidationError("The start date must be first.")
        return cleaned_data
