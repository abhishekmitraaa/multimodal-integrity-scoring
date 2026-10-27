"""Fusion pipeline dry run on SYNTHETIC sessions (SPEC 7.4, 8, 12.3). A test of the code, never a result.

Pipeline, each step the one the study will use:
1. Scoring ticks per exam session (SPEC 8.1): every 35 keydowns once a 70-key window exists, every
   paste, at least every 30 s, and at the end.
2. Raw evidence per tick through the real feature code: the keystroke distance of the latest window
   (within 120 s) to the user's practice prototype; process features over the trailing 120 s; the
   AST of the latest snapshot; clipboard and focus over the horizon.
3. Nested user-level CV (SPEC 12.3). In every fold, everything fitted from data uses training users
   only: the process scales s_k (pooled within-user SD), the AST references R_p and style
   statistics, the imputation medians (genuine training rows), C (inner folds, log loss) and tau
   (5% of out-of-fold genuine training sessions flagged).
4. Sign-constrained fusion (SPEC 7.4), EWMA on the logit and the session minimum (SPEC 8.3).
5. Pooled test-fold results: detection per attack, genuine false flags, time to detection,
   calibration (reliability, ECE, Brier), user-cluster bootstrap CIs (SPEC 12.5).

Every output says SYNTHETIC. The numbers describe a toy generator (integrity_eval.synthetic_sessions),
not people, and must never be reported as results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import yaml
from numpy.typing import NDArray

from integrity_ml import ast_features as ast
from integrity_ml.fusion import FusionModel, fit_fusion
from integrity_ml.process_features import ProcessConfig, baseline, pooled_within_sd, process_distance, process_features, vector
from integrity_ml.session_features import editor_keystrokes, enrollment_windows, exam_windows, insertions
from integrity_ml.smoothing import ewma_logit

from .manifest import REPO_ROOT, run_manifest
from .synthetic_sessions import ATTACKS, Session, generate

INPUTS = ("d_ks", "d_proc", "d_ast_h", "d_ast_s", "clip_ext_frac", "clip_ext_chars_log", "focus_loss_frac")
AVAILABILITY = ("ks_available", "ast_available")
BANNER = "SYNTHETIC: a test of the fusion pipeline on generated sessions. Not a result; never report these numbers."

# The SYNTHETIC exam solution every user types (the run-length task).
EXAM_TEXT = (
    "def rle(s):\n    out = []\n    i = 0\n    while i < len(s):\n        j = i\n"
    "        while j < len(s) and s[j] == s[i]:\n            j += 1\n"
    "        out.append(s[i] + str(j - i))\n        i = j\n    return ''.join(out)\n"
)


def _cfg(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def practice_texts() -> dict[str, str]:
    """The baseline-stage practice solutions, from the problem files the app uses."""
    out = {}
    for path in sorted((REPO_ROOT / "backend" / "problems").glob("*.yaml")):
        p = yaml.safe_load(path.read_text(encoding="utf-8"))
        if p.get("stage") == "baseline" and p.get("reference_solution"):
            out[p["id"]] = p["reference_solution"]
    return out


# ---------------------------------------------------------------- keystroke embedding

class StandInEmbedder:
    """Summary statistics of a window (hold and flight: mean, SD, median), NOT the P2 encoder.

    Used by tests and when no encoder file is given, so the pipeline runs without PyTorch.
    """

    name = "stand-in summary statistics (not the P2 encoder)"

    def embed(self, windows: Sequence[NDArray[np.float32]]) -> NDArray[np.float32]:
        if not windows:
            return np.zeros((0, 5), dtype=np.float32)
        x = np.stack(windows).astype(np.float64)
        hold, flight = x[:, :, 1], x[:, :-1, 2]
        return np.stack([hold.mean(1), hold.std(1), flight.mean(1), flight.std(1), np.median(flight, 1)], axis=1).astype(np.float32) * 10


def load_encoder(path: Path) -> Any:
    from integrity_ml.serving import KeystrokeModel

    model = KeystrokeModel(path, _cfg("models")["keystroke_encoder"])
    model.name = f"P2 TypeNet encoder {path.name} (sha256 {hashlib.sha256(path.read_bytes()).hexdigest()[:16]})"
    return model


# ---------------------------------------------------------------- raw evidence per tick

@dataclass
class RawTick:
    session: int
    uid: str
    attack: str               # genuine | A1 | A3b | A4
    t: float
    label: int                # 1 genuine; 0 once an attack has started
    ks: float | None
    proc: NDArray[np.float64]
    ast: ast.AstSummary | None
    ext_frac: float
    ext_chars: int
    focus_frac: float


def tick_times(events: Sequence[Mapping[str, Any]], every: int, first_after: int, max_interval_s: float) -> list[float]:
    ev = [e for e in events if e.get("t_client_us") is not None]
    downs = [e["t_client_us"] / 1e6 for e in ev if e["type"] == "keydown" and e["data"].get("target", "editor") == "editor"
             and not e["data"].get("rep")]
    t0, end = ev[0]["t_client_us"] / 1e6, ev[-1]["t_client_us"] / 1e6
    ticks = set(downs[first_after - 1::every]) | {e["t_client_us"] / 1e6 for e in ev if e["type"] == "paste"} | {end}
    out: list[float] = []
    last = t0
    for t in sorted(ticks):
        while t - last > max_interval_s:            # at least every max_interval_s while active
            last += max_interval_s
            out.append(last)
        out.append(t)
        last = t
    return out


def raw_ticks(s: Session, index: int, prototype: NDArray[np.float32] | None, embedder: Any,
              feat: Mapping[str, Any], scoring: Mapping[str, Any]) -> list[RawTick]:
    m, stride = int(feat["keystroke"]["window_keystrokes"]), int(feat["keystroke"]["exam_stride"])
    clip_s, max_age = feat["keystroke"]["latency_clip_ms"] / 1000, float(feat["keystroke"]["window_max_age_s"])
    horizon = float(feat["process"]["horizon_s"])
    pcfg = ProcessConfig.from_config(feat["process"])
    ev = s.events
    t0 = ev[0]["t_client_us"] / 1e6
    wins = exam_windows(editor_keystrokes(ev), m, stride, clip_s)
    win_t = np.array([t for _, t in wins])
    dist = (np.linalg.norm(embedder.embed([w for w, _ in wins]) - prototype, axis=1)
            if prototype is not None and wins else np.zeros(0))
    pastes = insertions(ev, 10**9, 10.0).pastes
    inserted = [(e["t_client_us"] / 1e6, int(e["data"]["ins_len"])) for e in ev if e["type"] == "content_change"]
    away: list[tuple[float, float]] = []
    start = None
    for e in ev:
        if e["type"] == "blur" and e["data"].get("target") == "window":
            start = e["t_client_us"] / 1e6
        elif e["type"] == "focus" and e["data"].get("target") == "window" and start is not None:
            away.append((start, e["t_client_us"] / 1e6))
            start = None
    snaps = [(e["t_client_us"] / 1e6, str(e["data"]["text"])) for e in ev if e["type"] == "snapshot"]
    parsed: dict[str, ast.AstSummary] = {}
    out = []
    for t in tick_times(ev, int(scoring["tick"]["every_keydowns"]), m, float(scoring["tick"]["max_interval_s"])):
        lo = t - horizon
        i = int(np.searchsorted(win_t, t, side="right")) - 1
        ks = float(dist[i]) if dist.size and i >= 0 and t - win_t[i] <= max_age else None
        text = next((x for tt, x in reversed(snaps) if tt <= t), None)
        if text is not None and text not in parsed:
            parsed[text] = ast.summarize(text)
        ext = sum(p.chars for p in pastes if p.provenance == "external" and lo < p.t <= t)
        ins = sum(n for tt, n in inserted if lo < tt <= t)
        span = min(horizon, t - t0) or 1.0
        gone = sum(max(0.0, min(b, t) - max(a, lo)) for a, b in away)
        out.append(RawTick(
            index, s.uid, s.label, t, 0 if s.onset_s is not None and t >= s.onset_s else 1, ks,
            vector(process_features(ev, pcfg, window=(lo, t))), parsed[text] if text is not None else None,
            ext / ins if ins else 0.0, ext, gone / span))
    return out


# ---------------------------------------------------------------- fold statistics and the design matrix

@dataclass
class FoldStats:
    s_k: NDArray[np.float64]
    b_u: dict[str, NDArray[np.float64]]
    r_exam: NDArray[np.float64]
    b_ast: dict[str, NDArray[np.float64]]
    style_exam: tuple[NDArray[np.float64], NDArray[np.float64]]
    z_practice: dict[str, list[NDArray[np.float64]]]


def _style_stats(summaries: Sequence[ast.AstSummary]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x = np.stack([s.style() for s in summaries])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(x, axis=0), np.nanstd(x, axis=0)


def fold_stats(train_users: set[str], practice: Mapping[str, Mapping[str, tuple[NDArray[np.float64], ast.AstSummary]]],
               exam_finals: Mapping[str, ast.AstSummary], authors: Mapping[str, ast.AstSummary], alpha: float) -> FoldStats:
    """Everything fitted from data, from training users only (plus author solutions for practice references)."""
    s_k = pooled_within_sd({u: [v for v, _ in practice[u].values()] for u in train_users})
    b_u = {u: baseline([v for v, _ in mods.values()]) for u, mods in practice.items()}
    r_exam = ast.reference([ast.smoothed(exam_finals[u].counts, alpha) for u in train_users])
    style_exam = _style_stats([exam_finals[u] for u in train_users])
    r_p, style_p = {}, {}
    for pid, author in authors.items():
        finals = [author] + [practice[u][pid][1] for u in train_users]
        r_p[pid] = ast.reference([ast.smoothed(f.counts, alpha) for f in finals])
        style_p[pid] = _style_stats(finals)
    b_ast = {u: ast.student_baseline([ast.tilt(ast.smoothed(practice[u][pid][1].counts, alpha), r_p[pid]) for pid in authors])
             for u in practice}
    z_practice = {u: [ast.style_z(practice[u][pid][1].style(), *style_p[pid]) for pid in authors] for u in practice}
    return FoldStats(s_k, b_u, r_exam, b_ast, style_exam, z_practice)


def design(ticks: Sequence[RawTick], st: FoldStats, alpha: float, min_nodes: int) -> NDArray[np.float64]:
    """Rows of INPUTS + AVAILABILITY; NaN where an input is unavailable (imputed later)."""
    rows = []
    for k in ticks:
        d_proc = process_distance(k.proc, st.b_u[k.uid], st.s_k)
        d_h = d_s = None
        if k.ast is not None and ast.available(k.ast, min_nodes):
            d_h = ast.jsd(ast.tilt(ast.smoothed(k.ast.counts, alpha), st.r_exam), st.b_ast[k.uid])
            d_s = ast.style_distance(ast.style_z(k.ast.style(), *st.style_exam), st.z_practice[k.uid])
        vals = [k.ks, d_proc, d_h, d_s, k.ext_frac, math.log1p(k.ext_chars), k.focus_frac]
        rows.append([np.nan if v is None else float(v) for v in vals] + [float(k.ks is not None), float(d_h is not None)])
    return np.array(rows, dtype=np.float64)


def impute(x: NDArray[np.float64], medians: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.where(np.isnan(x), medians, x)


def genuine_medians(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
    with warnings.catch_warnings():                    # an input never available in a fold: imputed as 0, said in coverage
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(np.where(y[:, None] == 1, x, np.nan), axis=0)
    return np.where(np.isnan(med), 0.0, med)


# ---------------------------------------------------------------- sessions, scores and the CV

def session_scores(model: FusionModel, x: NDArray[np.float64], ticks: Sequence[RawTick], lam: float) -> dict[int, tuple[NDArray[np.float64], NDArray[np.float64]]]:
    """session -> (tick times, smoothed scores)."""
    s = model.score(x)
    out: dict[int, tuple[list[float], list[float]]] = {}
    for k, v in zip(ticks, s):
        out.setdefault(k.session, ([], []))
        out[k.session][0].append(k.t)
        out[k.session][1].append(float(v))
    return {i: (np.array(t), ewma_logit(np.array(v), lam)) for i, (t, v) in out.items()}


def _logloss(p: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _folds(users: Sequence[str], k: int, rng: np.random.Generator) -> list[set[str]]:
    order = list(rng.permutation(list(users)))
    return [set(order[i::k]) for i in range(k)]


def run(cfg: Mapping[str, Any], seed: int, embedder: Any, users: int | None = None,
        outer_folds: int | None = None, inner_folds: int | None = None, resamples: int | None = None) -> dict[str, Any]:
    feat, scoring, models, ev_cfg = _cfg("features"), _cfg("scoring"), _cfg("models"), _cfg("eval")
    d = dict(cfg)
    n_users = users or int(d["users"])
    k_out, k_in = outer_folds or int(d["outer_folds"]), inner_folds or int(d["inner_folds"])
    n_boot = resamples or int(ev_cfg["bootstrap"]["resamples"])
    alpha, min_nodes = float(feat["ast"]["laplace_alpha"]), int(feat["ast"]["min_named_nodes"])
    lam, ffr = float(scoring["smoothing"]["lambda"]), float(scoring["target_false_flag_rate"])
    c_grid = [float(c) for c in models["fusion"]["c_grid"]]
    m, clip_s, g_min = int(feat["keystroke"]["window_keystrokes"]), feat["keystroke"]["latency_clip_ms"] / 1000, int(models["enrollment"]["g_min"])
    pcfg = ProcessConfig.from_config(feat["process"])
    texts = practice_texts()

    _, sessions = generate(n_users, texts, EXAM_TEXT, d, seed)
    uids = sorted({s.uid for s in sessions})

    # per user: practice process vectors, practice finals, prototype; genuine exam finals
    practice: dict[str, dict[str, tuple[NDArray[np.float64], ast.AstSummary]]] = {u: {} for u in uids}
    windows: dict[str, list[NDArray[np.float32]]] = {u: [] for u in uids}
    exam_finals: dict[str, ast.AstSummary] = {}
    for s in sessions:
        final = ast.summarize(next(str(e["data"]["text"]) for e in reversed(s.events) if e["type"] == "snapshot"))
        if s.kind == "practice":
            practice[s.uid][s.problem_id] = (vector(process_features(s.events, pcfg)), final)
            windows[s.uid] += enrollment_windows(editor_keystrokes(s.events), m, clip_s)
        elif s.label == "genuine":
            exam_finals[s.uid] = final
    authors = {pid: ast.summarize(t) for pid, t in texts.items()}
    prototypes = {u: (embedder.embed(w).mean(axis=0) if len(w) >= g_min else None) for u, w in windows.items()}

    exams = [s for s in sessions if s.kind == "exam"]
    ticks: list[RawTick] = []
    for i, s in enumerate(exams):
        ticks += raw_ticks(s, i, prototypes[s.uid], embedder, feat, scoring)
    y_all = np.array([k.label for k in ticks], dtype=np.float64)
    names, mask = INPUTS + AVAILABILITY, [True] * len(INPUTS) + [False] * len(AVAILABILITY)

    def fit_on(train: set[str], c: float) -> Callable[[set[str]], tuple[FusionModel, NDArray[np.float64], list[int]]]:
        st = fold_stats(train, practice, exam_finals, authors, alpha)
        tr = [i for i, k in enumerate(ticks) if k.uid in train]
        x_tr = design([ticks[i] for i in tr], st, alpha, min_nodes)
        med = genuine_medians(x_tr, y_all[tr])
        model = fit_fusion(impute(x_tr, med), y_all[tr], names, mask, c=c)

        def predict(on: set[str]) -> tuple[FusionModel, NDArray[np.float64], list[int]]:
            idx = [i for i, k in enumerate(ticks) if k.uid in on]
            return model, impute(design([ticks[i] for i in idx], st, alpha, min_nodes), med), idx
        return predict

    rng = np.random.default_rng(seed)
    outcomes: list[dict[str, Any]] = []
    tick_p, tick_y, fold_info = [], [], []
    for fold, test in enumerate(_folds(uids, k_out, rng)):
        train_users = set(uids) - test
        inner = _folds(sorted(train_users), k_in, rng)
        loss = {}
        for c in c_grid:                                     # C by inner-fold log loss over ticks
            p_all, y_in = [], []
            for val in inner:
                model, x, idx = fit_on(train_users - val, c)(val)
                p_all.append(model.score(x))
                y_in.append(y_all[idx])
            loss[c] = _logloss(np.concatenate(p_all), np.concatenate(y_in))
        best = min(c_grid, key=lambda c: (loss[c], c))
        oof = []                                             # tau: out-of-fold genuine training sessions
        for val in inner:
            model, x, idx = fit_on(train_users - val, best)(val)
            for sid, (_, sm) in session_scores(model, x, [ticks[i] for i in idx], lam).items():
                if exams[sid].label == "genuine":
                    oof.append(float(sm.min()))
        tau = float(np.quantile(oof, ffr))
        model, x, idx = fit_on(train_users, best)(test)
        tick_p.append(model.score(x))
        tick_y.append(y_all[idx])
        for sid, (tt, sm) in session_scores(model, x, [ticks[i] for i in idx], lam).items():
            s = exams[sid]
            crossed = tt[sm < tau]
            onset = s.onset_s if s.onset_s is not None else tt[0]
            outcomes.append({"uid": s.uid, "attack": s.label, "flagged": bool(crossed.size),
                             "ttd_s": float(max(0.0, crossed[0] - onset)) if crossed.size else None,
                             "session_score": float(sm.min())})
        fold_info.append({"fold": fold, "test_users": len(test), "c": best, "tau": round(tau, 4),
                          "weights": {n: round(float(w), 4) for n, w in zip(names, model.coef)},
                          "pinned_at_zero": [n for n, w, is_d in zip(names, model.coef, mask) if is_d and w == 0.0]})

    p, yv = np.concatenate(tick_p), np.concatenate(tick_y)
    return {
        "synthetic": True, "banner": BANNER, "dataset_id": d["dataset_id"], "users": n_users,
        "embedder": embedder.name, "folds": fold_info,
        "coverage": {"ks_available": float(np.mean([k.ks is not None for k in ticks])),
                     "ast_available": float(np.mean([k.ast is not None and ast.available(k.ast, min_nodes) for k in ticks])),
                     "ticks": len(ticks)},
        "sessions": _session_summary(outcomes, n_boot, seed),
        "calibration": calibration(p, yv),
        "grammar": ast.grammar_info(),
    }


def _session_summary(outcomes: Sequence[Mapping[str, Any]], resamples: int, seed: int) -> dict[str, Any]:
    out = {}
    users = sorted({o["uid"] for o in outcomes})
    rng = np.random.default_rng(seed + 1)
    picks = rng.integers(0, len(users), size=(resamples, len(users)))
    for kind in ("genuine", *ATTACKS):
        rows = [o for o in outcomes if o["attack"] == kind]
        flagged = np.array([sum(o["flagged"] for o in rows if o["uid"] == u) for u in users], dtype=np.float64)
        total = np.array([sum(1 for o in rows if o["uid"] == u) for u in users], dtype=np.float64)
        boot = flagged[picks].sum(1) / np.maximum(total[picks].sum(1), 1)      # users resampled with replacement
        ttd = [o["ttd_s"] for o in rows if o["ttd_s"] is not None]
        out[kind] = {"sessions": len(rows), "flagged_rate": round(float(flagged.sum() / max(total.sum(), 1)), 3),
                     "ci95": [round(float(np.quantile(boot, 0.025)), 3), round(float(np.quantile(boot, 0.975)), 3)],
                     "median_ttd_s": round(float(np.median(ttd)), 1) if ttd and kind != "genuine" else None}
    return out


def calibration(p: NDArray[np.float64], y: NDArray[np.float64], bins: int = 10) -> dict[str, Any]:
    """Tick-level reliability (10 bins), ECE and Brier score (SPEC 8.5)."""
    edges = np.linspace(0, 1, bins + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        sel = which == b
        if sel.any():
            gap = abs(float(p[sel].mean()) - float(y[sel].mean()))
            ece += sel.mean() * gap
            table.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(sel.sum()),
                          "mean_score": round(float(p[sel].mean()), 3), "genuine_share": round(float(y[sel].mean()), 3)})
    return {"ece": round(float(ece), 4), "brier": round(float(np.mean((p - y) ** 2)), 4), "reliability": table}


def render(r: Mapping[str, Any], manifest_md: str) -> str:
    lines = [f"# Fusion pipeline dry run — SYNTHETIC", "", f"> **{r['banner']}**", "", manifest_md, "",
             f"Users: {r['users']} (SYNTHETIC, `{r['dataset_id']}`). Keystroke embedding: {r['embedder']}.",
             f"Ticks: {r['coverage']['ticks']}; keystroke input available on {r['coverage']['ks_available']:.0%}, "
             f"AST on {r['coverage']['ast_available']:.0%}.", "",
             "## Sessions (pooled test folds; 95% CI: user-cluster bootstrap)", "",
             "| Session | n | Flagged | 95% CI | Median time to detection |", "|---|---|---|---|---|"]
    for kind, v in r["sessions"].items():
        lines.append(f"| {kind} | {v['sessions']} | {v['flagged_rate']:.1%} | {v['ci95'][0]:.1%}–{v['ci95'][1]:.1%} | "
                     + (f"{v['median_ttd_s']} s" if v["median_ttd_s"] is not None else "–") + " |")
    lines += ["", "\"genuine\" is the false-flag rate (target 5%, tau set on out-of-fold genuine training sessions).", "",
              "## Folds", "", "| Fold | C | tau | Distance weights pinned at 0 |", "|---|---|---|---|"]
    lines += [f"| {f['fold']} | {f['c']} | {f['tau']} | {', '.join(f['pinned_at_zero']) or '–'} |" for f in r["folds"]]
    lines += ["", "Weights (last fold): " + ", ".join(f"{k} {v}" for k, v in r["folds"][-1]["weights"].items()), "",
              f"## Calibration (ticks)", "", f"ECE {r['calibration']['ece']}, Brier {r['calibration']['brier']}.", "",
              "| Score bin | n | Mean score | Genuine share |", "|---|---|---|---|"]
    lines += [f"| {b['bin']} | {b['n']} | {b['mean_score']} | {b['genuine_share']} |" for b in r["calibration"]["reliability"]]
    lines += ["", "## What this does and does not show", "",
              "- It shows the pipeline runs end to end with the real feature code and the SPEC 12.3 protocol, and that "
              "no distance weight is positive.",
              "- It says nothing about real accuracy. The generator does not model coding style (every user types the same "
              "text, so the AST inputs carry no signal), real keyboards, or real cheating; its attacks are easy by construction.",
              "", f"> **{r['banner']}**"]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fusion pipeline dry run on SYNTHETIC sessions.")
    parser.add_argument("--out", type=Path, required=True, help="report path; the file name must contain 'synthetic'")
    parser.add_argument("--encoder", type=Path, help="the P2 encoder file (default: a stand-in embedding)")
    parser.add_argument("--users", type=int)
    args = parser.parse_args(argv)
    if "synthetic" not in args.out.name.lower():
        parser.error("the output file name must contain 'synthetic' (SPEC 10.11)")
    seed = int(_cfg("global")["seed"])
    embedder = load_encoder(args.encoder) if args.encoder else StandInEmbedder()
    result = run(_cfg("eval")["fusion_dryrun"], seed, embedder, users=args.users)
    manifest = run_manifest(seed, (result["dataset_id"],), synthetic=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(result, manifest.as_markdown()), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps({"manifest": manifest.__dict__, **result}, indent=2, default=str),
                                             encoding="utf-8")
    print(f"wrote {args.out} and {args.out.with_suffix('.json').name} (SYNTHETIC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
