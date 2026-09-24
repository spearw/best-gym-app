"""Server-drawn SVG charts, ported from the mockup's sparkSVG / drawE1RM / drawVol.

- e1RM trend: an exercise's session e1RM (best set) over its last CHART_POINTS
  sessions, with the week types of the athlete's programs as shaded bands (a dip reads
  against the block that caused it) and bodyweight as a dashed line on its own scale.
- Weekly volume and compliance: load × reps per training week (the gym's weeks) as bars,
  compliance % as a line, over the last 8 weeks.
- `spark()`: the small line used in the library rail and the athlete's Progress chart.
Values are shown in the viewer's unit; nothing here is stored.
"""

import datetime
from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.accounts import units

from . import history

CHART_POINTS = 12
BRAND = "#1F4FD8"


def _f(x):
    return f"{x:.1f}"


def spark(values, w, h, color, dots=False, area=False, sw=2, pad=6):
    """Path (and optional dots / area) for a list of numbers, as an SVG fragment."""
    values = [float(v) for v in values]
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = (w - 2 * pad) / max(1, len(values) - 1)
    pts = [(pad + i * step, h - pad - (v - lo) / span * (h - 2 * pad)) for i, v in enumerate(values)]
    path = " ".join(("L" if i else "M") + f"{_f(x)} {_f(y)}" for i, (x, y) in enumerate(pts))
    s = ""
    if area:
        s += f'<path d="{path} L{_f(pts[-1][0])} {h - 2} L{_f(pts[0][0])} {h - 2} Z" fill="{color}" opacity=".08"/>'
    s += f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'
    if dots:
        for i, (x, y) in enumerate(pts):
            s += f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{3.5 if i == len(pts) - 1 else 2.2}" fill="{color}"/>'
    return s


def _week_type_on(athlete, date, weeks):
    for w in weeks:
        if w.start_date <= date <= w.start_date + datetime.timedelta(days=6):
            return w.week_type
    return None


def e1rm_points(athlete, exercise, limit=CHART_POINTS):
    """[(date, e1rm kg, bodyweight kg or None, week type or None)], oldest first."""
    from apps.programs.models import ProgramWeek

    entries = history.exercise_history(athlete, [exercise.pk], limit=limit).get(exercise.pk, [])
    entries = [e for e in reversed(entries) if e.best_e1rm]
    weeks = list(ProgramWeek.objects.filter(program__athlete=athlete).select_related("week_type"))
    bodyweights = list(athlete.bodyweights.order_by("date", "id"))
    points = []
    for e in entries:
        bw = next((b.kg for b in reversed(bodyweights) if b.date <= e.date), None)
        points.append((e.date, e.best_e1rm, bw, _week_type_on(athlete, e.date, weeks)))
    return points


def e1rm_chart(athlete, exercise, unit):
    """The coach Overview's e1RM trend (460×170)."""
    points = e1rm_points(athlete, exercise)
    W, P, plot_h, top = 460, 16, 126, 14
    if len(points) < 2:
        return mark_safe(
            '<text x="230" y="90" text-anchor="middle" fill="var(--ink-4)" font-size="13">'
            "Not enough logged data for this lift yet</text>"
        )
    vals = [float(units.from_kg(p[1], unit)) for p in points]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    xs = [P + i * (W - 2 * P) / (len(points) - 1) for i in range(len(points))]
    ys = [top + plot_h - (v - lo) / span * plot_h for v in vals]
    s = ""
    # Phase bands: consecutive points with the same week type share one band.
    i = 0
    while i < len(points):
        wt = points[i][3]
        j = i
        while j + 1 < len(points) and points[j + 1][3] == wt:
            j += 1
        if wt is not None:
            x0 = 2 if i == 0 else (xs[i - 1] + xs[i]) / 2
            x1 = W - 2 if j == len(points) - 1 else (xs[j] + xs[j + 1]) / 2
            s += f'<rect x="{_f(x0)}" y="6" width="{_f(x1 - x0)}" height="{plot_h + 16}" rx="4" fill="{wt.colour}" opacity=".09"/>'
            s += (
                f'<text x="{_f((x0 + x1) / 2)}" y="{top + plot_h + 22}" text-anchor="middle" font-size="9" '
                f'font-weight="700" fill="{wt.colour}">{escape(wt.name.upper())}</text>'
            )
        i = j + 1
    # Bodyweight: dashed, on its own scale.
    bw = [(xs[k], float(units.from_kg(p[2], unit))) for k, p in enumerate(points) if p[2]]
    if len(bw) > 1:
        blo, bhi = min(b for _x, b in bw), max(b for _x, b in bw)
        bspan = (bhi - blo) or 1
        bpath = " ".join(
            ("L" if k else "M") + f"{_f(x)} {_f(top + plot_h * 0.72 - (b - blo) / bspan * plot_h * 0.5)}"
            for k, (x, b) in enumerate(bw)
        )
        s += (
            f'<path d="{bpath}" fill="none" stroke="var(--ink-4)" stroke-width="1.6" stroke-dasharray="4 4"/>'
        )
        s += f'<text x="{W - 4}" y="{top + 10}" text-anchor="end" font-size="9" fill="var(--ink-4)">bw {bw[-1][1]:g} {unit}</text>'
    path = " ".join(
        ("L" if k else "M") + f"{_f(x)} {_f(y)}" for k, (x, y) in enumerate(zip(xs, ys, strict=True))
    )
    s += f'<path d="{path} L{_f(xs[-1])} {top + plot_h} L{_f(xs[0])} {top + plot_h} Z" fill="{BRAND}" opacity=".07"/>'
    s += f'<path d="{path}" fill="none" stroke="{BRAND}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    for k, (x, y) in enumerate(zip(xs, ys, strict=True)):
        date = points[k][0]
        s += (
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{3.5 if k == len(xs) - 1 else 2.4}" fill="{BRAND}">'
            f"<title>{date:%-d %b}: e1RM {vals[k]:.0f} {unit}</title></circle>"
        )
    s += f'<text x="4" y="16" font-size="11" fill="var(--ink-3)">{hi:.0f} {unit}</text>'
    s += f'<text x="4" y="{top + plot_h + 4}" font-size="11" fill="var(--ink-3)">{lo:.0f} {unit}</text>'
    return mark_safe(s)


