from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Answers /healthz before host validation and the HTTPS redirect.

    Render's health probe comes from inside its network, over plain HTTP, with a
    Host header that is not in ALLOWED_HOSTS. Handling it first keeps a working
    deploy from being marked unhealthy. It still touches the database.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            except Exception:  # noqa: BLE001 - any DB failure means unhealthy
                return JsonResponse({"status": "database unavailable"}, status=503)
            return JsonResponse({"status": "ok"})
        return self.get_response(request)
