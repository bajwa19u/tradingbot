"""One message per trade: posting returns an id, editing rewrites it."""
from __future__ import annotations

import pytest

from src import discord_msg as dm


class Resp:
    def __init__(self, code=200, body=None, text=""):
        self.status_code, self._body, self.text = code, body or {}, text

    def json(self):
        return self._body


def test_post_returns_the_message_id(monkeypatch):
    seen = {}

    def fake(url, params=None, json=None, timeout=None):
        seen.update(url=url, params=params, json=json)
        return Resp(200, {"id": "12345"})
    monkeypatch.setattr(dm.requests, "post", fake)
    assert dm.post("https://hook", "hello") == "12345"
    assert seen["params"] == {"wait": "true"}, \
        "without wait=true Discord returns no message to edit later"


def test_post_without_a_webhook_does_not_explode():
    assert dm.post("", "hello") is None


def test_post_returns_none_when_discord_refuses(monkeypatch):
    monkeypatch.setattr(dm.requests, "post",
                        lambda *a, **k: Resp(429, text="rate limited"))
    assert dm.post("https://hook", "hello") is None


def test_post_returns_none_when_the_network_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no route to host")
    monkeypatch.setattr(dm.requests, "post", boom)
    assert dm.post("https://hook", "hello") is None


def test_post_returns_none_when_the_reply_carries_no_id(monkeypatch):
    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: Resp(200, {}))
    assert dm.post("https://hook", "x") is None


def test_edit_targets_the_message_endpoint(monkeypatch):
    seen = {}

    def fake(url, json=None, timeout=None):
        seen["url"] = url
        return Resp(200, {"id": "9"})
    monkeypatch.setattr(dm.requests, "patch", fake)
    assert dm.edit("https://hook", "9", "updated") is True
    assert seen["url"] == "https://hook/messages/9"


def test_edit_without_an_id_is_false_not_an_error():
    assert dm.edit("https://hook", "", "x") is False
    assert dm.edit("", "9", "x") is False


def test_edit_is_false_when_the_message_is_gone(monkeypatch):
    monkeypatch.setattr(dm.requests, "patch",
                        lambda *a, **k: Resp(404, text="Unknown Message"))
    assert dm.edit("https://hook", "9", "x") is False


def test_edit_is_false_when_the_network_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(dm.requests, "patch", boom)
    assert dm.edit("https://hook", "9", "x") is False


def test_long_messages_are_truncated_not_rejected(monkeypatch):
    sent = {}
    monkeypatch.setattr(dm.requests, "post",
                        lambda url, params=None, json=None, timeout=None:
                        (sent.update(json), Resp(200, {"id": "1"}))[1])
    dm.post("https://hook", "x" * 5000)
    assert len(sent["content"]) == dm.LIMIT
