from django.core.exceptions import ValidationError
from django.db import models


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
