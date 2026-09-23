from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models


class Category(models.TextChoices):
    SNATCH = "snatch", "Snatch"
    CLEAN_JERK = "clean_jerk", "Clean & Jerk"
    SQUAT = "squat", "Squat"
    PULL = "pull", "Pull"
    PRESS = "press", "Press"
    ACCESSORY = "accessory", "Accessory"
    CONDITIONING = "conditioning", "Conditioning"
    MOBILITY = "mobility", "Mobility"


class Measure(models.TextChoices):
    REPS = "reps", "Reps"
    TIME = "time", "Time"
    DISTANCE = "distance", "Distance"


# The fixed tag list from the mockup. A Tag model only if coaches ask for custom tags.
TAGS = [
    "high-impact",
    "low-impact",
    "competition-lift",
    "technique",
    "speed",
    "strength",
    "hypertrophy",
    "overhead",
    "posterior-chain",
    "unilateral",
    "no-equipment",
    "high-CNS",
    "recovery",
]


def validate_tags(value):
    unknown = [t for t in value if t not in TAGS]
    if unknown:
        raise ValidationError(f"Unknown tags: {', '.join(unknown)}")


class Exercise(models.Model):
    """Model lands in phase 1 because MaxEntry points at it; the library CRUD is phase 2."""

    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="exercises")
    key = models.CharField(
        max_length=20,
        blank=True,
        help_text="Marks exercises that came from the starter library (e.g. 'sn'), so the "
        "library can be refreshed without duplicates. Blank for exercises a coach creates. "
        "Nothing else may depend on it: features use the gym's own settings, e.g. TrackedLift.",
    )
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices)
    tags = ArrayField(models.CharField(max_length=30), default=list, blank=True, validators=[validate_tags])
    measure = models.CharField(max_length=10, choices=Measure.choices, default=Measure.REPS)
    reps_per_rep = models.PositiveSmallIntegerField(default=1, help_text='2 for a "1+1" complex')
    percent_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The max percentages are worked from. Empty means this exercise's own max.",
    )
    youtube_url = models.URLField(blank=True)
    cue = models.TextField(blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["gym", "name"], name="unique_exercise_name_per_gym"),
            models.UniqueConstraint(
                fields=["gym", "key"], condition=~models.Q(key=""), name="unique_exercise_key_per_gym"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def max_source(self):
        """The exercise whose max a percentage load is taken from."""
        return self.percent_of or self


MAX_TRACKED_LIFTS = 6


class TrackedLift(models.Model):
    """The lifts a gym records maxes for: asked at onboarding, shown on the Metrics
    tab and in the athlete header. An ordered, gym-wide list the coach edits in
    Settings. Archiving the exercise removes it from the list; history is kept."""

    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="tracked_lifts")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="tracked_by")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["gym", "exercise"], name="unique_tracked_lift_per_gym"),
        ]

    def __str__(self):
        return f"{self.gym}: {self.exercise}"

    def clean(self):
        if self.exercise.gym_id != self.gym_id:
            raise ValidationError("A gym can only track its own exercises.")
        if self.exercise.archived:
            raise ValidationError("Archived exercises can't be tracked.")
        if self.exercise.measure != Measure.REPS:
            raise ValidationError("Only lifts measured in reps have a max to track.")


def tracked_exercises(gym):
    """The gym's tracked lifts, in order, as Exercise objects."""
    return [t.exercise for t in TrackedLift.objects.filter(gym=gym).select_related("exercise")]
