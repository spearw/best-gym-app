from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps import hx
from apps.exercises.models import MAX_TRACKED_LIFTS, TrackedLift
from apps.exercises.starter import install_pack
from apps.exercises.tracked_views import trackable
from apps.programs.views import card_context as week_type_card_context
from apps.ratelimit import by_ip, by_user, client_ip, hit, rate_limit, too_many
from apps.workouts.models import copy_defaults_to, install_default_questions

from .access import athlete_required, coach_required, home_url_for
from .emails import invite_url, send_invite_email
from .forms import (
    CoachSignupForm,
    GymSettingsForm,
    InviteForm,
    JoinForm,
    MetricsForm,
    clean_browser_timezone,
)
from .metrics import missing_metrics, save_metrics
from .models import (
    Athlete,
    Coach,
    Gym,
    Invite,
    InviteStatus,
    MeasurementSource,
    User,
)


def login_allowed(request):
    """Sign-in attempts in 15 minutes: 10 per address and email, 50 per address (trying
    many accounts), 30 per email from anywhere (many addresses on one account). Every
    bucket counts the attempt, so none can be skipped."""
    email = request.POST.get("username", "").strip().lower()
    ip = client_ip(request)
    window = 15 * 60
    checks = [
        hit("login", f"{ip}:{email}", 10, window),
        hit("login-ip", ip, 50, window),
        hit("login-email", email, 30, window),
    ]
    return all(checks)


def admin_login(request, extra_context=None):
    """Django admin's sign-in page, under the same limits as the site's."""
    from django.contrib import admin

    if request.method == "POST" and not login_allowed(request):
        return too_many(request, "Too many sign-in attempts. Wait 15 minutes.")
    return admin.site.login(request, extra_context)


class RateLimitedLoginView(auth_views.LoginView):
    """Sign-in, limited by login_allowed()."""

    def post(self, request, *args, **kwargs):
        if not login_allowed(request):
            form = self.get_form()
            form.is_valid()  # bind it so the page shows what was typed
            form.errors.clear()
            form.add_error(None, "Too many sign-in attempts. Wait 15 minutes, or reset your password.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)


def index(request):
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    return redirect("accounts:login")


@login_required
def no_profile(request):
    if request.user.coach_profile or request.user.athlete_profile:
        return redirect(home_url_for(request.user))
    return TemplateResponse(request, "accounts/no_profile.html")


# ---------------------------------------------------------------- coach sign-up


@rate_limit("signup", 10, 60 * 60, key=by_ip)
def signup(request):
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    form = CoachSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        tz = clean_browser_timezone(data["browser_timezone"], "UTC")
        with transaction.atomic():
            gym = Gym.objects.create(name=data["gym_name"], units=data["units"], timezone=tz)
            install_pack(gym, data["starter"])
            install_default_questions(gym)
            user = User.objects.create_user(data["email"], data["password"], name=data["name"], timezone=tz)
            Coach.objects.create(user=user, gym=gym)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Welcome to Platform, {user.get_short_name()}")
        return redirect("coach:dashboard")
    return TemplateResponse(request, "accounts/signup.html", {"form": form})


# ---------------------------------------------------------------- invites (coach side)


@coach_required
def invite_new(request):
    return TemplateResponse(
        request, "partials/invite_modal.html", {"form": InviteForm(gym=request.coach.gym)}
    )


@coach_required
@require_POST
@rate_limit("invite", 30, 60 * 60, key=by_user)
def invite_create(request):
    form = InviteForm(request.POST, gym=request.coach.gym)
    if not form.is_valid():
        return TemplateResponse(request, "partials/invite_modal.html", {"form": form})
    email = form.cleaned_data["email"]
    invite = Invite.objects.create(
        coach=request.coach, email=email, starting_template=form.cleaned_data["starting_template"]
    )
    join_url = invite_url(request, invite)
    if email:
        send_invite_email(request, invite)
        toast = f"Invite sent to {email}"
    else:
        toast = "Invite link created — share it with your athlete"
    response = TemplateResponse(
        request, "partials/invite_modal.html", {"invite": invite, "join_url": join_url, "sent": bool(email)}
    )
    return hx.trigger(response, toast={"message": toast, "kind": "good"}, invitesChanged=True)


@coach_required
def invite_list(request):
    return TemplateResponse(request, "partials/invite_list.html", _invite_list_context(request))


def _invite_list_context(request):
    pending = [i for i in request.coach.invites.filter(status=InviteStatus.PENDING) if not i.is_expired]
    return {"pending_invites": [(i, invite_url(request, i)) for i in pending]}


@coach_required
@require_POST
def invite_revoke(request, pk):
    invite = get_object_or_404(Invite, pk=pk, coach=request.coach, status=InviteStatus.PENDING)
    invite.status = InviteStatus.REVOKED
    invite.save(update_fields=["status"])
    response = TemplateResponse(request, "partials/invite_list.html", _invite_list_context(request))
    return hx.toast(response, "Invite revoked")


# ---------------------------------------------------------------- joining (athlete side)


@rate_limit("join", 10, 60 * 60, key=by_ip)
def join(request, token):
    invite = Invite.objects.select_related("coach__user", "coach__gym").filter(token=token).first()
    if invite is None or not invite.is_usable:
        return TemplateResponse(request, "accounts/join_invalid.html", {"invite": invite}, status=410)

    user = request.user if request.user.is_authenticated else None
    if user and user.athlete_profile:
        messages.warning(request, "You already have an athlete account.")
        return redirect("app:home")
    if user and hasattr(user, "athlete"):  # an archived athlete profile: one per account
        messages.error(
            request,
            "This account's athlete profile was archived by a coach. Ask them to restore it, "
            "or sign out and join with a different email.",
        )
        return redirect("accounts:no_profile")

    form = None if user else JoinForm(request.POST or None, invite_email=invite.email)
    if request.method == "POST" and (user or form.is_valid()):
        with transaction.atomic():
            invite = Invite.objects.select_for_update().get(pk=invite.pk)
            if not invite.is_usable:
                return TemplateResponse(request, "accounts/join_invalid.html", {"invite": invite}, status=410)
            if user is None:
                data = form.cleaned_data
                tz = clean_browser_timezone(data["browser_timezone"], invite.gym.timezone)
                user = User.objects.create_user(
                    data["email"], data["password"], name=data["name"], timezone=tz
                )
            athlete = Athlete.objects.create(
                user=user, coach=invite.coach, gym=invite.gym, units=invite.gym.units
            )
            copy_defaults_to(athlete)
            if invite.starting_template_id:
                _apply_starting_template(invite, athlete)
            invite.status = InviteStatus.ACCEPTED
            invite.accepted_by = user
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["status", "accepted_by", "accepted_at"])
        if not request.user.is_authenticated:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("app:welcome_metrics")

    return TemplateResponse(request, "accounts/join.html", {"invite": invite, "form": form, "step": 1})


