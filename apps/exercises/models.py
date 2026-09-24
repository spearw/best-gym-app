from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class Measure(models.TextChoices):
    REPS = "reps", "Reps"
    TIME = "time", "Time"
    DISTANCE = "distance", "Distance"


TAG_MAX_LENGTH = 24


class Category(models.Model):
    """A gym's own exercise categories (e.g. Snatch, Squat, Hinge). Ordered by the coach.
    Deleting one that has exercises moves them to another category first."""

    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=40)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(Lower("name"), "gym", name="unique_category_name_per_gym"),
        ]

    def __str__(self):
        return self.name


class Tag(models.Model):
    """A gym's own exercise tags, used to filter the library and for tag-based
    template slots. Names are at most TAG_MAX_LENGTH characters."""

    gym = models.ForeignKey("accounts.Gym", on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=TAG_MAX_LENGTH)

    class Meta:
        ordering = [Lower("name")]
        constraints = [
            models.UniqueConstraint(Lower("name"), "gym", name="unique_tag_name_per_gym"),
        ]

    def __str__(self):
        return self.name


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
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="exercises")
    tags = models.ManyToManyField(Tag, blank=True, related_name="exercises")
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
    warmup = models.BooleanField(
        default=False, help_text="A warm-up drill: added to sessions as part of the warm-up checklist."
    )
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

    def clean(self):
        if self.category_id and self.gym_id and self.category.gym_id != self.gym_id:
            raise ValidationError({"category": "Pick one of your gym's categories."})

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
