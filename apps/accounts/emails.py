from django.core.mail import send_mail
from django.template.loader import render_to_string


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
