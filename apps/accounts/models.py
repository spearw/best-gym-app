import zoneinfo

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models


def validate_timezone(value):
    """Checked at validation time rather than baked into the migration as choices,
    because the available zone list depends on the machine's tzdata version."""
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"{value!r} is not a known time zone")


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


class User(AbstractUser):
    """Login is by email. There is no role column: a Coach or Athlete profile row
    (added in phase 1) decides what a user is, and one user may have both."""

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
