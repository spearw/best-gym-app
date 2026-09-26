from django.contrib import admin
from django.utils.html import format_html

from .models import BugReport


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    """Bug reports from the header button, newest first. Set the status as you triage."""

    list_display = ["created_at", "status", "side", "short_description", "user", "gym", "screen"]
    list_filter = ["status", "side", "gym"]
    list_editable = ["status"]
    search_fields = ["description", "page", "user__email", "user__name"]
    readonly_fields = [
        "created_at",
        "user",
        "gym",
        "side",
        "description",
        "page_link",
        "user_agent",
        "screen",
    ]
    fields = [*readonly_fields, "status", "admin_note"]
    date_hierarchy = "created_at"

    @admin.display(description="Description")
    def short_description(self, obj):
        return obj.description[:80] + ("…" if len(obj.description) > 80 else "")

    @admin.display(description="Page")
    def page_link(self, obj):
        # The page comes from the reporter's browser: only http(s) addresses become links
        # (never javascript: and the like); anything else is shown as text.
        if obj.page.startswith(("http://", "https://")):
            return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.page, obj.page)
        return obj.page

    def has_add_permission(self, request):
        return False  # reports come from the button
