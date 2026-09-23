from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Athlete, BodyweightEntry, Coach, Gym, Invite, MaxEntry, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "name", "timezone", "is_staff", "is_active"]
    search_fields = ["email", "name"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["name", "timezone"]}),
        ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "name", "password1", "password2"]}),
    ]


@admin.register(Gym)
class GymAdmin(admin.ModelAdmin):
    list_display = ["name", "units", "timezone", "created_at"]


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    list_display = ["user", "gym", "title"]
    list_select_related = ["user", "gym"]


class BodyweightInline(admin.TabularInline):
    model = BodyweightEntry
    extra = 0


class MaxInline(admin.TabularInline):
    model = MaxEntry
    extra = 0
    autocomplete_fields = ["exercise"]


@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ["user", "coach", "gym", "weight_class", "joined_at", "archived_at"]
    list_filter = ["gym", "archived_at"]
    list_select_related = ["user", "coach__user", "gym"]
    search_fields = ["user__email", "user__name"]
    inlines = [BodyweightInline, MaxInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["email", "coach", "status", "created_at", "expires_at", "accepted_by"]
    list_filter = ["status"]
    readonly_fields = ["token"]
