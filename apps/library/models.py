"""Reusable programming, shared by a gym's coaches: whole program templates, saved
weeks and saved sessions. One Template model with a `kind` covers all three (a saved
week is a template with one week; a saved session is one week holding one session),
so the editor and the apply code are the same for each.

A slot is one exercise's dose in a session (every PrescriptionBase field, so applying
copies them exactly). A fixed slot names its exercise; a tag slot names tags plus a
default exercise, and is resolved per athlete when the template is applied.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.programs.models import PrescribedSetBase, PrescriptionBase


class TemplateKind(models.TextChoices):
    PROGRAM = "program", "Template"
    WEEK = "week", "Saved week"
    SESSION = "session", "Saved session"


class Template(models.Model):
    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="templates")
    kind = models.CharField(max_length=10, choices=TemplateKind.choices, default=TemplateKind.PROGRAM)
    name = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=200, blank=True)
    program_note = models.TextField(
        blank=True,
        help_text="Becomes the program note (goal, rest, nutrition) when applied as a new program.",
    )
    sessions_per_week = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(6)],
        help_text="Written for N sessions a week.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or f"Untitled {self.get_kind_display().lower().replace('saved ', '')}"


class TemplateWeek(models.Model):
    template = models.ForeignKey(Template, on_delete=models.CASCADE, related_name="weeks")
    order = models.PositiveSmallIntegerField(default=0)
    week_type = models.ForeignKey(
        "programs.WeekType", on_delete=models.PROTECT, related_name="template_weeks"
    )
    focus_note = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.template} · week {self.order + 1}"


class TemplateSession(models.Model):
    week = models.ForeignKey(TemplateWeek, on_delete=models.CASCADE, related_name="sessions")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name or "Session"


class SlotKind(models.TextChoices):
    EXERCISE = "exercise", "Fixed exercise"
    TAG = "tag", "Tag-based"


class TemplateSlot(PrescriptionBase):
    """`exercise` is the fixed exercise, or a tag slot's default."""

    session = models.ForeignKey(TemplateSession, on_delete=models.CASCADE, related_name="slots")
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=SlotKind.choices, default=SlotKind.EXERCISE)
    exercise = models.ForeignKey(
        "exercises.Exercise", on_delete=models.PROTECT, related_name="template_slots"
    )
    tags = models.ManyToManyField("exercises.Tag", blank=True, related_name="template_slots")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise} {self.sets}×{self.rep_scheme}"

    @property
    def is_tag(self):
        return self.kind == SlotKind.TAG


class TemplateSlotSet(PrescribedSetBase):
    slot = models.ForeignKey(TemplateSlot, on_delete=models.CASCADE, related_name="set_overrides")

    class Meta(PrescribedSetBase.Meta):
        constraints = [models.UniqueConstraint(fields=["slot", "set_number"], name="unique_set_per_slot")]


class Cadence(models.TextChoices):
    DAILY = "daily", "Every day"
    TRAINING = "training", "Training days"
    THREE = "3x", "3× a week"
    FIVE = "5x", "5× a week"


HABIT_EMOJI = ["🍎", "😴", "💧", "🧘", "🚶", "🥩", "🥗", "⚖️", "💪", "📓"]


class TemplateHabit(models.Model):
    """Prescribed to the athlete when the template is applied (athlete habits: phase 7)."""

    template = models.ForeignKey(Template, on_delete=models.CASCADE, related_name="habits")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=80)
    emoji = models.CharField(max_length=8, default="🍎")
    cadence = models.CharField(max_length=10, choices=Cadence.choices, default=Cadence.DAILY)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class TemplateApplication(models.Model):
    """One apply of a template (or saved week) to an athlete: the "used N×" count."""

    template = models.ForeignKey(Template, on_delete=models.CASCADE, related_name="applications")
    athlete = models.ForeignKey("accounts.Athlete", on_delete=models.CASCADE, related_name="+")
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    weeks = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-applied_at"]

    def __str__(self):
        return f"{self.template} → {self.athlete}"
