from django.contrib import messages


def gym(request):
    """The current gym (coach's or athlete's), its week-type colour overrides as CSS
    variables, and any flash messages as toasts."""
    user = getattr(request, "user", None)
    current = None
    if user is not None and user.is_authenticated:
        profile = user.coach_profile or user.athlete_profile
        current = profile.gym if profile else None

    css_vars = ""
    if current and current.week_type_colours:
        parts = []
        for key, colour in current.week_type_colours.items():
            parts.append(f"--wk-{key}:{colour}")
            parts.append(f"--wk-{key}-lt:color-mix(in srgb, {colour} 16%, #fff)")
        css_vars = ";".join(parts)

    level_to_kind = {messages.SUCCESS: "good", messages.ERROR: "bad", messages.WARNING: "warn"}
    toasts = [
        {"message": str(m), "kind": level_to_kind.get(m.level, "")} for m in messages.get_messages(request)
    ]
    return {
        "current_gym": current,
        "gym_css_vars": css_vars,
        "initial_toasts": toasts,
    }
