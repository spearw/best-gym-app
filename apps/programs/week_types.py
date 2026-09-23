"""Week types colour-code the program editor, the athlete's week strip and every
session card. The CSS variables in static/css/tokens.css hold the default colours;
a gym can override them (Gym.week_type_colours), and the legend is generated from here."""

WEEK_TYPES = {
    "accum": {
        "label": "Accumulation",
        "desc": "Volume build — higher reps, moderate loads",
        "colour": "#2E9E5B",
    },
    "intens": {"label": "Intensification", "desc": "Load climbs, volume drops", "colour": "#E07C24"},
    "peak": {"label": "Comp Prep", "desc": "Openers & heavy singles, taper volume", "colour": "#D8412F"},
    "deload": {"label": "Deload", "desc": "Recovery — 60-70% loads, low volume", "colour": "#8A63D2"},
    "cut": {
        "label": "Cutting",
        "desc": "Weight-make week — reduced volume, keep intensity",
        "colour": "#2B7DE0",
    },
    "tech": {
        "label": "Technique",
        "desc": "Positions, tempo & complexes at light loads",
        "colour": "#0F9BA8",
    },
}

WEEK_TYPE_CHOICES = [(key, wt["label"]) for key, wt in WEEK_TYPES.items()]
