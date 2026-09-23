# Included inside the coach namespace (apps/dashboard/urls.py).
from django.urls import path

from . import views

urlpatterns = [
    path("programming/exercises/", views.exercise_list, name="exercises"),
    path("programming/exercises/new/", views.exercise_form, name="exercise_new"),
    path("programming/exercises/<int:pk>/edit/", views.exercise_form, name="exercise_edit"),
    path("programming/exercises/<int:pk>/archive/", views.exercise_archive, name="exercise_archive"),
    path("programming/exercises/<int:pk>/restore/", views.exercise_restore, name="exercise_restore"),
    path("programming/exercises/<int:pk>/delete/", views.exercise_delete, name="exercise_delete"),
]
