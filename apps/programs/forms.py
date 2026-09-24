import datetime
from decimal import Decimal

from django import forms

from apps.accounts import units
from apps.accounts.forms import InputClassMixin

from .models import LoadBasis, WeekType
from .prescriptions import parse_rep_scheme, parse_rir, rir_text

MAX_SETS = 20
MAX_CUSTOM_FIELDS = 8
LOAD_LIMITS = {
    LoadBasis.PERCENT: (Decimal("1"), Decimal("200"), "a percentage between 1 and 200"),
    LoadBasis.RPE: (Decimal("1"), Decimal("10"), "an RPE between 1 and 10"),
    LoadBasis.WEIGHT: (Decimal("0.5"), Decimal("1000"), "a weight"),
}


class StartProgramForm(InputClassMixin, forms.Form):
    name = forms.CharField(
        max_length=80,
        label="Block name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Accumulation Block"}),
    )
    first_day = forms.DateField(label="Starts the week of", widget=forms.DateInput(attrs={"type": "date"}))
    weeks = forms.IntegerField(min_value=1, max_value=52, initial=4, label="Weeks")
    week_type = forms.ModelChoiceField(queryset=WeekType.objects.none(), empty_label=None, label="Week type")

    def __init__(self, *args, gym, today, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["week_type"].queryset = WeekType.objects.active().filter(gym=gym)
        self.fields["first_day"].initial = gym.week_start_for(today)
        start = gym.get_week_start_display()
        end = (datetime.date(2024, 1, 1) + datetime.timedelta(days=gym.week_start + 6)).strftime("%A")
        self.fields["first_day"].help_text = f"Weeks run {start}–{end}; any day in the first week works."


def _decimal(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except ArithmeticError as err:
        raise forms.ValidationError("Enter a number.") from err


class PrescriptionForm(InputClassMixin, forms.Form):
    """Sets, rep scheme, load, RIR, note, custom fields and optional per-set overrides,
    plus where the item sits in its session (warm-up, section heading, superset).
    Weights are entered in `unit` and stored in kg."""

    sets = forms.IntegerField(min_value=1, max_value=MAX_SETS)
    rep_scheme = forms.CharField(
        max_length=60, required=False, label="Reps", help_text="e.g. 5, 10-12, 1+1, 8/leg, 10 min, AMRAP"
    )
    load_basis = forms.ChoiceField(choices=LoadBasis.choices, label="Load basis")
    load_value = forms.CharField(required=False, label="Load")
    rir = forms.CharField(required=False, max_length=10, label="RIR target")
    warmup = forms.BooleanField(required=False, label="Warm-up drill")
    section = forms.CharField(required=False, max_length=40, label="Section heading above this")
    section_note = forms.CharField(required=False, max_length=200, label="Section note")
    superset = forms.BooleanField(required=False, label="Superset with the exercise above")
    note = forms.CharField(
        required=False,
        max_length=500,
        label="Note to athlete",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. pause 2s in the catch"}),
    )
    vary = forms.BooleanField(required=False, label="Vary by set")

    def __init__(self, *args, unit, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit

    @classmethod
    def initial_for(cls, rx, unit):
        value = rx.load_value
        if value is not None and rx.load_basis == LoadBasis.WEIGHT:
            value = units.from_kg(value, unit)
        return {
            "sets": rx.sets,
            "rep_scheme": rx.rep_scheme,
            "load_basis": rx.load_basis,
            "load_value": format(Decimal(value).normalize(), "f") if value is not None else "",
            "rir": rir_text(rx.rir, rx.rir_max),
            "note": rx.note,
            "vary": rx.set_overrides.exists(),
            "warmup": rx.warmup,
            "section": rx.section,
            "section_note": rx.section_note,
            "superset": rx.superset,
        }

    def _checked_load(self, basis, raw, where="Load"):
        value = _decimal(raw)
        if basis in (LoadBasis.NONE, LoadBasis.BODYWEIGHT):
            return None
        if value is None:
            raise forms.ValidationError(f"{where}: enter {LOAD_LIMITS[basis][2]}.")
        low, high, what = LOAD_LIMITS[basis]
        if not low <= value <= high:
            raise forms.ValidationError(f"{where}: enter {what}.")
        return units.to_kg(value, self.unit) if basis == LoadBasis.WEIGHT else value

    def clean_rir(self):
        try:
            return parse_rir(self.cleaned_data.get("rir"))
        except ValueError as err:
            raise forms.ValidationError("Enter a number (2) or a range (1-2), up to 10.") from err

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        data["rir"], data["rir_max"] = data["rir"]
        for name in ("section", "section_note"):
            data[name] = " ".join(data.get(name, "").split())
        if data["warmup"]:
            # A warm-up drill is ticked off once: no sets, load or RIR, and it isn't in a section.
            data.update(sets=1, load_basis=LoadBasis.NONE, rir=None, rir_max=None, vary=False)
            data.update(section="", section_note="", superset=False)
        basis = data["load_basis"]
        try:
            data["load_value"] = self._checked_load(basis, data.get("load_value"))
        except forms.ValidationError as err:
            self.add_error("load_value", err)
            return data

        data["rep_scheme"] = " ".join(data.get("rep_scheme", "").split())
        data["reps"], data["duration_seconds"] = parse_rep_scheme(data["rep_scheme"])

        keys, values = self.data.getlist("cf_key"), self.data.getlist("cf_value")
        custom = []
        for key, value in zip(keys, values, strict=False):
            key, value = " ".join(key.split())[:30], " ".join(value.split())[:60]
            if key:
                custom.append({"key": key, "value": value})
        if len(custom) > MAX_CUSTOM_FIELDS:
            self.add_error(None, f"Keep it to {MAX_CUSTOM_FIELDS} custom fields.")
        data["custom_fields"] = custom

        data["set_rows"] = []
        if data.get("vary"):
            reps_list, loads = self.data.getlist("set_reps"), self.data.getlist("set_load")
            if len(reps_list) != data["sets"] or len(loads) != data["sets"]:
                self.add_error(None, "Fill in a row for every set.")
                return data
            for i, (reps_text, load_raw) in enumerate(zip(reps_list, loads, strict=True), start=1):
                reps_text = " ".join(reps_text.split())[:30]
                try:
                    load = self._checked_load(basis, load_raw, where=f"Set {i}") if load_raw.strip() else None
                except forms.ValidationError as err:
                    self.add_error(None, err)
                    return data
                data["set_rows"].append(
                    {
                        "set_number": i,
                        "rep_scheme": reps_text,
                        "reps": parse_rep_scheme(reps_text or data["rep_scheme"])[0],
                        "load_value": load,
                    }
                )
        return data

    def save(self, rx):
        data = self.cleaned_data
        for field in [
            "sets",
            "rep_scheme",
            "reps",
            "duration_seconds",
            "load_basis",
            "load_value",
            "rir",
            "rir_max",
            "note",
            "custom_fields",
            "warmup",
            "section",
            "section_note",
            "superset",
        ]:
            setattr(rx, field, data[field])
        rx.save()
        from .prescriptions import keep_warmups_first

        keep_warmups_first(rx.session)
        # Works for a program prescription (PrescribedSet) and a template slot (TemplateSlotSet).
        rx.set_overrides.all().delete()
        model, parent = rx.set_overrides.model, rx.set_overrides.field.name
        model.objects.bulk_create([model(**{parent: rx}, **row) for row in data["set_rows"]])
        return rx


def set_rows_initial(rx, unit):
    """Rows for the 'vary by set' editor: saved overrides, else one per set from the parent."""
    rows = []
    overrides = {s.set_number: s for s in rx.set_overrides.all()}
    # Saved overrides count as edited, so they aren't overwritten by the parent fields.
    for n in range(1, rx.sets + 1):
        s = overrides.get(n)
        value = s.load_value if s and s.load_value is not None else rx.load_value
        if value is not None and rx.load_basis == LoadBasis.WEIGHT:
            value = units.from_kg(value, unit)
        rows.append(
            {
                "reps": (s.rep_scheme if s else "") or rx.rep_scheme,
                "load": format(Decimal(value).normalize(), "f") if value is not None else "",
                "edited": s is not None,
            }
        )
    return rows
