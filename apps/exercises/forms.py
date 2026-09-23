from django import forms
from django.db.models.functions import Lower

from apps.accounts.forms import InputClassMixin

from .models import TAG_MAX_LENGTH, Category, Exercise, Tag


class ExerciseForm(InputClassMixin, forms.ModelForm):
    youtube_url = forms.URLField(
        required=False,
        assume_scheme="https",
        label="YouTube demo link",
        widget=forms.URLInput(attrs={"placeholder": "https://youtube.com/…"}),
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
            "tags": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, gym, **kwargs):
        super().__init__(*args, **kwargs)
        self.gym = gym
        self.fields["category"].queryset = Category.objects.filter(gym=gym)
        self.fields["category"].empty_label = None
        self.fields["tags"].queryset = Tag.objects.filter(gym=gym).order_by(Lower("name"))
        self.fields[
            "tags"
        ].help_text = "Used for filtering when you program, and for tag-based slots in templates."
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


def clean_label(value, max_length, what):
    """Shared rules for category, tag and week type names: trimmed, single-spaced, not empty."""
    value = " ".join((value or "").split())
    if not value:
        raise forms.ValidationError(f"Give the {what} a name.")
    if len(value) > max_length:
        raise forms.ValidationError(f"Keep {what} names to {max_length} characters.")
    return value


class NameForm(forms.Form):
    """Validates one name for a gym-owned, case-insensitively unique model."""

    name = forms.CharField(required=False)

    def __init__(self, *args, model, gym, max_length, what, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.model, self.gym, self.max_length, self.what, self.instance = (
            model,
            gym,
            max_length,
            what,
            instance,
        )

    def clean_name(self):
        name = clean_label(self.cleaned_data.get("name"), self.max_length, self.what)
        clash = self.model.objects.filter(gym=self.gym, name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"You already have a {self.what} called “{name}”.")
        return name


def save_pending_names(model, gym, post, max_length):
    """Editors send every row's on-screen name as name_<id> with each request. Save
    valid, changed ones before acting, so an edit followed quickly by a click (move,
    delete, add) is never lost, whatever order the requests arrive in. Invalid names
    are skipped here; the row's own save request reports them."""
    rows = {obj.pk: obj for obj in model.objects.filter(gym=gym)}
    for key, raw in post.items():
        if not key.startswith("name_") or not key[5:].isdigit() or int(key[5:]) not in rows:
            continue
        obj = rows[int(key[5:])]
        name = " ".join(raw.split())
        if not name or len(name) > max_length or name == obj.name:
            continue
        if model.objects.filter(gym=gym, name__iexact=name).exclude(pk=obj.pk).exists():
            continue
        obj.name = name
        obj.save(update_fields=["name"])


TAG_NAME_LENGTH = TAG_MAX_LENGTH
CATEGORY_NAME_LENGTH = Category._meta.get_field("name").max_length
