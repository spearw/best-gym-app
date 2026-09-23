from django.contrib import messages


def gym(request):
    """The current gym (coach's or athlete's) and any flash messages as toasts."""
    user = getattr(request, "user", None)
    current = None
    if user is not None and user.is_authenticated:
        profile = user.coach_profile or user.athlete_profile
        current = profile.gym if profile else None

    level_to_kind = {messages.SUCCESS: "good", messages.ERROR: "bad", messages.WARNING: "warn"}
    toasts = [
        {"message": str(m), "kind": level_to_kind.get(m.level, "")} for m in messages.get_messages(request)
    ]
    return {
        "current_gym": current,
        "initial_toasts": toasts,
    }
