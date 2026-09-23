# Included inside the coach namespace (apps/dashboard/urls.py).
from django.urls import path

from . import organise_views as org
from . import views

urlpatterns = [
    path("programming/exercises/", views.exercise_list, name="exercises"),
    path("programming/exercises/new/", views.exercise_form, name="exercise_new"),
    path("programming/exercises/<int:pk>/edit/", views.exercise_form, name="exercise_edit"),
    path("programming/exercises/<int:pk>/archive/", views.exercise_archive, name="exercise_archive"),
    path("programming/exercises/<int:pk>/restore/", views.exercise_restore, name="exercise_restore"),
    path("programming/exercises/<int:pk>/delete/", views.exercise_delete, name="exercise_delete"),
    path("programming/exercises/organise/", org.page, name="organise"),
    path("programming/categories/add/", org.category_add, name="category_add"),
    path("programming/categories/<int:pk>/rename/", org.category_rename, name="category_rename"),
    path("programming/categories/<int:pk>/move/<str:direction>/", org.category_move, name="category_move"),
    path("programming/categories/<int:pk>/delete/", org.category_delete, name="category_delete"),
    path("programming/tags/add/", org.tag_add, name="tag_add"),
    path("programming/tags/<int:pk>/rename/", org.tag_rename, name="tag_rename"),
    path("programming/tags/<int:pk>/delete/", org.tag_delete, name="tag_delete"),
]
