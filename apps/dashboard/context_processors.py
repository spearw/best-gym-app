"""Pick the full page or just the swapped region for the two shells.

A boosted link inside a shell sends HX-Target (coach-main or app-body). The page
template extends base_coach.html / base_app.html as usual; those extend the frame
chosen here, so one page template serves both the full load and the HTMX swap.
"""


def shell_frames(request):
    target = (
        getattr(getattr(request, "htmx", None), "target", None) if getattr(request, "htmx", False) else None
    )
    return {
        "coach_frame": "frames/coach_main.html" if target == "coach-main" else "frames/coach_full.html",
        "app_frame": "frames/app_body.html" if target == "app-body" else "frames/app_full.html",
    }


def coach_alerts(request):
    """The sidebar's unread count, evaluated only when a coach page shows it."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    def alert_count():
        from .alerts import unread_count

        return unread_count(user)

    def unread_messages():
        from apps.messaging.views import unread_for_athlete

        return unread_for_athlete(user)

    return {"alert_count": alert_count, "unread_messages": unread_messages}
