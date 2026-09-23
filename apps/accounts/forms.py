import zoneinfo
from decimal import Decimal

from django import forms
from django.contrib.auth import password_validation

from apps.programs.week_types import WEEK_TYPES

from .models import Units, User, YearsTraining


def timezone_choices():
    return [(tz, tz.replace("_", " ")) for tz in sorted(zoneinfo.available_timezones())]


def clean_browser_timezone(value, fallback):
    """The browser reports its zone in a hidden field; use it if it's real."""
    return value if value in zoneinfo.available_timezones() else fallback


class InputClassMixin:
    """The mockup styles every control with .input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.HiddenInput)):
                field.widget.attrs.setdefault("class", "input")


class NewAccountFields(InputClassMixin, forms.Form):
    name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "8+ characters"})
    )
    browser_timezone = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Log in instead.")
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            candidate = User(email=cleaned.get("email") or "", name=cleaned.get("name") or "")
            try:
                password_validation.validate_password(password, candidate)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return cleaned


class CoachSignupForm(NewAccountFields):
    gym_name = forms.CharField(max_length=120, label="Gym or team name")
    units = forms.ChoiceField(choices=Units.choices, initial=Units.KG, widget=forms.RadioSelect)

    field_order = ["name", "email", "password", "gym_name", "units", "browser_timezone"]


class JoinForm(NewAccountFields):
    def __init__(self, *args, invite_email="", **kwargs):
        super().__init__(*args, **kwargs)
        if invite_email:
            self.fields["email"].initial = invite_email


class MetricsForm(InputClassMixin, forms.Form):
    """Onboarding numbers. Every field is optional: blank means skipped, and the
    coach can fill it in later."""

    bodyweight = forms.DecimalField(
        required=False, min_value=Decimal("20"), max_value=Decimal("600"), decimal_places=2
    )
    height_cm = forms.DecimalField(
        required=False,
        min_value=Decimal("100"),
        max_value=Decimal("250"),
        decimal_places=1,
        label="Height (cm)",
    )
    sn = forms.DecimalField(
        required=False, min_value=Decimal("1"), max_value=Decimal("1000"), decimal_places=2
    )
    cj = forms.DecimalField(
        required=False, min_value=Decimal("1"), max_value=Decimal("1000"), decimal_places=2
    )
    bsq = forms.DecimalField(
        required=False, min_value=Decimal("1"), max_value=Decimal("1000"), decimal_places=2
    )
    years_training = forms.ChoiceField(
        required=False, choices=[("", "Select…"), *YearsTraining.choices], label="Years training"
    )

    def __init__(self, *args, units="kg", only=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        if only is not None:
            for name in list(self.fields):
                if name not in only:
                    del self.fields[name]
        labels = {
            "bodyweight": f"Bodyweight ({units})",
            "sn": f"Snatch 1RM ({units})",
            "cj": f"Clean & Jerk 1RM ({units})",
            "bsq": f"Back Squat 1RM ({units})",
        }
        placeholders = {
            "bodyweight": "e.g. 64" if units == "kg" else "e.g. 141",
            "height_cm": "e.g. 168",
            "sn": "best single",
        }
        for name, field in self.fields.items():
            if name in labels:
                field.label = labels[name]
            if name in placeholders:
                field.widget.attrs["placeholder"] = placeholders[name]
            if name != "years_training":
                field.widget.attrs["inputmode"] = "decimal"
                field.widget.attrs["step"] = "any"
        for field in self.fields.values():
            # "skip" (Alpine) clears and disables the input; disabled inputs aren't submitted.
            field.widget.attrs["x-ref"] = "i"
            field.widget.attrs[":disabled"] = "skipped"
            field.widget.attrs[":placeholder"] = "skipped ? 'skipped — coach can fill in' : $el.dataset.ph"
            field.widget.attrs["data-ph"] = field.widget.attrs.get("placeholder", "")

    def skipped_count(self):
        return sum(1 for name in self.fields if self.cleaned_data.get(name) in (None, ""))


class InviteForm(InputClassMixin, forms.Form):
    email = forms.EmailField(
        required=False,
        label="Athlete email",
        widget=forms.EmailInput(attrs={"placeholder": "athlete@example.com"}),
    )


class GymSettingsForm(InputClassMixin, forms.Form):
    gym_name = forms.CharField(max_length=120, label="Gym or team name")
    coach_title = forms.CharField(max_length=60, required=False, label="Your title")
    timezone = forms.ChoiceField(label="Gym time zone")
    units = forms.ChoiceField(choices=Units.choices, widget=forms.RadioSelect)

    def __init__(self, *args, gym=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["timezone"].choices = timezone_choices()
        self.fields["timezone"].help_text = "The coach dashboard counts days in this zone."
        for key, wt in WEEK_TYPES.items():
            default = wt["colour"]
            self.fields[f"colour_{key}"] = forms.RegexField(
                regex=r"^#[0-9A-Fa-f]{6}$",
                required=False,
                label=wt["label"],
                widget=forms.TextInput(attrs={"type": "color", "class": "colour-input"}),
                initial=(gym.week_type_colours.get(key, default) if gym else default),
            )

    def colour_overrides(self):
        """Only colours that differ from the defaults are stored."""
        overrides = {}
        for key, wt in WEEK_TYPES.items():
            value = (self.cleaned_data.get(f"colour_{key}") or "").upper()
            if value and value != wt["colour"].upper():
                overrides[key] = value
        return overrides
