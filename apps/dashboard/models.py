"""Alerts for the coach's "Needs your attention" feed.

One row per thing needing attention, unique on (recipient, kind, dedupe_key), so an
alert fires once however often the checks run. Events (a message, an issue, a PR) add
their row straight away; conditions (a program running out, missing metrics, a missed
session) are synced by apps/dashboard/alerts.py whenever the dashboard loads and by
the nightly job, and their row is deleted once the condition goes away.

`read_at`: dismissed with ✓ (still listed, dimmed). `cleared_at`: gone from the feed,
because it was handled (thread read, PR decided, issue resolved, weeks added…) or the
coach pressed "Clear read".
"""

from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    ISSUE = "issue", "Issue reported"
    MESSAGE = "message", "Message"
    PR = "pr", "PR"
    PROGRAM_ENDING = "program_ending", "Program running out"
    METRICS_MISSING = "metrics_missing", "Missing metrics"
    MISSED = "missed", "Missed session"
    VIDEO = "video", "Form video"
    WEEK_PUBLISHED = "week_published", "Week published"


class NotificationQuerySet(models.QuerySet):
    def in_feed(self):
        return self.filter(cleared_at__isnull=True)

    def unread(self):
        return self.in_feed().filter(read_at__isnull=True)


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    athlete = models.ForeignKey(
        "accounts.Athlete", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=20, choices=NotificationKind.choices)
    dedupe_key = models.CharField(max_length=80)
    text = models.CharField(max_length=300)
    link = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "kind", "dedupe_key"], name="one_notification_per_key"
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.text}"


class BugReport(models.Model):
    """A bug report from the "Report a bug" button in the coach or athlete header. Read and
    triaged in the Django admin for now. The page, browser and screen size are captured
    automatically so the reporter only has to say what went wrong."""

    class Side(models.TextChoices):
        COACH = "coach", "Coach app"
        ATHLETE = "athlete", "Athlete app"

    class Status(models.TextChoices):
        NEW = "new", "New"
        SEEN = "seen", "Seen"
        FIXED = "fixed", "Fixed"
        WONT_FIX = "wontfix", "Won't fix"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    gym = models.ForeignKey(
        "accounts.Gym", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    side = models.CharField(max_length=10, choices=Side.choices)
    description = models.TextField()
    page = models.CharField(max_length=500, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    screen = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_side_display()}: {self.description[:60]}"
