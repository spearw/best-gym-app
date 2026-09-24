from django.urls import include, path, re_path
from django.views.generic import RedirectView

from apps.accounts import coach_views
from apps.accounts import views as account_views
from apps.exercises import tracked_views
from apps.library import apply_views as av
from apps.library import views as lv
from apps.messaging import views as mv
from apps.programs import program_views as pv
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
    path("feed/", views.feed, name="feed"),
    path("feed/<int:pk>/read/", views.dismiss, name="feed_dismiss"),
    path("feed/clear/", views.clear_read, name="feed_clear"),
    path("athletes/<int:pk>/issues/<int:issue_id>/resolve/", views.resolve_issue, name="issue_resolve"),
    path("athletes/<int:pk>/messages/thread/", mv.coach_thread, name="message_thread"),
    path("athletes/<int:pk>/messages/send/", mv.coach_send, name="message_send"),
    # Athletes: roster, detail tabs, metrics, per-athlete check-in questions.
    path("athletes/", coach_views.roster, name="athletes"),
    path("athletes/<int:pk>/", coach_views.athlete_detail, name="athlete"),
    # Program editor (phase 3). Listed before the generic tab route so /program/ lands here.
    path("athletes/<int:pk>/program/", pv.program_tab, name="program"),
    path("athletes/<int:pk>/program/start/", pv.start, name="program_start"),
    path("athletes/<int:pk>/program/library/", pv.library, name="program_library"),
    path("athletes/<int:pk>/program/weeks/add/", pv.week_add, name="week_add"),
    path(
        "athletes/<int:pk>/program/weeks/<int:week_id>/duplicate/", pv.week_duplicate, name="week_duplicate"
    ),
    path("athletes/<int:pk>/program/weeks/<int:week_id>/delete/", pv.week_delete, name="week_delete"),
    path("athletes/<int:pk>/program/weeks/<int:week_id>/clear/", pv.week_clear, name="week_clear"),
    path("athletes/<int:pk>/program/weeks/<int:week_id>/publish/", pv.week_publish, name="week_publish"),
    path("athletes/<int:pk>/program/weeks/<int:week_id>/settings/", pv.week_settings, name="week_settings"),
    path("athletes/<int:pk>/program/add/", pv.day_add_exercise, name="day_add_exercise"),
    path(
        "athletes/<int:pk>/program/days/<int:day_id>/sessions/add/",
        pv.day_add_session,
        name="day_add_session",
    ),
    path(
        "athletes/<int:pk>/program/sessions/<int:session_id>/rename/",
        pv.session_rename,
        name="session_rename",
    ),
    path(
        "athletes/<int:pk>/program/sessions/<int:session_id>/delete/",
        pv.session_delete,
        name="session_delete",
    ),
    path("athletes/<int:pk>/program/rx/<int:rx_id>/", pv.rx_edit, name="rx_edit"),
    path("athletes/<int:pk>/program/rx/<int:rx_id>/remove/", pv.rx_remove, name="rx_remove"),
    path("athletes/<int:pk>/program/rx/<int:rx_id>/swap/", pv.rx_swap, name="rx_swap"),
    path("athletes/<int:pk>/program/rx/<int:rx_id>/move/", pv.rx_move, name="rx_move"),
    path("athletes/<int:pk>/program/apply/start/", av.apply_start, name="apply_start"),
    path("athletes/<int:pk>/program/apply/", av.apply_update, name="apply_update"),
    path("athletes/<int:pk>/program/apply/cancel/", av.apply_cancel, name="apply_cancel"),
    path("athletes/<int:pk>/program/apply/confirm/", av.apply_confirm, name="apply_confirm"),
    path("athletes/<int:pk>/program/weeks/<int:week_id>/save/", av.save_week, name="program_save_week"),
    path("athletes/<int:pk>/program/save/", av.save_program, name="program_save_template"),
    re_path(
        r"^athletes/(?P<pk>\d+)/(?P<tab>overview|program|sessions|metrics|messages)/$",
        coach_views.athlete_detail,
        name="athlete_tab",
    ),
    path("athletes/<int:pk>/metrics/<str:key>/edit/", coach_views.metric_edit, name="metric_edit"),
    path("athletes/<int:pk>/remind/", coach_views.remind_metrics, name="remind_metrics"),
    path("athletes/<int:pk>/max-updates/", coach_views.max_updates, name="max_updates"),
    path("athletes/<int:pk>/prs/<int:set_id>/", coach_views.pr_decide, name="pr_decide"),
    path("athletes/<int:athlete_pk>/questions/", qv.builder, name="athlete_questions"),
    path("athletes/<int:athlete_pk>/questions/reset/", qv.reset_to_defaults, name="athlete_questions_reset"),
    *question_patterns("athletes/<int:athlete_pk>/questions/", "athlete_q"),
    # Programming: templates/weeks/sessions (phase 5), exercises, default questions.
    path(
        "programming/",
        RedirectView.as_view(pattern_name="coach:programming_templates"),
        name="programming",
    ),
    path("programming/templates/", lv.library_page, {"ptab": "templates"}, name="programming_templates"),
    path("programming/weeks/", lv.library_page, {"ptab": "weeks"}, name="programming_weeks"),
    path("programming/sessions/", lv.library_page, {"ptab": "sessions"}, name="programming_sessions"),
    re_path(r"^programming/(?P<ptab>templates|weeks|sessions)/new/$", lv.new, name="template_new"),
    path("programming/apply/", av.apply_modal, name="apply_modal"),
    path("library/<int:pk>/", lv.edit, name="template_edit"),
    path("library/<int:pk>/library/", lv.library, name="template_library"),
    path("library/<int:pk>/meta/", lv.meta, name="template_meta"),
    path("library/<int:pk>/delete/", lv.delete, name="template_delete"),
    path("library/<int:pk>/weeks/add/", lv.week_add, name="template_week_add"),
    path("library/<int:pk>/weeks/<int:week_id>/type/", lv.week_type, name="template_week_type"),
    path(
        "library/<int:pk>/weeks/<int:week_id>/duplicate/", lv.week_duplicate, name="template_week_duplicate"
    ),
    path("library/<int:pk>/weeks/<int:week_id>/remove/", lv.week_remove, name="template_week_remove"),
    path("library/<int:pk>/weeks/<int:week_id>/sessions/add/", lv.session_add, name="template_session_add"),
    path(
        "library/<int:pk>/sessions/<int:session_id>/rename/",
        lv.session_rename,
        name="template_session_rename",
    ),
    path(
        "library/<int:pk>/sessions/<int:session_id>/remove/",
        lv.session_remove,
        name="template_session_remove",
    ),
    path("library/<int:pk>/slots/add/", lv.slot_add, name="template_add_slot"),
    path("library/<int:pk>/slots/add-tag/", lv.tag_slot_add, name="template_add_tag_slot"),
    path("library/<int:pk>/slots/<int:slot_id>/", lv.slot_edit, name="template_slot_edit"),
    path("library/<int:pk>/slots/<int:slot_id>/move/", lv.slot_move, name="template_slot_move"),
    path("library/<int:pk>/slots/<int:slot_id>/remove/", lv.slot_remove, name="template_slot_remove"),
    path("library/<int:pk>/habits/add/", lv.habit_add, name="template_habit_add"),
    path("library/<int:pk>/habits/<int:habit_id>/remove/", lv.habit_remove, name="template_habit_remove"),
    path("library/<int:pk>/pick/<str:kind>/", lv.pick, name="template_pick"),
    path("library/<int:pk>/pick/<str:kind>/<int:source_id>/", lv.pick_use, name="template_pick_use"),
    path("library/<int:pk>/save/<str:what>/<int:part_id>/", lv.save_part, name="template_save_part"),
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
]
