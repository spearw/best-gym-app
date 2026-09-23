from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def invite_url(request, invite):
    """The short /join/<token>/ link that goes in emails and the copy box."""
    return request.build_absolute_uri(f"/join/{invite.token}/")


def send_invite_email(request, invite):
    context = {
        "invite": invite,
        "coach": invite.coach,
        "gym": invite.coach.gym,
        "join_url": invite_url(request, invite),
    }
    subject = render_to_string("emails/invite_subject.txt", context).strip()
    body = render_to_string("emails/invite.txt", context)
    send_mail(subject, body, None, [invite.email])


def send_metrics_reminder(request, athlete, missing_keys):
    from .metrics import metric_specs

    labels = [m.label for m in metric_specs(athlete.gym) if m.key in missing_keys]
    context = {
        "athlete": athlete,
        "coach": athlete.coach,
        "labels": labels,
        "url": request.build_absolute_uri(reverse("app:numbers")),
    }
    subject = render_to_string("emails/metrics_reminder_subject.txt", context).strip()
    body = render_to_string("emails/metrics_reminder.txt", context)
    send_mail(subject, body, None, [athlete.user.email])
