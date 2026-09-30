"""One Discord message per trade, edited in place when the trade closes.

A trade used to produce two messages: an entry when it fired and a close
when it resolved. Eighteen trades meant thirty-six messages interleaved, and
reading the day off the feed meant matching them up by eye.

Discord webhooks can edit a message they created, so a trade is now one card
that starts as the entry and is rewritten with the result. Posting with
`wait=true` makes Discord return the created message, whose id is kept
alongside the trade; the close then PATCHes that id.

Nothing here is allowed to take the bot off the air. Every failure is logged
and reported back as "not sent" or "could not edit", and the caller falls
back to posting the close as its own message rather than losing a result
silently - a feed that quietly drops the outcome of a trade is worse than a
feed with an extra message in it.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

TIMEOUT = 20
LIMIT = 1900


def post(url: str, text: str) -> str | None:
    """Send a message; return its id so it can be edited later.

    None means the message did not go out, or went out without an id - in
    either case the caller must not assume it can be edited.
    """
    if not url:
        log.warning("No Discord webhook configured — skipping")
        return None
    try:
        resp = requests.post(url, params={"wait": "true"},
                             json={"content": text[:LIMIT]}, timeout=TIMEOUT)
        if resp.status_code >= 300:
            log.error("Discord %s: %s", resp.status_code, resp.text[:200])
            return None
        return str(resp.json().get("id") or "") or None
    except Exception as exc:                                   # noqa: BLE001
        log.error("Discord post failed: %s", exc)
        return None


def edit(url: str, message_id: str, text: str) -> bool:
    """Rewrite a message this webhook created. False if it could not be done.

    A message can be gone for reasons that are nobody's fault - deleted by
    hand, or a webhook rotated between the entry and the close - so the
    caller treats False as "post it separately" rather than as an error.
    """
    if not (url and message_id):
        return False
    try:
        resp = requests.patch(f"{url}/messages/{message_id}",
                              json={"content": text[:LIMIT]}, timeout=TIMEOUT)
        if resp.status_code >= 300:
            log.error("Discord edit %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:                                   # noqa: BLE001
        log.error("Discord edit failed: %s", exc)
        return False
