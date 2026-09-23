from django.contrib import admin

from .models import Exercise


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ["name", "gym", "category", "key", "percent_of", "archived"]
    list_filter = ["gym", "category", "archived"]
    search_fields = ["name", "key"]
