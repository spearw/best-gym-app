"""HTMX response helpers shared by every app."""

import json


def trigger(response, **events):
    """Set HX-Trigger. JSON is ASCII-escaped because HTTP headers can't carry raw
    non-ASCII: an em dash in a toast would otherwise make HTMX drop the whole header.

        trigger(response, toast={"message": "Saved", "kind": "good"}, invitesChanged=True)
    """
    response["HX-Trigger"] = json.dumps(events, ensure_ascii=True)
    return response


def trigger_after_swap(response, **events):
    """Like trigger(), but fires once the new content is in the page. Use it for events
    that remove the requesting element (e.g. closeModal), or HTMX abandons the swap."""
    response["HX-Trigger-After-Swap"] = json.dumps(events, ensure_ascii=True)
    return response


def toast(response, message, kind=""):
    return trigger(response, toast={"message": message, "kind": kind})


def retarget(response, target, swap="innerHTML"):
    """Send this response somewhere other than the requesting element's hx-target,
    e.g. re-render a modal with errors instead of the list it would have updated."""
    response["HX-Retarget"] = target
    response["HX-Reswap"] = swap
    return response
