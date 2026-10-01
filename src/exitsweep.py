"""Which exit rule would have banked 30 September instead of watching it go?

That day answered the entry question and asked a different one. Every open
position was green at some point: +7.01% of favourable movement across seven
trades, which became -4.58% by the bell. In Uday's options the same shape was
the difference between +$42,692 and -$107,281, because every contract bought
that morning expired worthless.

So the entries were not the problem. The exits were, and this measures them.

Same entries throughout
-----------------------
Every variant here takes the IDENTICAL trades at the identical prices. Only
the way out changes. That is what makes the comparison mean anything: a rule
that looks better because it also skipped the bad days would be telling us
about the days, not the rule.

  as it trades now      stop, target, or the closing bell
  breakeven             once it is up enough, stop losing on it
  give back             hand back only a share of the best it ever showed
  near target           it has had long enough and it is close enough

and separately, the entry window - after how many minutes the bot stops
taking new trades at all. The autopsy already has breaks 30-45 minutes after
the bell at -28.3% while the first half hour made money, so this is less a
question than a confirmation, but it is swept rather than assumed.

Choosing honestly
-----------------
Fourteen variants against one baseline is fourteen chances to find a winner
by luck. The best of fourteen coin flips looks impressive. So the rule is
picked on the explore dates ONLY, its holdout number is reported beside it,
and the noise floor for this many variants is printed next to the result. If
the best rule does not clear that floor on the holdout, this file says so
rather than dressing it up.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from zoneinfo import ZoneInfo

import pandas as pd

from . import opening as op
from . import widths as w
from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import UNIVERSES

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("exitsweep")

# name -> the parameters that change. Everything else stays as it trades.
EXITS: list[tuple[str, dict]] = [
    ("as it trades now", {}),
    ("breakeven at +0.5%", {"breakeven_after_pct": 0.5}),
    ("breakeven at +1.0%", {"breakeven_after_pct": 1.0}),
    ("give back at most 1/3", {"giveback_frac": 0.33, "giveback_arm_pct": 0.5}),
    ("give back at most 1/2", {"giveback_frac": 0.50, "giveback_arm_pct": 0.5}),
    ("give back at most 2/3", {"giveback_frac": 0.67, "giveback_arm_pct": 0.5}),
    ("80% of target after 15m", {"near_target_after": 15,
                                 "near_target_frac": 0.8}),
    ("80% of target after 30m", {"near_target_after": 30,
                                 "near_target_frac": 0.8}),
    ("80% of target after 45m", {"near_target_after": 45,
                                 "near_target_frac": 0.8}),
    ("60% of target after 30m", {"near_target_after": 30,
                                 "near_target_frac": 0.6}),
    ("60% of target after 45m", {"near_target_after": 45,
                                 "near_target_frac": 0.6}),
    ("breakeven +0.5% and give back 1/2",
     {"breakeven_after_pct": 0.5, "giveback_frac": 0.50,
      "giveback_arm_pct": 0.5}),
    ("breakeven +0.5% and 80% after 30m",
     {"breakeven_after_pct": 0.5, "near_target_after": 30,
      "near_target_frac": 0.8}),
]

WINDOWS: list[int | None] = [None, 30, 60, 90, 120]

EXPLORE_SHARE = 2 / 3     # the first two thirds of the dates choose; the rest judge


def split_dates(data: dict[str, pd.DataFrame]) -> tuple[set, set]:
    """Explore = the earlier dates, holdout = the later ones.

    Split by date rather than at random, because a random split lets a rule
    learn one morning from another morning of the same week.
    """
    dates = sorted({d for df in data.values() if len(df)
                    for d, _ in op.by_day(df)})
    if len(dates) < 4:
        raise RuntimeError(
            f"only {len(dates)} trading days came back - not enough to split. "
            f"Check the symbols and the date range.")
    cut = int(len(dates) * EXPLORE_SHARE)
    return set(dates[:cut]), set(dates[cut:])


def run_one(data: dict[str, pd.DataFrame], base: dict, extra: dict,
            window: int | None, dates: set) -> dict:
    p = {**base, **extra}
    if window is not None:
        p["entry_before_min"] = window
    return w.tally(w.trades_for(data, dates, p))


def noise_floor(tallies: list[dict], n_variants: int) -> float:
    """How big a profit gap is unremarkable when you tried this many rules.

    sqrt(2 ln N) standard errors - the expected maximum of N draws. A best
    variant inside this of the baseline has not been shown to be better; it
    has been shown to be the luckiest of N.
    """
    per = [t["profit_pct"] / t["n"] for t in tallies if t["n"] > 20]
    if len(per) < 2:
        return 0.0
    n = max((t["n"] for t in tallies), default=0)
    spread = (max(per) - min(per)) or 0.0
    se = spread * math.sqrt(max(n, 1)) / 2 if n else 0.0
    return round(math.sqrt(2 * math.log(max(n_variants, 2))) * se, 2)


HEAD = ("| rule | trades | win % | won | lost | profit % |"
        "\n|---|---|---|---|---|---|")


def row(name: str, t: dict) -> str:
    return (f"| {name} | {t['n']} | {t['win_pct']:.1f}% | {t['won']} | "
            f"{t['lost']} | {t['profit_pct']:+.1f}% |")


def sweep(data: dict[str, pd.DataFrame]) -> tuple[str, dict]:
    base = w.cfg()
    explore, holdout = split_dates(data)
    log.info("%d explore dates, %d holdout dates", len(explore), len(holdout))

    L = ["# Which exit rule keeps the money", "",
         f"{len(data)} symbols · {len(explore)} explore dates · "
         f"{len(holdout)} holdout dates", "",
         "Every rule takes the SAME entries at the SAME prices. Only the way "
         "out changes.", ""]

    # --- the exits -----------------------------------------------------------
    ex_explore, ex_hold = {}, {}
    for name, extra in EXITS:
        ex_explore[name] = run_one(data, base, extra, None, explore)
        ex_hold[name] = run_one(data, base, extra, None, holdout)
        log.info("%-36s explore %+7.1f%%  holdout %+7.1f%%", name,
                 ex_explore[name]["profit_pct"], ex_hold[name]["profit_pct"])

    L += ["## Exit rules — explore", "", HEAD]
    L += [row(n, ex_explore[n]) for n, _ in EXITS]
    L += ["", "## Exit rules — holdout (dates that chose nothing)", "", HEAD]
    L += [row(n, ex_hold[n]) for n, _ in EXITS]

    # --- the entry window ----------------------------------------------------
    win_explore, win_hold = {}, {}
    for win in WINDOWS:
        label = "no cutoff" if win is None else f"stop entering after {win}m"
        win_explore[label] = run_one(data, base, {}, win, explore)
        win_hold[label] = run_one(data, base, {}, win, holdout)
    L += ["", "## When to stop taking new trades — explore", "", HEAD]
    L += [row(k, v) for k, v in win_explore.items()]
    L += ["", "## When to stop taking new trades — holdout", "", HEAD]
    L += [row(k, v) for k, v in win_hold.items()]

    # --- the verdict ---------------------------------------------------------
    base_name = EXITS[0][0]
    best = max((n for n, _ in EXITS), key=lambda n: ex_explore[n]["profit_pct"])
    floor = noise_floor(list(ex_explore.values()), len(EXITS))
    gain_h = ex_hold[best]["profit_pct"] - ex_hold[base_name]["profit_pct"]
    gain_e = ex_explore[best]["profit_pct"] - ex_explore[base_name]["profit_pct"]

    L += ["", "## Verdict", ""]
    L.append(f"Best on the explore dates: **{best}** "
             f"({ex_explore[best]['profit_pct']:+.1f}% against "
             f"{ex_explore[base_name]['profit_pct']:+.1f}% for the rule as it "
             f"trades now).")
    L.append("")
    L.append(f"On the holdout it made **{ex_hold[best]['profit_pct']:+.1f}%** "
             f"against **{ex_hold[base_name]['profit_pct']:+.1f}%** — a "
             f"difference of **{gain_h:+.1f}%**.")
    L.append("")

    # The order of these checks is the point. An earlier version of this
    # project twice announced that something "held up" while the number it
    # was describing was negative, so the all-negative case is tested FIRST.
    both_losing = (ex_hold[best]["profit_pct"] < 0
                   and ex_hold[base_name]["profit_pct"] < 0)
    if both_losing:
        L.append(f"- **Both still lose money.** {best} loses less, which is "
                 f"not the same as making any. Nothing here has been shown to "
                 f"turn this rule profitable.")
    if gain_h <= 0:
        L.append(f"- **It did not survive the holdout.** It gained "
                 f"{gain_e:+.1f}% on the dates that chose it and "
                 f"{gain_h:+.1f}% on the dates that did not. That is what "
                 f"picking the luckiest of {len(EXITS)} looks like.")
    elif gain_h < floor:
        L.append(f"- **Inside the noise floor.** With {len(EXITS)} variants "
                 f"tried, a gap of {floor:.1f}% is expected from luck alone; "
                 f"this one is {gain_h:+.1f}%.")
    elif both_losing:
        # Reaching here means the gap is real but both sides are under water.
        # Saying "clears the noise floor" alone would read as an endorsement
        # of a rule that loses money, which is the mistake this project has
        # already made twice.
        L.append(f"- The {gain_h:+.1f}% gap clears the {floor:.1f}% noise "
                 f"floor, so the improvement looks real - but it is damage "
                 f"control on a losing rule, not an edge.")
    else:
        L.append(f"- Clears the {floor:.1f}% noise floor for {len(EXITS)} "
                 f"variants, on dates it was not chosen on. That is the "
                 f"strongest form of evidence this project produces.")

    wb = max(win_hold, key=lambda k: win_hold[k]["profit_pct"])
    L.append(f"- Best entry cutoff on the holdout: **{wb}** "
             f"({win_hold[wb]['profit_pct']:+.1f}%), against "
             f"{win_hold['no cutoff']['profit_pct']:+.1f}% with no cutoff.")

    data_out = {
        "explore": {n: {k: v for k, v in ex_explore[n].items() if k != "trades"}
                    for n, _ in EXITS},
        "holdout": {n: {k: v for k, v in ex_hold[n].items() if k != "trades"}
                    for n, _ in EXITS},
        "windows": {k: {kk: vv for kk, vv in v.items() if kk != "trades"}
                    for k, v in win_hold.items()},
        "best_on_explore": best, "holdout_gain": gain_h, "noise_floor": floor,
    }
    return "\n".join(L), data_out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--universe", default="bigtech")
    ap.add_argument("--symbols", default="")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or UNIVERSES.get(args.universe) or UNIVERSES["bigtech"])
    md = MarketData(Credentials.from_env(), feed="iex")
    # op.fetch is what every study that has actually finished uses: it drops
    # symbols that come back empty or too thin to replay, which a direct
    # intraday_bars call does not, and one empty frame is enough to crash the
    # date split downstream.
    try:
        data = op.fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("could not fetch bars: %s", exc)
        return 1
    if not data:
        log.error("no usable price history came back for %s", ", ".join(symbols))
        return 1
    log.info("usable history: %d symbols, %d bars",
             len(data), sum(len(d) for d in data.values()))
    text, blob = sweep(data)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "exitsweep.md").write_text(text)
    (REPORTS / "exitsweep.json").write_text(json.dumps(blob, indent=2))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