def weekly(athlete, weeks=8):
    """[(week start, volume kg, compliance % or None)] for the last `weeks` training weeks."""
    from .models import SetLog

    today = athlete.today()
    this_week = athlete.gym.week_start_for(today)
    starts = [this_week - datetime.timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    sets = SetLog.objects.filter(
        done=True,
        load_kg__isnull=False,
        reps__isnull=False,
        session_exercise__session_log__athlete=athlete,
        session_exercise__session_log__finished_at__isnull=False,
        session_exercise__session_log__date__gte=starts[0],
    ).values_list("session_exercise__session_log__date", "load_kg", "reps")
    volume = dict.fromkeys(starts, Decimal(0))
    for date, load, reps in sets:
        volume[athlete.gym.week_start_for(date)] += load * reps
    rows = []
    for start in starts:
        done, scheduled = history.compliance(
            athlete, today, end=min(start + datetime.timedelta(days=6), today)
        )
        rows.append((start, volume[start], round(done / scheduled * 100) if scheduled else None))
    return rows


def volume_chart(athlete, unit):
    """Bars for weekly volume (thousands of kg or lb lifted), a line for compliance %."""
    rows = weekly(athlete)
    vols = [float(units.from_kg(v, unit)) / 1000 for _s, v, _c in rows]
    top = max(vols) or 1
    s = ""
    for i, (start, _v, _c) in enumerate(rows):
        x, h = 24 + i * 54, vols[i] / top * 110
        s += (
            f'<rect x="{x}" y="{_f(150 - h)}" width="26" height="{_f(h)}" rx="5" fill="var(--wk-accum)" opacity=".8">'
            f"<title>Week of {start:%-d %b}: {vols[i]:.1f}k {unit}</title></rect>"
        )
        s += f'<text x="{x + 13}" y="164" text-anchor="middle" font-size="9" fill="var(--ink-4)">{start:%-d/%-m}</text>'
    compliance = [c for _s, _v, c in rows if c is not None]
    if len(compliance) > 1:
        s += spark(compliance, 460, 150, BRAND, sw=2, pad=24)
    return mark_safe(s), rows


def progress_chart(athlete, exercise, unit):
    """The athlete's Progress chart (340×120) and the change over it ("+4 kg")."""
    points = e1rm_points(athlete, exercise)
    if len(points) < 2:
        return None, None
    vals = [float(units.from_kg(p[1], unit)) for p in points]
    svg = spark(vals, 340, 110, BRAND, dots=True, area=True, sw=2.5, pad=12)
    svg += f'<text x="8" y="14" font-size="10" fill="var(--ink-3)">{max(vals):.0f} {unit}</text>'
    days = (points[-1][0] - points[0][0]).days
    change = round(vals[-1] - vals[0])
    return mark_safe(svg), {"change": change, "drop": abs(change), "weeks": max(1, round(days / 7))}


def rail_spark(entries, trend):
    """The library rail's 52×18 sparkline (entries newest first)."""
    values = [e.best_e1rm or (e.top.load_kg if e.top else 0) for e in reversed(entries)]
    if len(values) < 2:
        return ""
    color = "#DC3545" if trend == "down" else "#159570"
    return mark_safe(
        f'<svg width="52" height="18" viewBox="0 0 52 18" aria-hidden="true">{spark(values, 52, 18, color, sw=1.6, pad=2)}</svg>'
    )


def chart_lifts(athlete):
    """Exercises worth charting: the gym's tracked lifts, then others the athlete has
    logged with a load."""
    from apps.exercises.models import Exercise, tracked_exercises

    tracked = list(tracked_exercises(athlete.gym))
    logged = history.exercise_history(athlete, limit=2)
    others = (
        Exercise.objects.filter(pk__in=[k for k, v in logged.items() if any(e.best_e1rm for e in v)])
        .exclude(pk__in=[e.pk for e in tracked])
        .order_by("name")
    )
    return tracked + list(others)
