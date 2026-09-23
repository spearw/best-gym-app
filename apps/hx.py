"""HTMX response helpers shared by every app."""

import json


def trigger(response, **events):
    """Set HX-Trigger. JSON is ASCII-escaped because HTTP headers can't carry raw
    non-ASCII: an em dash in a toast would otherwise make HTMX drop the whole header.

        trigger(response, toast={"message": "Saved", "kind": "good"}, invitesChanged=True)
    """
    response["HX-Trigger"] = json.dumps(events, ensure_ascii=True)
    return response


def toast(response, message, kind=""):
    return trigger(response, toast={"message": message, "kind": kind})
