"""Create the form-video bucket if it's missing and allow browsers on the site to upload
to it (CORS). Run once per environment: `make db` runs it locally; for Cloudflare R2 run
it once with the production STORAGE_* settings (or set the same CORS rule in R2's dashboard)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.workouts import videos


class Command(BaseCommand):
    help = "Create the form-video bucket and its CORS rule."

    def add_arguments(self, parser):
        parser.add_argument(
            "--origin",
            action="append",
            help="A site origin allowed to upload, e.g. https://gymtrainer.onrender.com (repeatable). "
            "Default: http://localhost:8000 plus CSRF_TRUSTED_ORIGINS.",
        )

    def handle(self, *args, **options):
        if not videos.enabled():
            raise CommandError("No STORAGE_* settings: form videos are off.")
        s3, bucket = videos.client(), videos.config()["bucket"]
        existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
            self.stdout.write(f"created bucket {bucket}")
        origins = options["origin"] or [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            *settings.CSRF_TRUSTED_ORIGINS,
        ]
        try:
            s3.put_bucket_cors(
                Bucket=bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": origins,
                            "AllowedMethods": ["PUT", "GET", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
            self.stdout.write(f"CORS allows uploads from: {', '.join(origins)}")
        except Exception as err:  # MinIO allows every origin and has no bucket CORS API
            self.stdout.write(
                f"CORS not set ({type(err).__name__}); fine for MinIO, set it in R2's dashboard"
            )
        self.stdout.write(self.style.SUCCESS(f"form videos ready in {bucket}"))
