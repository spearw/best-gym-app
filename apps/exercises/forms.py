from django import forms

from apps.accounts.forms import InputClassMixin

from .models import TAGS, Exercise


class ExerciseForm(InputClassMixin, forms.ModelForm):
    youtube_url = forms.URLField(
        required=False,
        assume_scheme="https",
        label="YouTube demo link",
        widget=forms.URLInput(attrs={"placeholder": "https://youtube.com/…"}),
    )
    tags = forms.MultipleChoiceField(
        choices=[(t, t) for t in TAGS],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Used for filtering when you program, and for tag-based slots in templates.",
    )

    class Meta:
        model = Exercise
        fields = ["name", "category", "measure", "percent_of", "tags", "youtube_url", "cue"]
        labels = {
            "percent_of": "Percentages worked from",
            "cue": "Coaching cue shown to athlete",
            "measure": "Measured in",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Snatch Pull + Snatch complex"}),
            "cue": forms.Textarea(
                attrs={"rows": 2, "placeholder": "e.g. Push the floor away, bar stays close"}
            ),
        }

    def __init__(self, *args, gym, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym
        # A percentage is worked from a lift's own max, so only "base" lifts are offered.
        base = Exercise.objects.filter(gym=gym, archived=False, percent_of__isnull=True)
        if self.instance.pk:
            base = base.exclude(pk=self.instance.pk)
        self.fields["percent_of"].queryset = base.order_by("name")
        self.fields["percent_of"].empty_label = "Its own max (or none)"
        self.fields["percent_of"].help_text = "e.g. Front Squat percentages come from the Back Squat max."

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Exercise.objects.filter(gym=self.gym, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            archived = clash.first().archived
            raise forms.ValidationError(
                "An archived exercise already has this name. Restore it instead."
                if archived
                else "Your library already has an exercise with this name."
            )
        return name

    def clean_percent_of(self):
        target = self.cleaned_data.get("percent_of")
        if target and self.instance.pk and Exercise.objects.filter(percent_of=self.instance).exists():
            raise forms.ValidationError(
                "Other exercises take their percentages from this one, so it must keep its own max."
            )
        return target

    def save(self, commit=True):
        self.instance.gym = self.gym
        return super().save(commit)
