import datetime
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Deferrable, Q
from django.db.models.functions import Lower

HEX_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_colour(value):
    if not HEX_COLOUR.fullmatch(value or ""):
        raise ValidationError(f"{value!r} is not a colour like #2E9E5B")


class WeekTypeQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived=False)


class WeekType(models.Model):
    """A gym's own week types (e.g. Accumulation, Deload). They colour-code the program
    editor, the athlete's week strip and session cards. A week type that programs or
    templates use can only be archived: it leaves the pickers but past weeks keep it."""

    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="week_types")
    name = models.CharField(max_length=30)
    description = models.CharField(max_length=120, blank=True)
    colour = models.CharField(max_length=7, validators=[validate_colour])
    order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)

    objects = WeekTypeQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(Lower("name"), "gym", name="unique_week_type_name_per_gym"),
        ]

    def __str__(self):
        return self.name

    @property
    def css_vars(self):
        """Inline CSS variables the mockup's .wk-pill / .wk-tab / .rx-item styles read."""
        return f"--wkc:{self.colour};--wkl:color-mix(in srgb, {self.colour} 16%, #fff)"


# ---------------------------------------------------------------- prescriptions (shared with templates)


class LoadBasis(models.TextChoices):
    PERCENT = "percent", "% of max"
    RPE = "rpe", "RPE"
    WEIGHT = "weight", "Weight"
    BODYWEIGHT = "bodyweight", "Bodyweight"
    NONE = "none", "No load"


class PrescriptionBase(models.Model):
    """One exercise's dose in one session. Shared by program prescriptions and (in
    phase 5) template slots, so applying a template copies every field.

    `rep_scheme` is what the athlete reads ("5", "1+1", "8/leg", "10 min"); `reps` and
    `duration_seconds` are parsed from it for maths (see prescriptions.parse_rep_scheme).
    `load_value` is just the number: 75 (percent), 8 (RPE) or a weight in kg."""

    sets = models.PositiveSmallIntegerField(default=3)
    rep_scheme = models.CharField(max_length=30, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    load_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    load_basis = models.CharField(max_length=12, choices=LoadBasis.choices, default=LoadBasis.NONE)
    rir = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)
    custom_fields = models.JSONField(default=list, blank=True)  # [{"key": "Tempo", "value": "3-1-0"}]

    class Meta:
        abstract = True


class PrescribedSetBase(models.Model):
    """A per-set override (e.g. 70/75/80%). No rows means every set follows the parent."""

    set_number = models.PositiveSmallIntegerField()
    rep_scheme = models.CharField(max_length=30, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    load_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["set_number"]


# ---------------------------------------------------------------- an athlete's program


class ProgramQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)


class Program(models.Model):
    """An athlete's training block: back-to-back weeks from `start_date`. One active
    program per athlete; starting a new one ends the current one, which is kept."""

    athlete = models.ForeignKey("accounts.Athlete", on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=80)
    start_date = models.DateField()
    active = models.BooleanField(default=True)
    source_template = models.ForeignKey(
        "library.Template", null=True, blank=True, on_delete=models.SET_NULL, related_name="programs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    objects = ProgramQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["athlete"], condition=Q(active=True), name="one_active_program_per_athlete"
            ),
        ]

    def __str__(self):
        return f"{self.athlete}: {self.name}"


class ProgramWeek(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="weeks")
    order = models.PositiveSmallIntegerField()
    week_type = models.ForeignKey(WeekType, on_delete=models.PROTECT, related_name="program_weeks")
    start_date = models.DateField()
    focus_note = models.TextField(blank=True)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            # Deferred, so shifting every later week's order in one transaction is allowed.
            models.UniqueConstraint(
                fields=["program", "order"],
                name="unique_week_order_per_program",
                deferrable=Deferrable.DEFERRED,
            ),
        ]

    def __str__(self):
        return f"{self.program} · {self.label}"

    @property
    def label(self):
        return f"Wk {self.order + 1}"

    @property
    def end_date(self):
        return self.start_date + datetime.timedelta(days=6)


class ProgramDay(models.Model):
    """Seven per week. Rest is not stored: a day with no sessions is a rest day."""

    week = models.ForeignKey(ProgramWeek, on_delete=models.CASCADE, related_name="days")
    date = models.DateField()

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["week", "date"], name="unique_day_per_week", deferrable=Deferrable.DEFERRED
            ),
        ]

    def __str__(self):
        return str(self.date)


class ProgramSession(models.Model):
    """Usually one per day; a second covers morning and evening training."""

    day = models.ForeignKey(ProgramDay, on_delete=models.CASCADE, related_name="sessions")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name or f"Session on {self.day.date}"


class Prescription(PrescriptionBase):
    session = models.ForeignKey(ProgramSession, on_delete=models.CASCADE, related_name="prescriptions")
    order = models.PositiveSmallIntegerField(default=0)
    exercise = models.ForeignKey("exercises.Exercise", on_delete=models.PROTECT, related_name="prescriptions")
    tag_slot_tags = models.ManyToManyField("exercises.Tag", blank=True, related_name="+")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise} {self.sets}×{self.rep_scheme}"


class PrescribedSet(PrescribedSetBase):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="set_overrides")

    class Meta(PrescribedSetBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["prescription", "set_number"], name="unique_set_per_prescription"
            ),
        ]

    def __str__(self):
        return f"Set {self.set_number} of {self.prescription}"
