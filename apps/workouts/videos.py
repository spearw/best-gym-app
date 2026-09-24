"""Form-video storage: an S3-compatible bucket (Cloudflare R2 in production, MinIO locally).

Django never handles the video bytes. The athlete's browser asks for a signed PUT URL
(`upload_url`), sends the file straight to the bucket, then tells the server it's done;
`confirm` checks the object really arrived at the size that was signed for. The coach
plays it from a short-lived signed GET URL (`view_url`). Settings: FORM_VIDEOS.
"""

import uuid

from django.conf import settings

UPLOAD_SECONDS = 15 * 60
VIEW_SECONDS = 60 * 60


def config():
    return settings.FORM_VIDEOS


def enabled():
    c = config()
    return bool(c["endpoint"] and c["bucket"] and c["access_key"] and c["secret"])


def client():
    import boto3
    from botocore.config import Config

    c = config()
    return boto3.client(
        "s3",
        endpoint_url=c["endpoint"],
        aws_access_key_id=c["access_key"],
        aws_secret_access_key=c["secret"],
        region_name=c["region"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def new_key(athlete, content_type):
    ext = {"video/quicktime": "mov", "video/webm": "webm"}.get(content_type, "mp4")
    return f"form-videos/{athlete.gym_id}/{athlete.pk}/{uuid.uuid4().hex}.{ext}"


def upload_url(key, size, content_type):
    """A signed PUT for exactly `size` bytes of `content_type`: the browser can't send more."""
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": config()["bucket"], "Key": key, "ContentType": content_type, "ContentLength": size},
        ExpiresIn=UPLOAD_SECONDS,
    )


def view_url(key):
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": config()["bucket"], "Key": key}, ExpiresIn=VIEW_SECONDS
    )


def stored_size(key):
    """The object's size in bytes, or None if it isn't there."""
    from botocore.exceptions import ClientError

    try:
        return client().head_object(Bucket=config()["bucket"], Key=key)["ContentLength"]
    except ClientError:
        return None


def delete(key):
    client().delete_object(Bucket=config()["bucket"], Key=key)


def expire(now=None):
    """Delete files past FORM_VIDEOS["keep_days"] (the row stays, marked deleted) and
    uploads started a day ago that never finished. Returns (expired, abandoned)."""
    import datetime

    from django.utils import timezone

    from .models import FormVideo

    if not enabled():
        return 0, 0
    now = now or timezone.now()
    old = FormVideo.objects.available().filter(
        uploaded_at__lt=now - datetime.timedelta(days=config()["keep_days"])
    )
    expired = 0
    for video in old:
        delete(video.key)
        video.deleted_at = now
        video.save(update_fields=["deleted_at"])
        expired += 1
    abandoned = FormVideo.objects.filter(
        uploaded_at__isnull=True, created_at__lt=now - datetime.timedelta(days=1)
    )
    count = 0
    for video in abandoned:
        delete(video.key)  # deleting a missing object is fine
        video.delete()
        count += 1
    return expired, count
