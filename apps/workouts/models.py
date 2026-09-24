import datetime

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class QuestionType(models.TextChoices):
    SCALE = "scale", "1–10 scale"
    CHOICE = "choice", "Multiple choice"


class CheckinQuestionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived=False).order_by("order", "id")

    def gym_defaults(self, gym):
        return self.filter(gym=gym, athlete__isnull=True)

    def for_athlete(self, athlete):
        return self.filter(athlete=athlete)


class CheckinQuestion(models.Model):
    """A pre-session check-in question. Owned either by a gym (the defaults new
    athletes are given) or by one athlete (their own copy, which their coach can
    adjust). Removing a question archives it so old answers keep their question."""

    gym = models.ForeignKey(
        "accounts.Gym", null=True, blank=True, on_delete=models.CASCADE, related_name="default_questions"
    )
    athlete = models.ForeignKey(
        "accounts.Athlete", null=True, blank=True, on_delete=models.CASCADE, related_name="questions"
    )
    order = models.PositiveIntegerField(default=0)
    type = models.CharField(max_length=10, choices=QuestionType.choices)
    text = models.CharField(max_length=200)
    low_label = models.CharField(max_length=60, blank=True)
    high_label = models.CharField(max_length=60, blank=True)
    options = models.JSONField(default=list, blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CheckinQuestionQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(gym__isnull=False, athlete__isnull=True)
                    | models.Q(gym__isnull=True, athlete__isnull=False)
                ),
                name="checkin_question_has_exactly_one_owner",
            )
        ]

    def __str__(self):
        return self.text

    def clean(self):
        if self.type == QuestionType.CHOICE:
            if not isinstance(self.options, list) or not all(isinstance(o, str) and o for o in self.options):
                raise ValidationError({"options": "Options must be a list of non-empty strings"})

    @property
    def owner_gym(self):
        return self.gym if self.gym_id else self.athlete.gym

    def copy_for(self, athlete, order=None):
        return CheckinQuestion(
            athlete=athlete,
            order=self.order if order is None else order,
            type=self.type,
            text=self.text,
            low_label=self.low_label,
            high_label=self.high_label,
            options=list(self.options),
        )


# The mockup's default check-in, given to every new gym.
DEFAULT_QUESTIONS = [
    {
        "type": QuestionType.SCALE,
        "text": "How recovered do you feel today?",
        "low_label": "not recovered",
        "high_label": "fully recovered",
    },
    {
        "type": QuestionType.CHOICE,
        "text": "Anything affecting today's session?",
        "options": [
            "Nothing — all good",
            "Legs are sore",
            "Poor sleep",
            "Shoulder discomfort",
            "Low energy / cutting",
        ],
    },
]


def install_default_questions(gym):
    """Give a gym the mockup's default questions if it has none yet."""
    if CheckinQuestion.objects.gym_defaults(gym).exists():
        return
    CheckinQuestion.objects.bulk_create(
        [CheckinQuestion(gym=gym, order=i, **q) for i, q in enumerate(DEFAULT_QUESTIONS)]
    )


def copy_defaults_to(athlete):
    """Replace an athlete's active questions with copies of the gym defaults.
    Their old questions are archived, not deleted, so past answers keep them."""
    CheckinQuestion.objects.for_athlete(athlete).filter(archived=False).update(archived=True)
    defaults = CheckinQuestion.objects.gym_defaults(athlete.gym).active()
    CheckinQuestion.objects.bulk_create([q.copy_for(athlete, order=i) for i, q in enumerate(defaults)])


# ---------------------------------------------------------------- session records (phase 4)
#
# One SessionLog per workout is the source of truth: check-in answers, every set, the
# post-session RPE and comment, and any issue reported. History, PRs, day status and
# streaks are derived from these rows (apps/workouts/history.py), never stored twice.

EDIT_WINDOW = datetime.timedelta(hours=24)


class SessionLogQuerySet(models.QuerySet):
    def finished(self):
        return self.filter(finished_at__isnull=False)

    def unfinished(self):
        return self.filter(finished_at__isnull=True)


