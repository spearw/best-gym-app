"""Who may see what. A user is a coach because they have a Coach row, an athlete
because they have an (unarchived) Athlete row. Every coach view uses coach_required
and reads data through request.coach; every athlete view uses athlete_required."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse


def home_url_for(user):
    """Where a signed-in user lands. The coach app wins when a user has both profiles."""
    if user.coach_profile:
        return reverse("coach:dashboard")
    if user.athlete_profile:
        return reverse("app:home")
    return reverse("accounts:no_profile")


def _required(profile_attr, request_attr):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            profile = getattr(request.user, profile_attr)
            if profile is None:
                # Signed in but the wrong kind of user: send them to their own app.
                return redirect(home_url_for(request.user))
            setattr(request, request_attr, profile)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


coach_required = _required("coach_profile", "coach")
athlete_required = _required("athlete_profile", "athlete")
