from decimal import Decimal

from django import forms

from apps.accounts.forms import InputClassMixin

from .models import IssueKind, IssueReport

RIR_CHOICES = [("", "—"), ("0", "0"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5+")]


class SetForm(forms.Form):
    """One set from the player, in the athlete's unit. Time is entered in `time_unit`."""

    load = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_value=Decimal("2000"), decimal_places=2
    )
    reps = forms.IntegerField(required=False, min_value=0, max_value=999)
    time = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_value=Decimal("1440"), decimal_places=2
    )
    time_unit = forms.ChoiceField(required=False, choices=[("s", "s"), ("min", "min")])
    rir = forms.TypedChoiceField(required=False, choices=RIR_CHOICES, coerce=int, empty_value=None)
    done = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        time = data.get("time")
        if time is not None:
            data["duration_seconds"] = int(time * (60 if data.get("time_unit") == "min" else 1))
        else:
            data["duration_seconds"] = None
        return data


class FinishForm(forms.Form):
    rpe = forms.IntegerField(min_value=1, max_value=10, error_messages={"required": "Pick how hard it was."})
    comment = forms.CharField(required=False, max_length=2000, widget=forms.Textarea)


class IssueForm(InputClassMixin, forms.ModelForm):
    class Meta:
        model = IssueReport
        fields = ["kind", "text"]
        labels = {"kind": "What kind of issue?", "text": "Where / what?"}
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 3, "placeholder": "e.g. sharp pinch in left wrist at jerk lockout, ~120kg"}
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = IssueKind.choices
