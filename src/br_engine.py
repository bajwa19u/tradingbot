"""Break & Retest V1: the setup state machine.

    Break -> Retest -> Confirmation -> Entry

One `Engine` per symbol per setup timeframe per session. It is fed completed
bars one at a time - the backtest replays a day through it, the live bot
feeds it each bar as it closes - so both run exactly the same rules.

For each level and direction a tracker moves through:

  armed    waiting for a bar to CLOSE beyond the level, coming from the near
           side. A wick through does not count.
  broken   waiting for price to come back to within `retest.tolerance_pct` of
           the level, at least `min_bars_after_break` bars later. A CLOSE back
           through the level by more than `fail_close_pct` is a failed
           breakout, not a retest.
  touched  waiting for a candle that closes in the breakout direction and on
           the right side of the level, within `max_bars_after_touch` bars of
           the most recent touch. Its close is the entry.

Every tracker that finishes - confirmed or not - comes out as a `Candidate`
with the reason it ended, so rejected setups can be followed up later.

Rules that can block an otherwise complete setup (inactive level, a gap
"break", the signal window, an open position) are NOT applied here. The
setup is completed and the blocker is attached, so the missed-trade report
can say what the blocked trade would have done.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .br_levels import Level


@dataclass
class Candidate:
    symbol: str
    tf: int
    date: object
    level_name: str
    level_kind: str
    level: float
    direction: str
    attempt: int
    level_active: bool
    level_note: str = ""
    status: str = "open"          # confirmed | failed_breakout | retest_timeout | confirm_timeout | window_closed
    blockers: list = field(default_factory=list)   # rules that would stop the trade
    break_ts: object = None       # bar start of the breakout bar
    break_close: float = None
    gap_break: bool = False
    touch_ts: object = None
    touch_extreme: float = None   # lowest low (long) / highest high (short) during the retest
    confirm_ts: object = None     # bar start of the confirmation bar
    signal_ts: object = None      # bar CLOSE time of the confirmation bar = when it is known
    entry: float = None           # confirmation close (before slippage)
    bars_to_retest: int = None
    bars_to_confirm: int = None

    @property
    def key(self) -> tuple:
        return (self.symbol, str(self.date), self.level_name, self.direction)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["blockers"] = ";".join(self.blockers)
        return d


class _Tracker:
    __slots__ = ("level", "direction", "stage", "attempt", "cand", "break_i", "touch_i")

    def __init__(self, level: Level, direction: str):
        self.level, self.direction = level, direction
        self.stage, self.attempt = "armed", 0
        self.cand, self.break_i, self.touch_i = None, None, None


class Engine:
    def __init__(self, symbol: str, tf: int, date, levels: list[Level], cfg,
                 prev_close: float | None = None):
        self.symbol, self.tf, self.date, self.cfg = symbol, tf, date, cfg
        self.levels = list(levels)
        self.trackers: list[_Tracker] = []
        for lv in self.levels:
            for d in lv.directions:
                self.trackers.append(_Tracker(lv, d))
        self.bars: list[dict] = []
        self.prev_close = prev_close           # last close before the session, for bar 0
        self.finished: list[Candidate] = []
        self.done_keys: set = set()            # (level name, direction) already signalled today
        self.tol = cfg.retest.tolerance_pct / 100
        self.fail = cfg.retest.fail_close_pct / 100
        self.beyond = cfg.breakout.min_close_beyond_pct / 100
        self.max_bars = max(1, int(cfg.retest.max_minutes_after_break // tf))

    # ------------------------------------------------------------ feed
    def on_bar(self, ts, o, h, l, c, v=0.0) -> list[Candidate]:
        """One completed bar. Returns the candidates that finished on it."""
        bar = {"ts": pd.Timestamp(ts), "o": float(o), "h": float(h), "l": float(l),
               "c": float(c), "v": float(v)}
        self.bars.append(bar)
        i = len(self.bars) - 1
        out: list[Candidate] = []
        self._swings(i)
        for tr in self.trackers:
            done = self._step(tr, i, bar)
            if done is not None:
                out.append(done)
        self.finished.extend(out)
        return out

    def close_session(self) -> list[Candidate]:
        """The signal window has ended: anything half-built is closed out."""
        out = []
        for tr in self.trackers:
            if tr.stage in ("broken", "touched"):
                tr.cand.status = "window_closed"
                out.append(tr.cand)
                tr.stage = "done"
        self.finished.extend(out)
        return out

    # ------------------------------------------------------------ rules
    def _side(self, tr):
        return 1 if tr.direction == "long" else -1

    def _step(self, tr: _Tracker, i: int, b: dict) -> Candidate | None:
        if tr.stage == "done":
            return None
        s, L = self._side(tr), tr.level.price

        if tr.stage == "armed":
            prev = self.bars[i - 1]["c"] if i > 0 else self.prev_close
            if not s * (b["c"] - L) > L * self.beyond:
                return None
            if (tr.level.name, tr.direction) in self.done_keys:
                return None
            gap = i == 0 and s * (b["o"] - L) > 0
            came_from_near_side = prev is None or s * (prev - L) <= 0
            if not came_from_near_side and not gap:
                return None                       # already beyond: no break happened here
            tr.attempt += 1
            if tr.attempt > self.cfg.breakout.max_attempts_per_level:
                tr.stage = "done"
                return None
            tr.cand = Candidate(self.symbol, self.tf, self.date, tr.level.name, tr.level.kind,
                                L, tr.direction, tr.attempt, tr.level.active, tr.level.note,
                                break_ts=b["ts"], break_close=b["c"], gap_break=gap)
            if not tr.level.active:
                tr.cand.blockers.append("inactive_level")
            if gap and not self.cfg.breakout.allow_gap_breaks:
                tr.cand.blockers.append("gap_beyond_level")
            tr.stage, tr.break_i, tr.touch_i = "broken", i, None
            return None

        cand = tr.cand
        # A meaningful close back through the level: the breakout failed.
        if s * (L - b["c"]) > L * self.fail:
            cand.status = "failed_breakout"
            return self._rearm(tr)

        touches = s * (b["l"] if s > 0 else b["h"]) <= s * L + L * self.tol
        if touches and i - tr.break_i >= self.cfg.retest.min_bars_after_break:
            if tr.stage == "broken":
                tr.stage = "touched"
                cand.touch_ts = b["ts"]
                cand.bars_to_retest = i - tr.break_i
            tr.touch_i = i
            ext = b["l"] if s > 0 else b["h"]
            cand.touch_extreme = ext if cand.touch_extreme is None else (
                min(cand.touch_extreme, ext) if s > 0 else max(cand.touch_extreme, ext))

        if tr.stage == "touched":
            directional = s * (b["c"] - b["o"]) > 0
            holds = s * (b["c"] - L) > 0 or not self.cfg.confirmation.require_close_beyond_level
            if directional and holds:
                cand.status = "confirmed"
                cand.confirm_ts = b["ts"]
                cand.signal_ts = b["ts"] + pd.Timedelta(minutes=self.tf)
                cand.entry = b["c"]
                cand.bars_to_confirm = i - tr.touch_i
                tr.stage = "done"
                self.done_keys.add((tr.level.name, tr.direction))
                return cand
            if i - tr.touch_i >= self.cfg.confirmation.max_bars_after_touch:
                cand.status = "confirm_timeout"
                return self._rearm(tr)

        if i - tr.break_i >= self.max_bars:
            cand.status = "retest_timeout" if tr.stage == "broken" else "confirm_timeout"
            return self._rearm(tr)
        return None

    def _rearm(self, tr: _Tracker) -> Candidate:
        cand = tr.cand
        done = tr.attempt >= self.cfg.breakout.max_attempts_per_level
        tr.stage = "done" if done else "armed"
        tr.cand, tr.break_i, tr.touch_i = None, None, None
        return cand

    # ------------------------------------------------------------ swings
    def _swings(self, i: int) -> None:
        """A pivot is confirmed `right` bars after it prints. It then becomes
        a level for the bars that follow, never for the bars it is made of."""
        left, right = self.cfg.levels.swing_left, self.cfg.levels.swing_right
        p = i - right
        if p - left < 0:
            return
        win = self.bars[p - left:i + 1]
        mid = self.bars[p]
        stamp = f"{mid['ts']:%H:%M}"
        new = []
        if "swing_high" in self.cfg.levels.long and mid["h"] == max(x["h"] for x in win) \
                and sum(x["h"] == mid["h"] for x in win) == 1:
            new.append(Level(f"swing_high@{stamp}", "swing_high", mid["h"], ("long",)))
        if "swing_low" in self.cfg.levels.short and mid["l"] == min(x["l"] for x in win) \
                and sum(x["l"] == mid["l"] for x in win) == 1:
            new.append(Level(f"swing_low@{stamp}", "swing_low", mid["l"], ("short",)))
        for lv in new:
            pct = self.cfg.levels.merge_within_pct
            if any(abs(k.price - lv.price) <= k.price * pct / 100 for k in self.levels):
                continue                       # already watched under another name
            self.levels.append(lv)
            tr = _Tracker(lv, lv.directions[0])
            # Price is beyond its own pivot only if it already broke it; the
            # near-side check on the next bar takes care of that.
            self.trackers.append(tr)


def run_day(symbol: str, tf: int, date, levels: list[Level], bars: pd.DataFrame, cfg,
            prev_close: float | None = None, until_min: int | None = None) -> list[Candidate]:
    """Replay one session's `tf`-minute bars through an Engine. Bars whose
    CLOSE is after `until_min` (minutes after midnight) are not fed."""
    eng = Engine(symbol, tf, date, [Level(**{**lv.__dict__, "aliases": list(lv.aliases)})
                                    for lv in levels], cfg, prev_close)
    for ts, r in bars.iterrows():
        close_min = ts.hour * 60 + ts.minute + tf
        if until_min is not None and close_min > until_min:
            break
        eng.on_bar(ts, r.open, r.high, r.low, r.close, r.volume)
    eng.close_session()
    return eng.finished
