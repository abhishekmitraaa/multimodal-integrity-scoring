"""Evidence report for one participant: practice baseline → each exam checked against it (D-036).

No fused integrity score: S needs a fusion model fitted on labelled study data, which does not
exist yet (SPEC 7.4, 8). The report lists each piece of evidence with a plain verdict. A session
is "review" if any rule fires, "insufficient_data" if the keystroke check could not run and nothing
fired, and otherwise "no_review_flags" (SPEC 8.4). Rules and thresholds are in
config/scoring.yaml → report; they are hand-set, not calibrated. A flag means a person should
look, never that misconduct happened (SPEC 10.8).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
from numpy.typing import NDArray

from integrity_ml.ast_features import ast_timeline
from integrity_ml.session_features import Habits, enrollment_windows, exam_windows, session_signals

FALSE_FLAG_NOTE = (
    "Accessibility needs and assistive technology, injury, fatigue, mood and stress, a different keyboard or "
    "device, input methods and simple unfamiliarity can all change how someone types and cause false flags. "
    "A flag only means \"a human should look\". It is not evidence of misconduct."
)
TRANSCRIPTION_NOTE = (
    "The baseline comes from practice tasks where the code was shown and typed (D-035). Composing your own "
    "code usually has more pauses and corrections than copying, so some difference from the baseline is expected."
)


class Reference(Protocol):
    g: int
    genuine: dict[str, float]
    eer_threshold: float


class Model(Protocol):
    def embed(self, windows: Sequence[NDArray[np.float32]]) -> NDArray[np.float32]: ...
    def reference(self, g: int) -> Any: ...


SessionEvents = Mapping[str, Any]   # {"session_id", "kind", "problem_id", "closed", "events": [...]}


def _finding(fid: str, status: str, title: str, detail: str) -> dict[str, str]:
    return {"id": fid, "status": status, "title": title, "detail": detail}


def _round(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(float(v), n)


def _habits_dict(h: Habits | None) -> dict[str, Any] | None:
    return None if h is None else {k: _round(v) if isinstance(v, float) else v for k, v in asdict(h).items()}


def _mean_habits(items: Sequence[Habits]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("interval_cv", "pause_share_2s", "revisions_per_100", "chars_per_minute"):
        vals = [getattr(h, key) for h in items if getattr(h, key) is not None]
        out[key] = _round(float(np.mean(vals))) if vals else None
    out["keystrokes"] = int(sum(h.keystrokes for h in items))
    out["typed_chars"] = int(sum(h.typed_chars for h in items))
    return out


def build_report(pseudonym: str, sessions: Sequence[SessionEvents], model: Model | None, model_note: str,
                 cfg: Mapping[str, Any]) -> dict[str, Any]:
    """cfg: {"report": scoring.report, "m", "stride", "clip_s", "g_min", "large_insert_chars", "coupling_s",
    "ast": features.ast}."""
    rules = cfg["report"]
    # Stages (D-038): practice tasks build the baseline; the check task is held out and tested against it.
    practice = [s for s in sessions if s["kind"] == "practice" and s["closed"] and s.get("stage", "baseline") == "baseline"]
    # Only the first submitted check counts (one check per participant; a retake cannot replace it).
    checks = sorted((s for s in sessions if s.get("stage") == "check" and s["closed"]),
                    key=lambda s: s.get("closed_at") or 0.0)[:1]
    exams = [s for s in sessions if s["kind"] == "exam"]

    # ---- baseline from the closed practice sessions
    windows: list[NDArray[np.float32]] = []
    practice_rows, practice_habits = [], []
    for s in practice:
        sig = session_signals(s["events"], cfg["large_insert_chars"], cfg["coupling_s"])
        w = enrollment_windows(sig.keystrokes, cfg["m"], cfg["clip_s"])
        windows += w
        if sig.habits:
            practice_habits.append(sig.habits)
        practice_rows.append({"session_id": s["session_id"], "problem_id": s["problem_id"],
                              "keystrokes": len(sig.keystrokes), "windows": len(w)})
    prototype = model.embed(windows).mean(axis=0) if model is not None and len(windows) >= cfg["g_min"] else None
    baseline_status = "none" if not practice else ("ready" if len(windows) >= cfg["g_min"] else "insufficient")
    baseline = {
        "status": baseline_status, "practice_sessions": practice_rows, "windows": len(windows),
        "windows_needed": cfg["g_min"], "habits": _mean_habits(practice_habits) if practice_habits else None,
        "note": TRANSCRIPTION_NOTE,
    }
    baseline["check"] = _check_report(checks, model, prototype, len(windows), cfg, rules)

    # ---- each exam against it
    exam_reports = [_exam_report(s, model, prototype, len(windows), baseline, baseline["check"], cfg, rules) for s in exams]
    states = [e["state"] for e in exam_reports if e["closed"]]
    overall = ("review" if "review" in states else "insufficient_data" if "insufficient_data" in states
               else "no_review_flags" if states else "no_exam_yet")
    return {
        "pseudonym": pseudonym,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {"available": model is not None, "note": model_note},
        "baseline": baseline,
        "exams": exam_reports,
        "overall": {"state": overall, "reasons": [r for e in exam_reports for r in e["reasons"]]},
        "no_score_note": "No single integrity score is shown: it needs a fusion model fitted on labelled study data (P3, after data collection).",
        "false_flag_note": FALSE_FLAG_NOTE,
    }


def _distances(model: Model, prototype: NDArray[np.float32], windows: Sequence[NDArray[np.float32]]) -> NDArray[np.float64]:
    return np.linalg.norm(model.embed(list(windows)).astype(np.float64) - prototype.astype(np.float64), axis=1)


def _population_threshold(model: Model, g: int, rules: Mapping[str, Any]) -> tuple[float, Any]:
    ref = model.reference(g)
    return float(ref.genuine[rules["keystroke_threshold"].split("_")[1]]), ref


def _check_report(checks: Sequence[SessionEvents], model: Model | None, prototype: NDArray[np.float32] | None, g: int,
                  cfg: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """The baseline check (D-038): new typing by the same person, compared with the baseline.

    confirmed      most check windows are within the same-person range: the baseline describes this
                   person, and their largest check distance (capped at check_cap x the reference line)
                   becomes their personal line for the exam.
    not_confirmed  most check windows are outside it. The baseline may be unreliable, or the check may
                   have been typed by someone else or deliberately differently. Nothing is switched off:
                   it becomes a finding for a person to look at, and the exam is still compared with the
                   reference line (security review: a failed check must not disable detection).
    """
    if not checks:
        return {"status": "not_done", "detail": "The baseline check has not been done yet."}
    if model is None or prototype is None:
        return {"status": "unavailable", "detail": "The check needs the keystroke model and a ready baseline."}
    keys = [k for s in checks for k in session_signals(s["events"], cfg["large_insert_chars"], cfg["coupling_s"]).keystrokes]
    wins = [w for w, _ in exam_windows(keys, cfg["m"], cfg["stride"], cfg["clip_s"])]
    if not wins:
        return {"status": "unavailable", "detail": f"The check had fewer than {cfg['m']} key presses."}
    population, _ = _population_threshold(model, g, rules)
    dist = _distances(model, prototype, wins)
    above = float((dist > population).mean())
    confirmed = above < rules["check_mismatch_share"]
    personal = min(float(dist.max()) * float(rules["check_margin"]), population * float(rules["check_cap"]))
    within = len(wins) - int(round(above * len(wins)))
    return {
        "closed_at": checks[0].get("closed_at"),
        "status": "confirmed" if confirmed else "not_confirmed",
        "windows": [round(float(d), 3) for d in dist],
        "population_threshold": round(population, 3),
        "personal_threshold": round(personal, 3) if confirmed else None,
        "share_above": round(above, 2),
        "detail": (f"The check typing matches the practice typing: {within} of {len(wins)} windows are within the usual "
                   f"same-person range. The baseline is confirmed."
                   if confirmed else
                   f"The check typing does not match the practice typing ({round(100 * above)}% of {len(wins)} windows are "
                   f"outside the usual same-person range). The baseline may not describe this person well, or the check "
                   f"was typed differently. A person should look; the exam is still compared with the reference range."),
    }


def _exam_report(s: SessionEvents, model: Model | None, prototype: NDArray[np.float32] | None, g: int,
                 baseline: Mapping[str, Any], check: Mapping[str, Any], cfg: Mapping[str, Any],
                 rules: Mapping[str, Any]) -> dict[str, Any]:
    sig = session_signals(s["events"], cfg["large_insert_chars"], cfg["coupling_s"])
    ins, hab = sig.insertions, sig.habits
    starts = [e["t_client_us"] for e in s["events"] if e.get("t_client_us") is not None]
    t0 = min(starts) / 1e6 if starts else 0.0      # times in the report: seconds since the exam started
    assert ins is not None and hab is not None
    findings: list[dict[str, str]] = []
    keystroke: dict[str, Any] = {"available": False}

    # 1. Keystroke rhythm against the baseline
    wins = exam_windows(sig.keystrokes, cfg["m"], cfg["stride"], cfg["clip_s"])
    if model is None:
        findings.append(_finding("keystroke", "unavailable", "Typing rhythm vs baseline", "The keystroke model is not installed on this server."))
    elif prototype is None:
        findings.append(_finding("keystroke", "unavailable", "Typing rhythm vs baseline",
                                 f"Not enough practice typing for a baseline: {baseline['windows']} of {baseline['windows_needed']} windows of {cfg['m']} key presses."))
    elif not wins:
        findings.append(_finding("keystroke", "unavailable", "Typing rhythm vs baseline",
                                 f"The exam has fewer than {cfg['m']} key presses, so there is no window to compare."))
    else:
        population, ref = _population_threshold(model, g, rules)
        # The personal line counts only for a confirmed check submitted before this exam started.
        before = check.get("closed_at") is None or s.get("created_at") is None or check["closed_at"] <= s["created_at"]
        personal = check.get("personal_threshold") if check["status"] == "confirmed" and before else None
        threshold = max(population, personal) if personal is not None else population
        dist = _distances(model, prototype, [w for w, _ in wins])
        above = float((dist > threshold).mean())
        keystroke = {"available": True, "g": g, "threshold": round(threshold, 3), "population_threshold": round(population, 3),
                     "personal_threshold": personal, "eer_threshold": round(float(ref.eer_threshold), 3),
                     "windows": [{"t": round(t - t0, 1), "distance": round(float(d), 3)} for (_, t), d in zip(wins, dist)],
                     "share_above": round(above, 2)}
        mismatch = above >= rules["keystroke_mismatch_share"] and len(wins) >= rules["keystroke_mismatch_min_windows"]
        line = ("this person's own normal range from the baseline check" if personal is not None and personal > population
                else "95% of same-person comparisons in the reference data")
        caveat = ("" if personal is not None else
                  " (No usable baseline check, so only the reference-data range is used.)")
        findings.append(_finding(
            "keystroke", "flag" if mismatch else "ok", "Typing rhythm vs baseline",
            f"{round(100 * above)}% of {len(wins)} exam windows are further from this person's practice typing than {line}. "
            + ("That is unusual for the same person." if mismatch else "That is within the usual range for the same person.") + caveat))

    # 1b. The baseline check itself (D-038): a mismatch is for a person to look at, never a switch-off.
    if check["status"] == "not_confirmed":
        findings.append(_finding("baseline_check", "flag", "Baseline check did not match", str(check["detail"])))

    # 2. Pastes from outside the editor
    ext = ins.external_paste_chars
    findings.append(_finding("external_paste", "flag" if ext >= rules["external_paste_min_chars"] else "ok",
                             "Pastes from outside the editor",
                             f"{ext} characters pasted with no matching copy inside this session." if ext else "None."))
    # 3. Left the window, then pasted
    if ins.away_then_external_paste:
        findings.append(_finding("away_then_paste", "flag", "Pasted soon after returning to the window",
                                 f"{len(ins.away_then_external_paste)} external paste(s) within {cfg['coupling_s']:g} s of returning to the window."))
    # 4. Share of code that was not typed
    inserted = ins.typed_chars + ins.untyped_chars
    share = ins.untyped_chars / inserted if inserted else 0.0
    untyped_flag = share >= rules["untyped_share"] and ins.untyped_chars >= rules["untyped_min_chars"]
    findings.append(_finding("untyped", "flag" if untyped_flag else "ok", "Code that was not typed",
                             f"{ins.untyped_chars} of {inserted} inserted characters ({round(100 * share)}%) came from paste or other non-typing edits."))
    # 5. Reconciliation: text without matching key presses (D-026)
    recon = len(ins.unexplained_large_inserts) + (1 if ins.typed_chars_beyond_keystrokes >= rules["typed_beyond_keystrokes_min"] else 0)
    findings.append(_finding("reconciliation", "flag" if recon else "ok", "Code without matching key presses",
                             (f"{len(ins.unexplained_large_inserts)} large insertion(s) with no paste or key presses behind them; "
                              f"{ins.typed_chars_beyond_keystrokes} 'typed' characters beyond the key presses recorded.")
                             if recon else "Every insertion is backed by key presses or a recorded paste."))
    # 6. Machine-like rhythm
    machine = hab.interval_cv is not None and hab.interval_cv < rules["machine_rhythm_cv"] and hab.keystrokes >= rules["machine_rhythm_min_keystrokes"]
    if hab.interval_cv is not None:
        findings.append(_finding("machine_rhythm", "flag" if machine else "ok", "Evenness of typing rhythm",
                                 f"Key-interval spread {hab.interval_cv:.2f}: unusually even, as an auto-typer would be (people vary far more)."
                                 if machine else f"Key-interval spread {hab.interval_cv:.2f}: the normal unevenness of human typing (an auto-typer is near 0)."))
    # 7. Context only, never a flag by itself
    findings.append(_finding("away", "info", "Time away from the window", f"{round(ins.away_seconds)} s with the browser window out of focus."))
    # 8. AST jumps (SPEC 6.3): dashboard evidence, not a flag (pastes and unexplained inserts behind them are rules 2-5)
    a = cfg["ast"]
    tl = ast_timeline(s["events"], int(a["jump_min_nodes"]), int(a["jump_max_keydowns"]), int(a["max_snapshots"]),
                      int(a["max_parse_chars"]))
    at = ", ".join(f"{int((j.t - t0) // 60)}:{int((j.t - t0) % 60):02d}" for j in tl.jumps)
    findings.append(_finding(
        "ast_jump", "info", "Code structure that arrived without typing",
        (f"{len(tl.jumps)} time(s) at least {a['jump_min_nodes']} pieces of code structure appeared between two snapshots "
         f"with fewer than {a['jump_max_keydowns']} key presses (at {at})." if tl.jumps else "None.")
        + (f" Only the first {tl.snapshots} snapshots were checked." if tl.truncated else "")))

    flags = [f for f in findings if f["status"] == "flag"]
    keystroke_unavailable = any(f["id"] == "keystroke" and f["status"] == "unavailable" for f in findings)
    state = "review" if flags else ("insufficient_data" if keystroke_unavailable else "no_review_flags")
    return {
        "session_id": s["session_id"], "problem_id": s["problem_id"], "closed": s["closed"],
        "duration_s": round(sig.duration_s), "state": state,
        "reasons": [f"{f['title']}: {f['detail']}" for f in flags],
        "findings": findings, "keystroke": keystroke,
        "habits": {"exam": _habits_dict(hab), "baseline": baseline["habits"]},
        "pastes": [{"t": round(p.t - t0, 1), "chars": p.chars, "provenance": p.provenance} for p in ins.pastes],
        "ast_jumps": [{"t": round(j.t - t0, 1), "added_nodes": j.added_nodes, "keydowns": j.keydowns} for j in tl.jumps],
    }
