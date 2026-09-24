"""Coach–athlete messages: one thread per coach and athlete, so a new coach starts a
fresh thread and never sees the previous coach's conversation."""

from django.conf import settings
from django.db import models


class Thread(models.Model):
    coach = models.ForeignKey("accounts.Coach", on_delete=models.CASCADE, related_name="threads")
    athlete = models.ForeignKey("accounts.Athlete", on_delete=models.CASCADE, related_name="threads")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["coach", "athlete"], name="one_thread_per_pair")]

    def __str__(self):
        return f"{self.coach} ↔ {self.athlete}"

    @classmethod
    def for_athlete(cls, athlete):
        """The thread with the athlete's current coach (created on first use)."""
        return cls.objects.get_or_create(coach=athlete.coach, athlete=athlete)[0]

    def unread_for(self, user):
        return self.messages.filter(read_at__isnull=True).exclude(sender=user)


class Message(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    body = models.TextField(max_length=4000)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sent_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40]}"
