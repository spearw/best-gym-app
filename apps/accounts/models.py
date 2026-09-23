import datetime
import secrets
import zoneinfo

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_timezone(value):
    """Checked at validation time rather than baked into the migration as choices,
    because the available zone list depends on the machine's tzdata version."""
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"{value!r} is not a known time zone")


class Units(models.TextChoices):
    KG = "kg", "kilograms"
    LB = "lb", "pounds"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username):
        # Email login is case-insensitive.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractUser):
    """Login is by email. There is no role column: a Coach or Athlete profile row
    decides what a user is, and one user may have both.

    `timezone` is the person's own zone. For an athlete it is the zone "today" is
    worked out in; it defaults to the gym's zone when they join."""

    username = None
    first_name = None
    last_name = None
    email = models.EmailField("email address", unique=True)
    name = models.CharField(max_length=150, blank=True)
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_timezone])

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.name or self.email

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name.split(" ")[0] if self.name else self.email

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        if not parts:
            return self.email[:2].upper()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @property
    def coach_profile(self):
        return getattr(self, "coach", None) if self.pk else None

    @property
    def athlete_profile(self):
        athlete = getattr(self, "athlete", None) if self.pk else None
        return athlete if athlete and athlete.archived_at is None else None

    @property
    def zoneinfo(self):
        return zoneinfo.ZoneInfo(self.timezone)

    def today(self):
        """The date in this person's own time zone."""
        return timezone.localdate(timezone=self.zoneinfo)


class WeekStart(models.IntegerChoices):
    MONDAY = 0, "Monday"
    SUNDAY = 6, "Sunday"


class Gym(models.Model):
    """Owns the exercise library, templates and default check-in questions.
    Coaches at one gym share them; a solo coach is a gym of one."""

    name = models.CharField(max_length=120)
    units = models.CharField(max_length=2, choices=Units.choices, default=Units.KG)
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_timezone])
    week_start = models.PositiveSmallIntegerField(
        choices=WeekStart.choices,
        default=WeekStart.MONDAY,
        help_text="The day training weeks start on (Python weekday: 0 = Monday, 6 = Sunday).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def today(self):
        """The date in the gym's zone; the coach dashboard counts days in this."""
        return timezone.localdate(timezone=zoneinfo.ZoneInfo(self.timezone))

    def week_start_for(self, day):
        """The first day of the training week containing `day`."""
        return day - datetime.timedelta(days=(day.weekday() - self.week_start) % 7)


class Coach(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach")
    gym = models.ForeignKey(Gym, on_delete=models.PROTECT, related_name="coaches")
    title = models.CharField(max_length=60, default="Head coach", blank=True)

    def __str__(self):
        return str(self.user)


class YearsTraining(models.TextChoices):
    UNDER_1 = "<1", "< 1"
    ONE_TO_3 = "1-3", "1–3"
    THREE_TO_5 = "3-5", "3–5"
    OVER_5 = "5+", "5+"


class MaxUpdates(models.TextChoices):
    APPROVE = "approve", "Coach approves"
    AUTO = "auto", "Automatically"


class Athlete(models.Model):
    """Archive, never delete, so session history survives.
    Bodyweight and maxes are history tables (BodyweightEntry, MaxEntry)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="athlete")
    coach = models.ForeignKey(Coach, on_delete=models.PROTECT, related_name="athletes")
    gym = models.ForeignKey(Gym, on_delete=models.PROTECT, related_name="athletes")
    weight_class = models.CharField(max_length=20, blank=True)
    competition_name = models.CharField(max_length=120, blank=True)
    competition_date = models.DateField(null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    years_training = models.CharField(max_length=4, choices=YearsTraining.choices, blank=True)
    units = models.CharField(max_length=2, choices=Units.choices, default=Units.KG)
    max_updates = models.CharField(
        max_length=8,
        choices=MaxUpdates.choices,
        default=MaxUpdates.APPROVE,
        help_text="When a session beats a working max: update it straight away, or wait for the coach.",
    )
    joined_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__name"]

    def __str__(self):
        return str(self.user)

    @property
    def timezone(self):
        return self.user.timezone

    def today(self):
        return self.user.today()

    def current_bodyweight(self):
        return self.bodyweights.order_by("-date", "-id").first()

    def current_max(self, exercise):
        """Latest MaxEntry for this exercise: the working max percentages come from."""
        return self.maxes.filter(exercise=exercise).order_by("-date", "-id").first()

    def current_maxes(self):
        """Latest MaxEntry per exercise, as {exercise_id: MaxEntry}."""
        latest = {}
        for entry in self.maxes.select_related("exercise").order_by("exercise_id", "-date", "-id"):
            latest.setdefault(entry.exercise_id, entry)
        return latest


class MeasurementSource(models.TextChoices):
    ONBOARDING = "onboarding", "Onboarding"
    ATHLETE = "athlete", "Athlete"
    COACH = "coach", "Coach"
    SESSION = "session", "Session"


class BodyweightEntry(models.Model):
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name="bodyweights")
    date = models.DateField()
    kg = models.DecimalField(max_digits=5, decimal_places=2)
    source = models.CharField(max_length=12, choices=MeasurementSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "bodyweight entries"
        constraints = [models.CheckConstraint(condition=models.Q(kg__gt=0), name="bodyweight_positive")]

    def __str__(self):
        return f"{self.athlete} {self.kg} kg on {self.date}"


class MaxEntry(models.Model):
    """The latest row per exercise is the working max. A session PR adds a row rather
    than overwriting. "Not provided" means no row at all."""

    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name="maxes")
    exercise = models.ForeignKey("exercises.Exercise", on_delete=models.PROTECT, related_name="max_entries")
    date = models.DateField()
    kg = models.DecimalField(max_digits=6, decimal_places=2)
    reps = models.PositiveSmallIntegerField(default=1)
    source = models.CharField(max_length=12, choices=MeasurementSource.choices)
    # The logged set this max came from, when a session set it (apps/workouts/prs.py).
    set_log = models.ForeignKey(
        "workouts.SetLog", null=True, blank=True, on_delete=models.CASCADE, related_name="max_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "max entries"
        constraints = [models.CheckConstraint(condition=models.Q(kg__gt=0), name="max_positive")]

    def __str__(self):
        return f"{self.athlete} {self.exercise} {self.kg} kg × {self.reps} on {self.date}"


def default_invite_expiry():
    return timezone.now() + datetime.timedelta(days=14)


def new_invite_token():
    return secrets.token_urlsafe(18)


class InviteStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"


class Invite(models.Model):
    """One invite = one athlete. `starting_template` is added in phase 5 with templates."""

    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField(blank=True)
    token = models.CharField(max_length=40, unique=True, default=new_invite_token, editable=False)
    status = models.CharField(max_length=10, choices=InviteStatus.choices, default=InviteStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_invite_expiry)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.email or '(link)'} from {self.coach}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self):
        return self.status == InviteStatus.PENDING and not self.is_expired

    @property
    def gym(self):
        return self.coach.gym
