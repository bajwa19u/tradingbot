"""The two strategies must not reach into each other.

There are two unrelated programs in this repository. One trades breakouts
intraday off Alpaca minute bars and posts to Discord. The other studies
whether companies drift up before they report, using SEC filings and daily
closes, and posts nothing anywhere.

They share a folder and nothing else, and that is deliberate: a change to
the trading bot must not be able to alter what the earnings screen
concludes, and a change to the screen must not be able to affect what gets
sent to Discord tomorrow morning. Right now that separation holds because
nobody has broken it yet, which is not a guarantee - one convenient import
is all it takes, and it would be invisible until something went wrong.

So the boundary is checked rather than trusted. This walks the actual
import graph and fails if either side has grown a dependency on the other.
If you are reading this because the test went red, the fix is almost never
to add a name to a list below; it is that the thing being shared belongs in
a module of its own that both sides may import.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

# The earnings study. Daily bars, SEC filings, no live anything.
EARNINGS = {"preearn", "preearn_screen", "fundamentals"}

# Everything the intraday side is allowed to consist of.
INTRADAY = {
    "adaptive", "backtest", "breakout", "broker", "confidence", "data",
    "discover",
    "discord_msg", "exitsweep",
    "forensics", "history", "holds", "indicators", "inplay", "inplay_bot",
    "inspect_symbol", "live_bot", "notify", "opening", "orb_autopsy",
    "paper", "retest", "run_backtest", "run_live", "sq_autopsy", "squeeze",
    "sweep", "swing", "universe", "widths",
}

# Genuinely common ground: where the repo is on disk, and which secrets
# exist. No strategy logic lives here, and none should.
SHARED = {"config"}


def imports(module: str) -> set[str]:
    """Sibling modules imported by one file in src/."""
    path = SRC / f"{module}.py"
    if not path.exists():
        return set()
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        # `from . import x, y`  /  `from .x import y`  /  `from src.x import y`
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("src."):
                found.add(node.module.split(".")[1])
            elif node.level and node.module:
                found.add(node.module.split(".")[0])
            elif node.level:
                found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("src."):
                    found.add(a.name.split(".")[1])
    return {m for m in found if (SRC / f"{m}.py").exists()}


def reachable(roots: set[str]) -> set[str]:
    """Every sibling module reachable from these, directly or otherwise."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        m = todo.pop()
        for dep in imports(m):
            if dep not in seen:
                seen.add(dep)
                todo.append(dep)
    return seen


def test_the_lists_describe_the_repo_as_it_actually_is():
    """A new module must be classified, not silently ignored."""
    on_disk = {p.stem for p in SRC.glob("*.py")} - {"__init__"}
    classified = EARNINGS | INTRADAY | SHARED
    assert not on_disk - classified, (
        f"unclassified module(s): {sorted(on_disk - classified)} — decide "
        f"which side of the boundary they belong on")
    assert not classified - on_disk, (
        f"listed but missing: {sorted(classified - on_disk)}")


def test_the_earnings_screen_does_not_touch_the_trading_bot():
    leaked = reachable(EARNINGS) & INTRADAY
    assert not leaked, (
        f"the earnings screen now depends on {sorted(leaked)} — a change to "
        f"the trading bot could silently alter its conclusions")


def test_the_trading_bot_does_not_touch_the_earnings_screen():
    leaked = reachable(INTRADAY) & EARNINGS
    assert not leaked, (
        f"the trading bot now depends on {sorted(leaked)} — a change to the "
        f"earnings research could silently alter tomorrow's Discord signals")


def test_the_earnings_screen_sends_nothing_anywhere():
    """It is research. If it learns to post, that was not an accident."""
    for m in sorted(EARNINGS):
        text = (SRC / f"{m}.py").read_text()
        for banned in ("discord", "webhook", "requests.post"):
            assert banned not in text.lower(), (
                f"src/{m}.py mentions {banned!r} — the earnings screen must "
                f"not be able to send anything")


@pytest.mark.parametrize("module", sorted(EARNINGS | INTRADAY | SHARED))
def test_every_module_still_parses(module):
    ast.parse((SRC / f"{module}.py").read_text())
