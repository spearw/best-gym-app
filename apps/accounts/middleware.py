import zoneinfo

from django.utils import timezone


class UserTimezoneMiddleware:
    """Show dates and times in the signed-in person's own zone. Storage stays UTC."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            try:
                timezone.activate(zoneinfo.ZoneInfo(user.timezone))
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                timezone.deactivate()
        else:
            timezone.deactivate()
        return self.get_response(request)
