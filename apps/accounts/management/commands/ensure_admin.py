"""Create or update the site admin from ADMIN_EMAIL and ADMIN_PASSWORD, for hosts with no
shell (Render's free tier): it runs at start-up. Without both settings it does nothing.
Changing ADMIN_PASSWORD in the dashboard changes the password at the next start."""

import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User

MIN_LENGTH = 12


class Command(BaseCommand):
    help = "Create or update the admin account from ADMIN_EMAIL / ADMIN_PASSWORD."

    def handle(self, *args, **options):
        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not email or not password:
            self.stdout.write("ensure_admin: ADMIN_EMAIL / ADMIN_PASSWORD not set; skipped.")
            return
        if len(password) < MIN_LENGTH:
            # Don't stop the site starting over it; just refuse to use a weak password.
            self.stderr.write(
                f"ensure_admin: ADMIN_PASSWORD needs at least {MIN_LENGTH} characters; skipped."
            )
            return
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email, password, name="Admin")
        else:
            user.set_password(password)
        user.is_staff = user.is_superuser = True
        user.save()
        self.stdout.write(f"ensure_admin: {email} is an admin.")
