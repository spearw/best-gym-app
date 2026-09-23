import pytest
from django.core.management import call_command

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_logs_in_by_email_and_has_no_username():
    user = User.objects.create_user("Coach@IronRidge.Example", "pw-123456", name="Dana Whitfield")
    assert user.email == "Coach@ironridge.example"  # domain is normalised
    assert not hasattr(User, "username") or User.username is None
    assert User.USERNAME_FIELD == "email"
    assert user.check_password("pw-123456")
    assert not user.is_staff and not user.is_superuser
    assert user.timezone == "UTC"


def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser("admin@example.com", "pw-123456")
    assert admin.is_staff and admin.is_superuser


def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user("", "pw")


@pytest.mark.parametrize(
    "name,email,expected",
    [("Dana Whitfield", "d@x.com", "DW"), ("Maya", "m@x.com", "M"), ("", "theo@x.com", "TH")],
)
def test_initials(name, email, expected):
    assert User(name=name, email=email).initials == expected


def test_seed_demo_is_idempotent():
    call_command("seed_demo")
    call_command("seed_demo")
    assert User.objects.count() == 7
    dana = User.objects.get(email="dana@ironridge.example")
    assert dana.name == "Dana Whitfield" and dana.is_staff
    assert dana.check_password("demo-password-123")