class SessionLog(models.Model):
    """One workout. `date` is the day it was trained in the athlete's zone; a session
    logged after the fact carries the planned day, and `started_at` shows when it was
    entered. A paused session has no `finished_at`."""

    athlete = models.ForeignKey("accounts.Athlete", on_delete=models.CASCADE, related_name="session_logs")
    program_session = models.ForeignKey(
        "programs.ProgramSession", null=True, blank=True, on_delete=models.SET_NULL, related_name="logs"
    )
    date = models.DateField()
    name = models.CharField(max_length=120, blank=True)
    week_type = models.ForeignKey(
        "programs.WeekType", null=True, blank=True, on_delete=models.PROTECT, related_name="session_logs"
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    checkin_skipped = models.BooleanField(default=False)
    session_rpe = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    comment = models.TextField(blank=True)

    objects = SessionLogQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-started_at"]
        constraints = [
            # A planned session is logged once; starting it again resumes the same log.
            models.UniqueConstraint(
                fields=["program_session"],
                condition=models.Q(program_session__isnull=False),
                name="one_log_per_program_session",
            ),
        ]

    def __str__(self):
        return f"{self.athlete} · {self.name or 'Session'} on {self.date}"

    @property
    def finished(self):
        return self.finished_at is not None

    def editable(self, now=None):
        """Paused sessions can always be continued; finished ones for 24 hours."""
        if self.finished_at is None:
            return True
        return (now or timezone.now()) < self.finished_at + EDIT_WINDOW

    @property
    def logged_late(self):
        """Entered on a later day than it was trained (a missed day filled in)."""
        return timezone.localdate(self.started_at, self.athlete.user.zoneinfo) > self.date


class SessionExercise(models.Model):
    """One exercise in a logged session. `prescribed` is a snapshot of what the coach
    asked for when the session started (see apps/workouts/sessions.snapshot), so later
    edits to the program never change "asked for". `exercise_name` keeps the history
    readable if the exercise is deleted from the library (the link is then cleared)."""

    session_log = models.ForeignKey(SessionLog, on_delete=models.CASCADE, related_name="exercises")
    prescription = models.ForeignKey(
        "programs.Prescription", null=True, blank=True, on_delete=models.SET_NULL, related_name="logged"
    )
    exercise = models.ForeignKey(
        "exercises.Exercise",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="session_exercises",
    )
    exercise_name = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)
    prescribed = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise_name} in {self.session_log}"


class SetLog(models.Model):
    """One set as logged. Loads are exact kg; a complex logs one rep of the complex;
    timed work logs seconds and no reps. `rir` 5 means "5 or more"."""

    session_exercise = models.ForeignKey(SessionExercise, on_delete=models.CASCADE, related_name="sets")
    set_number = models.PositiveSmallIntegerField()
    load_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    rir = models.PositiveSmallIntegerField(null=True, blank=True)
    done = models.BooleanField(default=False)
    logged_at = models.DateTimeField(auto_now=True)
    # The coach chose to keep the current max rather than use this set as the new one.
    max_dismissed = models.BooleanField(default=False)

    class Meta:
        ordering = ["set_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["session_exercise", "set_number"], name="unique_set_per_exercise"
            ),
        ]

    def __str__(self):
        return f"Set {self.set_number} of {self.session_exercise}"


class CheckinAnswer(models.Model):
    """The question FK keeps trends working after a reword; `question_text` keeps the
    history readable if the question is archived or removed."""

    session_log = models.ForeignKey(SessionLog, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(
        CheckinQuestion, null=True, blank=True, on_delete=models.SET_NULL, related_name="answers"
    )
    order = models.PositiveSmallIntegerField(default=0)
    question_text = models.CharField(max_length=200)
    type = models.CharField(max_length=10, choices=QuestionType.choices)
    value = models.CharField(max_length=200)  # "1".."10" for a scale, else the chosen option
    other_text = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["session_log", "question"], name="one_answer_per_question"),
        ]

    def __str__(self):
        return f"{self.question_text}: {self.display}"

    @property
    def display(self):
        if self.type == QuestionType.SCALE:
            return f"{self.value} / 10"
        return self.value


OTHER_OPTION = "Other"


class IssueKind(models.TextChoices):
    PAIN = "pain", "Pain / possible injury"
    EQUIPMENT = "equipment", "Equipment not available"
    PRESCRIPTION = "prescription", "Prescription looks wrong"
    OTHER = "other", "Something else"


class IssueReport(models.Model):
    athlete = models.ForeignKey("accounts.Athlete", on_delete=models.CASCADE, related_name="issues")
    session_log = models.ForeignKey(
        SessionLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    kind = models.CharField(max_length=14, choices=IssueKind.choices)
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.athlete}: {self.get_kind_display()}"


class FormVideoQuerySet(models.QuerySet):
    def uploaded(self):
        return self.filter(uploaded_at__isnull=False)

    def available(self):
        return self.uploaded().filter(deleted_at__isnull=True)


class FormVideo(models.Model):
    """An athlete's clip of one exercise in a session, for the coach to check. The file is
    in the form-video bucket under `key` (apps/workouts/videos.py). `uploaded_at` is set
    once the upload is confirmed; the file is deleted FORM_VIDEOS["keep_days"] later
    (`deleted_at`), but the row stays so the session still shows there was a video and
    what the coach said."""

    session_log = models.ForeignKey(SessionLog, on_delete=models.CASCADE, related_name="videos")
    session_exercise = models.ForeignKey(
        SessionExercise, null=True, blank=True, on_delete=models.SET_NULL, related_name="videos"
    )
    exercise_name = models.CharField(max_length=120)
    key = models.CharField(max_length=300, unique=True)
    content_type = models.CharField(max_length=60)
    size = models.PositiveBigIntegerField()
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    feedback = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = FormVideoQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.exercise_name} video in {self.session_log}"
