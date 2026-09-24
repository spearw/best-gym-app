import zoneinfo
from decimal import Decimal

from django import forms
from django.contrib.auth import password_validation

from apps.exercises.starter import PACK_CHOICES, PACKS

from .metrics import metric_specs
from .models import Units, User, WeekStart, YearsTraining


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
    starter = forms.ChoiceField(
        choices=PACK_CHOICES,
        widget=forms.RadioSelect,
        label="Start with",
        error_messages={"required": "Pick how you'd like to start."},
    )

    field_order = ["name", "email", "password", "gym_name", "units", "starter", "browser_timezone"]

    def starter_options(self):
        """Radio options with each pack's description, for the template."""
        chosen = self["starter"].value()
        return [
            {"key": p.key, "label": p.label, "description": p.description, "checked": p.key == chosen}
            for p in PACKS.values()
        ]


class JoinForm(NewAccountFields):
    def __init__(self, *args, invite_email="", **kwargs):
        super().__init__(*args, **kwargs)
        if invite_email:
            self.fields["email"].initial = invite_email


class MetricsForm(InputClassMixin, forms.Form):
    """The athlete's numbers: bodyweight, height, the gym's tracked lifts, years
    training. Every field is optional: blank means skipped, and the coach can fill
    it in later. `only` limits the form to some metric keys (e.g. just the missing ones)."""

    def __init__(self, *args, gym, units="kg", only=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        for metric in metric_specs(gym):
            if only is not None and metric.key not in only:
                continue
            self.fields[metric.key] = self._field(metric, units)
        for field in self.fields.values():
            # "skip" (Alpine) clears and disables the input; disabled inputs aren't submitted.
            field.widget.attrs["x-ref"] = "i"
            field.widget.attrs[":disabled"] = "skipped"
            field.widget.attrs[":placeholder"] = "skipped ? 'skipped — coach can fill in' : $el.dataset.ph"
            field.widget.attrs["data-ph"] = field.widget.attrs.get("placeholder", "")

    @staticmethod
    def _field(metric, units):
        if metric.kind == "years":
            return forms.ChoiceField(
                required=False,
                choices=[("", "Select…"), *YearsTraining.choices],
                label=metric.label,
                widget=forms.Select(attrs={"class": "input"}),
            )
        if metric.kind == "height":
            field = forms.DecimalField(
                required=False,
                min_value=Decimal("100"),
                max_value=Decimal("250"),
                decimal_places=1,
                label="Height (cm)",
            )
            placeholder = "e.g. 168"
        elif metric.key == "bodyweight":
            field = forms.DecimalField(
                required=False,
                min_value=Decimal("20"),
                max_value=Decimal("600"),
                decimal_places=2,
                label=f"Bodyweight ({units})",
            )
            placeholder = "e.g. 64" if units == "kg" else "e.g. 141"
        else:
            field = forms.DecimalField(
                required=False,
                min_value=Decimal("1"),
                max_value=Decimal("1000"),
                decimal_places=2,
                label=f"{metric.label} ({units})",
            )
            placeholder = "best single"
        field.widget.attrs.update(
            {"class": "input", "placeholder": placeholder, "inputmode": "decimal", "step": "any"}
        )
        return field

    def skipped_count(self):
        return sum(1 for name in self.fields if self.cleaned_data.get(name) in (None, ""))


class InviteForm(InputClassMixin, forms.Form):
    email = forms.EmailField(
        required=False,
        label="Athlete email",
        widget=forms.EmailInput(attrs={"placeholder": "athlete@example.com"}),
    )
    starting_template = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Starting template",
        empty_label="None — I'll build their program",
        help_text="Applied as a draft program from the week after they join, for you to review and publish.",
    )

    def __init__(self, *args, gym, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.library.models import Template, TemplateKind

        self.fields["starting_template"].queryset = Template.objects.filter(
            gym=gym, kind__in=[TemplateKind.PROGRAM, TemplateKind.WEEK]
        ).order_by("kind", "name")
        self.fields["starting_template"].label_from_instance = lambda t: (
            f"{t.display_name}{' (saved week)' if t.kind == TemplateKind.WEEK else ''}"
        )


class GymSettingsForm(InputClassMixin, forms.Form):
    gym_name = forms.CharField(max_length=120, label="Gym or team name")
    coach_title = forms.CharField(max_length=60, required=False, label="Your title")
    timezone = forms.ChoiceField(label="Gym time zone")
    units = forms.ChoiceField(choices=Units.choices, widget=forms.RadioSelect)
    week_start = forms.TypedChoiceField(
        choices=WeekStart.choices,
        coerce=int,
        widget=forms.RadioSelect,
        label="Training weeks start on",
        help_text="Used for new programs. Existing programs keep their dates.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["timezone"].choices = timezone_choices()
        self.fields["timezone"].help_text = "The coach dashboard counts days in this zone."
