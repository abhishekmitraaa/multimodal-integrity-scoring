"""Real-keyboard check report (docs/keycheck.md). DEVELOPMENT DATA ONLY.

Reads the keycheck.v1 files saved by the #/keycheck page. For each run (one person, keyboard and
browser) it reports:

- overlapping keys: the share of consecutive keystrokes with a negative IL (the next key pressed
  before the previous one was released), with and without modifier keys;
- held keys: auto-repeat delay and interval, and whether repeats carry the `repeat` flag;
- event.timeStamp against performance.now(): the dispatch lag, whether both use the same clock,
  and whether timeStamp is taken before dispatch (task 4, where the page blocks its main thread).

The files are team members' test typing. They never enter a study dataset, and this report is not
a study result.

Usage: python -m integrity_eval.keycheck <folder with *.dev.json> --out <report.md>
(--out writes UTF-8; without it the report goes to stdout. Both must be outside the repository.)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from integrity_ml.keystroke import KeyEvent, latencies, pair_keystrokes

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAT = "keycheck.v1"
MODIFIER_CODES = frozenset({
    "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight",
    "MetaLeft", "MetaRight", "CapsLock",
})
GRID_CANDIDATES_US = (100_000, 16_667, 1_000, 100, 20, 5, 1)


class KeycheckError(RuntimeError):
    pass


def load_config(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    data = yaml.safe_load((repo_root / "config" / "eval.yaml").read_text(encoding="utf-8"))
    return dict(data["keycheck"])


def _outside_repo(path: Path, repo_root: Path) -> Path:
    resolved, repo = path.resolve(), repo_root.resolve()
    if resolved == repo or repo in resolved.parents:
        raise KeycheckError(f"{resolved} is inside the repository; keep keycheck files in the data root")
    return resolved


def load_runs(folder: Path, repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Load every *.dev.json file in folder. Refuses anything that is not development data."""
    resolved = _outside_repo(folder, repo_root)
    runs = []
    for path in sorted(resolved.glob("*.dev.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("format") != FORMAT:
            raise KeycheckError(f"{path.name}: not a {FORMAT} file")
        if run.get("dataset") != "development" or run.get("not_for_study") is not True:
            raise KeycheckError(f"{path.name}: not labelled as development data")
        run["_file"] = path.name
        runs.append(run)
    if not runs:
        raise KeycheckError(f"no *.dev.json files in {resolved}")
    if len({bool(r["synthetic"]) for r in runs}) > 1:
        raise KeycheckError("refusing to mix synthetic and real keycheck files in one report")
    return runs


def timestamp_grid_us(values_ms: Sequence[float]) -> int:
    """Coarsest candidate grid (µs) that every value sits on, within 0.01 µs; 0 if none does."""
    for grid in GRID_CANDIDATES_US:
        if all(abs(v * 1000 - round(v * 1000 / grid) * grid) < 0.01 for v in values_ms):
            return grid
    return 0


def _task_events(run: dict[str, Any], tasks: Sequence[str]) -> list[dict[str, Any]]:
    return [e for e in run["events"] if e["task"] in tasks]


def _key_events(events: Sequence[dict[str, Any]]) -> list[KeyEvent]:
    return [KeyEvent(e["type"], e["code"], round(e["ts"] * 1000), bool(e["rep"])) for e in events]


@dataclass(frozen=True)
class OverlapStats:
    keystrokes: int
    unmatched: int
    pairs: int
    overlap_frac: float
    pairs_without_modifiers: int
    overlap_frac_without_modifiers: float
    median_negative_il_ms: float | None
    top_pairs: list[tuple[str, int]]


def overlap_stats(run: dict[str, Any], tasks: Sequence[str], top: int) -> OverlapStats:
    """Negative IL per task (keys never pair across tasks), pooled over the given tasks."""
    keystrokes = unmatched = 0
    il_all: list[float] = []
    il_plain: list[float] = []
    overlapping: Counter[str] = Counter()
    for task in tasks:
        ks, stats = pair_keystrokes(_key_events(_task_events(run, [task])))
        keystrokes += stats.keystrokes
        unmatched += stats.unmatched_keydowns + stats.unmatched_keyups
        il = latencies(ks).il_ms
        for i, value in enumerate(il):
            first, second = ks[i].code, ks[i + 1].code
            il_all.append(float(value))
            if first not in MODIFIER_CODES and second not in MODIFIER_CODES:
                il_plain.append(float(value))
            if value < 0:
                overlapping[f"{first}→{second}"] += 1
    negative = [v for v in il_all if v < 0]
    return OverlapStats(
        keystrokes=keystrokes,
        unmatched=unmatched,
        pairs=len(il_all),
        overlap_frac=len(negative) / len(il_all) if il_all else 0.0,
        pairs_without_modifiers=len(il_plain),
        overlap_frac_without_modifiers=sum(v < 0 for v in il_plain) / len(il_plain) if il_plain else 0.0,
        median_negative_il_ms=float(np.median(negative)) if negative else None,
        top_pairs=overlapping.most_common(top),
    )


@dataclass(frozen=True)
class HoldStats:
    code: str
    holds: int
    repeats: int
    initial_delay_ms: float | None
    repeat_interval_ms: float | None
    missing_repeat_flag: int
    keyups_during_hold: int


def hold_stats(run: dict[str, Any]) -> list[HoldStats]:
    """Auto-repeat per key in the held-keys task.

    A hold starts at a non-repeat keydown. Repeat keydowns join it. A keyup ends it unless another
    repeat keydown follows (some platforms send a keyup per repeat; those are counted). A second
    non-repeat keydown with no keyup in between is a repeat that lacks the flag.
    """
    by_code: dict[str, list[dict[str, Any]]] = {}
    for e in _task_events(run, ["hold"]):
        by_code.setdefault(e["code"], []).append(e)
    out = []
    for code, events in by_code.items():
        holds: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        pending_keyup = False
        for e in events:
            if e["type"] == "keyup":
                pending_keyup = current is not None
                continue
            if e["rep"] or (current is not None and not pending_keyup):
                if current is None:
                    continue
                if pending_keyup:
                    current["keyups_during"] += 1
                if not e["rep"]:
                    current["missing_flag"] += 1
                current["reps"].append(e["ts"])
            else:
                current = {"start": e["ts"], "reps": [], "keyups_during": 0, "missing_flag": 0}
                holds.append(current)
            pending_keyup = False
        delays = [h["reps"][0] - h["start"] for h in holds if h["reps"]]
        intervals = [d for h in holds for d in np.diff(h["reps"]).tolist()]
        out.append(HoldStats(
            code=code,
            holds=len(holds),
            repeats=sum(len(h["reps"]) for h in holds),
            initial_delay_ms=float(np.median(delays)) if delays else None,
            repeat_interval_ms=float(np.median(intervals)) if intervals else None,
            missing_repeat_flag=sum(h["missing_flag"] for h in holds),
            keyups_during_hold=sum(h["keyups_during"] for h in holds),
        ))
    return out


@dataclass(frozen=True)
class LagStats:
    events: int
    median_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    min_ms: float | None


def lag_stats(events: Sequence[dict[str, Any]]) -> LagStats:
    """Lag = performance.now() on entry to the handler minus event.timeStamp."""
    lag = np.array([e["now"] - e["ts"] for e in events], dtype=np.float64)
    if lag.size == 0:
        return LagStats(0, None, None, None, None)
    return LagStats(int(lag.size), float(np.median(lag)), float(np.percentile(lag, 95)),
                    float(lag.max()), float(lag.min()))


@dataclass(frozen=True)
class JankStats:
    keydowns: int
    inside_frac: float
    lag: LagStats
    verdict: str


def jank_stats(run: dict[str, Any], cfg: dict[str, Any]) -> JankStats:
    """Task 4: are keydowns pressed during a main-thread block stamped inside it?"""
    blocks = [(float(s), float(e)) for s, e in run["jank_blocks"]]
    keydowns = [e for e in _task_events(run, ["jank"]) if e["type"] == "keydown"]
    inside = [e for e in keydowns if any(s <= e["ts"] <= end for s, end in blocks)]
    frac = len(inside) / len(keydowns) if keydowns else 0.0
    lag = lag_stats(keydowns)
    if len(keydowns) < cfg["min_jank_keydowns"]:
        verdict = "not enough key presses in task 4"
    elif frac >= cfg["input_time_min_inside_frac"]:
        verdict = "input time: timeStamp is taken before dispatch"
    elif frac <= cfg["dispatch_time_max_inside_frac"] and (lag.median_ms or 0.0) <= cfg["dispatch_time_max_lag_ms"]:
        verdict = "dispatch time: timeStamp is taken when the handler runs"
    else:
        verdict = "inconclusive"
    return JankStats(len(keydowns), frac, lag, verdict)


def _trusted_share(run: dict[str, Any]) -> str:
    """Share of events with isTrusted = true. Not a defence (SPEC 4.5): OS-level injection is trusted too."""
    events = run["events"]
    return f"{sum(bool(e['trusted']) for e in events) / len(events):.0%}" if events else "–"


def _fmt(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _run_label(run: dict[str, Any]) -> str:
    browser = run["browser"]
    return f"{run['tester']} · {run['keyboard_type']} · {browser['brand']} {browser['version']}"


def render(runs: Sequence[dict[str, Any]], cfg: dict[str, Any]) -> str:
    synthetic = bool(runs[0]["synthetic"])
    normal = list(cfg["normal_tasks"])
    lines = [
        "# Real-keyboard check report",
        "",
        "**DEVELOPMENT DATA.** Team members' test typing on the `#/keycheck` page. Not a study result "
        "and never part of a study dataset.",
    ]
    if synthetic:
        lines += ["", "**SYNTHETIC.** These files come from automated input, not real keyboards."]
    lines += [
        "",
        f"Files: {len(runs)}. Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Thresholds: `config/eval.yaml` → `keycheck`.",
        "",
        "## Runs",
        "",
        "| # | Tester | Keyboard | OS | Browser | Isolated | Timer step (µs) | timeStamp grid (µs) | isTrusted | File |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, run in enumerate(runs, 1):
        grid = timestamp_grid_us([e["ts"] for e in run["events"]]) if run["events"] else 0
        keyboard = run["keyboard_type"] + (f" ({run['keyboard_label']})" if run.get("keyboard_label") else "")
        lines.append(
            f"| {i} | {run['tester']} | {keyboard} | {run['os']} | {run['browser']['brand']} {run['browser']['version']} | "
            f"{'yes' if run['cross_origin_isolated'] else 'no'} | {run['timer_resolution_us']} | "
            f"{grid if grid else 'finer than 1'} | {_trusted_share(run)} | `{run['_file']}` |"
        )
    lines += [
        "",
        f"## Overlapping keys (negative IL), tasks {', '.join(normal)}",
        "",
        "IL is the time from releasing one key to pressing the next. It is negative when the next key "
        "goes down before the previous one comes up. \"Without modifiers\" leaves out every pair that "
        "involves Shift, Ctrl, Alt, Meta or CapsLock, since a held Shift always overlaps.",
        "",
        "| # | Keystrokes | Unmatched events | Pairs | IL < 0 | Pairs without modifiers | IL < 0 without modifiers | Median negative IL (ms) | Most frequent overlaps |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, run in enumerate(runs, 1):
        o = overlap_stats(run, normal, int(cfg["top_overlap_pairs"]))
        top = ", ".join(f"{pair} ×{n}" for pair, n in o.top_pairs) or "–"
        lines.append(
            f"| {i} | {o.keystrokes} | {o.unmatched} | {o.pairs} | {o.overlap_frac:.1%} | "
            f"{o.pairs_without_modifiers} | {o.overlap_frac_without_modifiers:.1%} | {_fmt(o.median_negative_il_ms)} | {top} |"
        )
    lines += [
        "",
        "## Held keys (task 3)",
        "",
        "| # | Key | Holds | Repeats | Initial delay (ms) | Repeat interval (ms) | Repeats without the flag | Keyups during a hold |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, run in enumerate(runs, 1):
        stats = hold_stats(run)
        if not stats:
            lines.append(f"| {i} | – | 0 | – | – | – | – | – |")
        for hs in stats:
            lines.append(
                f"| {i} | {hs.code} | {hs.holds} | {hs.repeats} | {_fmt(hs.initial_delay_ms)} | "
                f"{_fmt(hs.repeat_interval_ms)} | {hs.missing_repeat_flag} | {hs.keyups_during_hold} |"
            )
    lines += [
        "",
        "## event.timeStamp against performance.now()",
        "",
        "Lag = `performance.now()` on entry to the handler minus `event.timeStamp`, over keydown and keyup "
        "events. A negative lag would mean the two do not share a clock. Task 4 blocks the page's main "
        "thread; the verdict follows the rule in `config/eval.yaml`.",
        "",
        "| # | Tasks 1–2: events | Lag median (ms) | p95 | max | min | Task 4: keydowns | Stamped inside a block | Task 4 lag median (ms) | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, run in enumerate(runs, 1):
        lag = lag_stats(_task_events(run, normal))
        jank = jank_stats(run, cfg)
        lines.append(
            f"| {i} | {lag.events} | {_fmt(lag.median_ms, 2)} | {_fmt(lag.p95_ms, 2)} | {_fmt(lag.max_ms, 2)} | "
            f"{_fmt(lag.min_ms, 3)} | {jank.keydowns} | {jank.inside_frac:.0%} | {_fmt(jank.lag.median_ms, 2)} | {jank.verdict} |"
        )
    lines += ["", "Runs: " + "; ".join(f"{i} = {_run_label(r)}" for i, r in enumerate(runs, 1)), ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-keyboard check report (development data only).")
    parser.add_argument("folder", type=Path, help="folder holding *.dev.json files (outside the repo)")
    parser.add_argument("--out", type=Path, help="write the report here as UTF-8 (outside the repo)")
    args = parser.parse_args(argv)
    try:
        runs = load_runs(args.folder)
        out = _outside_repo(args.out, REPO_ROOT) if args.out else None
    except KeycheckError as err:
        print(f"keycheck: {err}", file=sys.stderr)
        return 2
    report = render(runs, load_config())
    if out is not None:
        out.write_text(report, encoding="utf-8")
        print(f"keycheck: wrote {out}", file=sys.stderr)
    else:
        reconfigure = getattr(sys.stdout, "reconfigure", None)  # Windows pipes default to cp1252
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
