from django.urls import include, path, re_path
from django.views.generic import RedirectView

from apps.accounts import coach_views
from apps.accounts import views as account_views
from apps.exercises import tracked_views
from apps.programs import views as week_type_views
from apps.workouts import question_views as qv

from . import views

app_name = "coach"


def question_patterns(prefix, name_prefix):
    """The builder endpoints, mounted once for gym defaults and once per athlete."""
    return [
        path(f"{prefix}add/<str:qtype>/", qv.add, name=f"{name_prefix}_add"),
        path(f"{prefix}<int:qid>/update/", qv.update, name=f"{name_prefix}_update"),
        path(f"{prefix}<int:qid>/archive/", qv.archive, name=f"{name_prefix}_archive"),
        path(f"{prefix}<int:qid>/move/<str:direction>/", qv.move, name=f"{name_prefix}_move"),
        path(f"{prefix}<int:qid>/options/add/", qv.add_option, name=f"{name_prefix}_option_add"),
        path(
            f"{prefix}<int:qid>/options/<int:index>/remove/",
            qv.remove_option,
            name=f"{name_prefix}_option_remove",
        ),
    ]


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Athletes: roster, detail tabs, metrics, per-athlete check-in questions.
    path("athletes/", coach_views.roster, name="athletes"),
    path("athletes/<int:pk>/", coach_views.athlete_detail, name="athlete"),
    re_path(
        r"^athletes/(?P<pk>\d+)/(?P<tab>overview|program|sessions|metrics|messages)/$",
        coach_views.athlete_detail,
        name="athlete_tab",
    ),
    path("athletes/<int:pk>/metrics/<str:key>/edit/", coach_views.metric_edit, name="metric_edit"),
    path("athletes/<int:pk>/remind/", coach_views.remind_metrics, name="remind_metrics"),
    path("athletes/<int:athlete_pk>/questions/", qv.builder, name="athlete_questions"),
    path("athletes/<int:athlete_pk>/questions/reset/", qv.reset_to_defaults, name="athlete_questions_reset"),
    *question_patterns("athletes/<int:athlete_pk>/questions/", "athlete_q"),
    # Programming: templates/weeks/sessions (phase 5), exercises, default questions.
    path("programming/", RedirectView.as_view(pattern_name="coach:exercises"), name="programming"),
    path(
        "programming/templates/",
        views.programming_placeholder,
        {"ptab": "templates"},
        name="programming_templates",
    ),
    path("programming/weeks/", views.programming_placeholder, {"ptab": "weeks"}, name="programming_weeks"),
    path(
        "programming/sessions/",
        views.programming_placeholder,
        {"ptab": "sessions"},
        name="programming_sessions",
    ),
    path("", include("apps.exercises.urls")),
    path("programming/questions/", qv.defaults_page, name="questions"),
    path("programming/questions/push/", qv.push_defaults, name="questions_push"),
    *question_patterns("programming/questions/", "default_q"),
    # Settings and invites.
    path("settings/", account_views.settings_page, name="settings"),
    path("settings/lifts/", tracked_views.card, name="tracked"),
    path("settings/week-types/add/", week_type_views.add, name="week_type_add"),
    path("settings/week-types/<int:pk>/update/", week_type_views.update, name="week_type_update"),
    path("settings/week-types/<int:pk>/move/<str:direction>/", week_type_views.move, name="week_type_move"),
    path("settings/week-types/<int:pk>/remove/", week_type_views.remove, name="week_type_remove"),
    path("settings/week-types/<int:pk>/restore/", week_type_views.restore, name="week_type_restore"),
    path("settings/lifts/add/", tracked_views.add, name="tracked_add"),
    path("settings/lifts/<int:pk>/remove/", tracked_views.remove, name="tracked_remove"),
    path("settings/lifts/<int:pk>/move/<str:direction>/", tracked_views.move, name="tracked_move"),
    path("invites/new/", account_views.invite_new, name="invite_new"),
    path("invites/", account_views.invite_create, name="invite_create"),
    path("invites/pending/", account_views.invite_list, name="invite_list"),
    path("invites/<int:pk>/revoke/", account_views.invite_revoke, name="invite_revoke"),
    path("ping/", views.ping, name="ping"),
]
