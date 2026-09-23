import re

from django.core.exceptions import ValidationError
from django.db import models
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