def _apply_starting_template(invite, athlete):
    """The invite's template becomes an unpublished draft program from next week, on the
    template's default training days, for the coach to review and publish."""
    from apps.library import apply

    template = invite.starting_template
    try:
        apply.confirm(
            athlete,
            template,
            apply.default_days(template),
            apply.RECENT,
            "new:next",
            False,
            invite.coach.user,
        )
    except apply.CannotApply:
        pass  # an empty template: the coach builds the program by hand


@athlete_required
def welcome_metrics(request):
    athlete = request.athlete
    form = MetricsForm(request.POST or None, gym=athlete.gym, units=athlete.units)
    request.session["onboarding_total"] = len(form.fields)
    if request.method == "POST" and "skip_all" in request.POST:
        request.session["onboarding_skipped"] = len(form.fields)
        return redirect("app:welcome_done")
    if request.method == "POST" and form.is_valid():
        save_metrics(athlete, form.cleaned_data, source=MeasurementSource.ONBOARDING)
        request.session["onboarding_skipped"] = form.skipped_count()
        return redirect("app:welcome_done")
    return TemplateResponse(request, "accounts/welcome_metrics.html", {"form": form, "step": 2})


@athlete_required
def welcome_done(request):
    skipped = request.session.pop("onboarding_skipped", 0)
    total = request.session.pop("onboarding_total", 0)
    return TemplateResponse(
        request,
        "accounts/welcome_done.html",
        {"skipped": skipped, "all_skipped": bool(total) and skipped >= total, "step": 3},
    )


# ---------------------------------------------------------------- gym settings


@coach_required
def settings_page(request):
    gym = request.coach.gym
    initial = {
        "gym_name": gym.name,
        "coach_title": request.coach.title,
        "digest": request.coach.digest,
        "timezone": gym.timezone,
        "units": gym.units,
        "week_start": gym.week_start,
    }
    form = GymSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        gym.name = data["gym_name"]
        gym.timezone = data["timezone"]
        gym.units = data["units"]
        gym.week_start = data["week_start"]
        gym.full_clean()
        gym.save()
        request.coach.title = data["coach_title"]
        request.coach.digest = data["digest"]
        request.coach.save(update_fields=["title", "digest"])
        messages.success(request, "Settings saved")
        return redirect("coach:settings")
    return TemplateResponse(
        request,
        "coach/settings.html",
        {
            "panel": "settings",
            "title": "Settings",
            "form": form,
            **week_type_card_context(gym),
            "tracked": TrackedLift.objects.filter(gym=gym).select_related("exercise__category"),
            "trackable": trackable(gym),
            "max_tracked": MAX_TRACKED_LIFTS,
        },
    )


@athlete_required
def update_numbers(request):
    """Where the coach's reminder email points: fill in only the missing metrics."""
    athlete = request.athlete
    missing = missing_metrics(athlete)
    if not missing:
        messages.success(request, "All your numbers are in — nothing to add")
        return redirect("app:profile")
    form = MetricsForm(request.POST or None, gym=athlete.gym, units=athlete.units, only=missing)
    if request.method == "POST" and form.is_valid():
        filled = [k for k in missing if form.cleaned_data.get(k) not in (None, "")]
        save_metrics(athlete, form.cleaned_data, source=MeasurementSource.ATHLETE)
        coach = athlete.coach.user.get_short_name()
        if filled:
            messages.success(request, f"Thanks — {coach} can see your numbers")
        return redirect("app:profile")
    return TemplateResponse(
        request, "accounts/update_numbers.html", {"form": form, "tab": "profile", "title": "Your numbers"}
    )
