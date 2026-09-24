"""{{ when|ago }}: the mockup's short times — "just now", "5m ago", "2h ago", "3d ago", "12 Sep"."""

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def ago(value):
    if not value:
        return ""
    seconds = (timezone.now() - value).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return timezone.localtime(value).strftime("%-d %b")
