"""The evaluation harness (SPEC 7.4, 8, 12.3-12.6), shared by the SYNTHETIC dry run and the D2 study data.

Given labelled sessions (practice + exam, each exam with a condition and an onset), it:
1. computes raw evidence per scoring tick once (SPEC 8.1): latest keystroke window, process
   features over the trailing horizon, the AST of the latest snapshot, clipboard and focus;
2. runs user-disjoint nested CV (SPEC 12.3). Per outer fold the encoder may be fine-tuned on the
   training users' practice windows (step 1); everything fitted from data uses training users only:
   process scales s_k, per-task AST references and style statistics, imputation medians (genuine
   training rows), C (inner folds, log loss) and tau (5% of out-of-fold genuine training sessions);
3. scores test users with sign-constrained fusion, EWMA on the logit and the session minimum (SPEC 8.3);
4. reports (SPEC 12.4, 12.5): detection per attack with the realised false-flag rate, per-user table,
   time to detection in seconds and keystrokes (missed = "not detected", never dropped), modality
   ablations (each alone, leave-one-out), fused vs best single modality as a paired user-cluster
   bootstrap difference, lambda in {1, 0.5, 0.3} each with its own tau, training variance over
   repeat seeds, calibration, and false flags by covariate (descriptive).

Deviation from SPEC 12.3, recorded in D-047: the encoder is fine-tuned once per OUTER fold (on its
training users), not again inside each inner fold, to keep the cost down; inner C/tau selection is
therefore mildly optimistic, and test users are never touched.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from integrity_ml import ast_features as ast
from integrity_ml.fusion import FusionModel, fit_fusion
from integrity_ml.process_features import ProcessConfig, baseline, pooled_within_sd, process_distance, process_features, vector
from integrity_ml.session_features import editor_keystrokes, enrollment_windows, exam_windows, insertions
from integrity_ml.smoothing import ewma_logit

INPUTS = ("d_ks", "d_proc", "d_ast_h", "d_ast_s", "clip_ext_frac", "clip_ext_chars_log", "focus_loss_frac")
AVAILABILITY = ("ks_available", "ast_available")
COLUMNS = INPUTS + AVAILABILITY
MODALITIES: dict[str, tuple[str, ...]] = {
    "keystroke": ("d_ks", "ks_available"),
    "process": ("d_proc",),
    "ast": ("d_ast_h", "d_ast_s", "ast_available"),
    "clipboard": ("clip_ext_frac", "clip_ext_chars_log", "focus_loss_frac"),
}
GENUINE_LABELS = ("genuine", "A7", "A8")              # genuine work; A7 and A8 are false-flag tests (SPEC 9.3)
ATTACK_LABELS = ("A1", "A2", "A3a", "A3b", "A4", "A5", "IMP")


@dataclass
class Session:
    uid: str
    kind: str                 # practice | exam
    label: str                # practice | genuine | A1 ... | IMP
    problem_id: str
    events: list[dict[str, Any]]
    onset_s: float | None = None          # attack onset on the client clock (s); None = genuine work
    covariates: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawTick:
    session: int
    uid: str
    problem_id: str
    t: float
    label: int                # 1 genuine; 0 once an attack has started
    win: int | None           # index of the latest exam window within the age limit
    proc: NDArray[np.float64]
    ast: ast.AstSummary | None
    ext_frac: float
    ext_chars: int
    focus_frac: float


@dataclass
class Prepared:
    exams: list[Session]
    users: list[str]
    ticks: list[RawTick]
    y: NDArray[np.float64]
    practice: dict[str, dict[str, tuple[NDArray[np.float64], ast.AstSummary]]]
    enroll: dict[str, list[NDArray[np.float32]]]
    windows: list[list[NDArray[np.float32]]]            # per exam session
    keydowns: list[NDArray[np.float64]]                 # per exam session, editor keydown times (s)
    finals: dict[tuple[str, str], ast.AstSummary]       # (uid, problem) -> final code of a genuine exam
    authors: dict[str, ast.AstSummary]                  # practice author solutions
    alpha: float
    min_nodes: int


def tick_times(events: Sequence[Mapping[str, Any]], every: int, first_after: int, max_interval_s: float) -> list[float]:
    """SPEC 8.1: every `every` keydowns once a window exists, every paste, at least every max_interval_s, and the end."""
    ev = [e for e in events if e.get("t_client_us") is not None]
    downs = [e["t_client_us"] / 1e6 for e in ev if e["type"] == "keydown" and e["data"].get("target", "editor") == "editor"
             and not e["data"].get("rep")]
    t0, end = ev[0]["t_client_us"] / 1e6, ev[-1]["t_client_us"] / 1e6
    ticks = set(downs[first_after - 1::every]) | {e["t_client_us"] / 1e6 for e in ev if e["type"] == "paste"} | {end}
    out: list[float] = []
    last = t0
    for t in sorted(ticks):
        while t - last > max_interval_s:
            last += max_interval_s
            out.append(last)
        out.append(t)
        last = t
    return out


def _last_snapshot_text(events: Sequence[Mapping[str, Any]]) -> str:
    return next((str(e["data"]["text"]) for e in reversed(events) if e["type"] == "snapshot"), "")


def prepare(sessions: Sequence[Session], practice_authors: Mapping[str, str], cfg: Mapping[str, Mapping[str, Any]]) -> Prepared:
    """Raw evidence per tick, computed once. cfg: {"features", "scoring", "models"} config dicts."""
    feat, scoring, models = cfg["features"], cfg["scoring"], cfg["models"]
    m, stride = int(feat["keystroke"]["window_keystrokes"]), int(feat["keystroke"]["exam_stride"])
    clip_s, max_age = feat["keystroke"]["latency_clip_ms"] / 1000, float(feat["keystroke"]["window_max_age_s"])
    horizon = float(feat["process"]["horizon_s"])
    pcfg = ProcessConfig.from_config(feat["process"])
    alpha, min_nodes = float(feat["ast"]["laplace_alpha"]), int(feat["ast"]["min_named_nodes"])
    users = sorted({s.uid for s in sessions})
    practice: dict[str, dict[str, tuple[NDArray[np.float64], ast.AstSummary]]] = {u: {} for u in users}
    enroll: dict[str, list[NDArray[np.float32]]] = {u: [] for u in users}
    finals: dict[tuple[str, str], ast.AstSummary] = {}
    exams = [s for s in sessions if s.kind == "exam"]
    lengths = [(s.events[-1]["t_client_us"] - s.events[0]["t_client_us"]) / 1e6 for s in exams]
    cuts = np.quantile(lengths, [1 / 3, 2 / 3]) if lengths else [0.0, 0.0]
    for s, length in zip(exams, lengths):           # session length is a covariate for false flags (SPEC 12.4)
        s.covariates.setdefault("session_length", "short" if length <= cuts[0] else "medium" if length <= cuts[1] else "long")
    for s in sessions:
        if s.kind == "practice":
            practice[s.uid][s.problem_id] = (vector(process_features(s.events, pcfg)), ast.summarize(_last_snapshot_text(s.events)))
            enroll[s.uid] += enrollment_windows(editor_keystrokes(s.events), m, clip_s)
        elif s.label == "genuine":
            finals[(s.uid, s.problem_id)] = ast.summarize(_last_snapshot_text(s.events))
    ticks: list[RawTick] = []
    windows, keydowns = [], []
    for i, s in enumerate(exams):
        ev = s.events
        t0 = ev[0]["t_client_us"] / 1e6
        wins = exam_windows(editor_keystrokes(ev), m, stride, clip_s)
        windows.append([w for w, _ in wins])
        win_t = np.array([t for _, t in wins])
        keydowns.append(np.array([e["t_client_us"] / 1e6 for e in ev if e["type"] == "keydown"
                                  and e["data"].get("target", "editor") == "editor" and not e["data"].get("rep")]))
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
        for t in tick_times(ev, int(scoring["tick"]["every_keydowns"]), m, float(scoring["tick"]["max_interval_s"])):
            lo = t - horizon
            j = int(np.searchsorted(win_t, t, side="right")) - 1
            text = next((x for tt, x in reversed(snaps) if tt <= t), None)
            if text is not None and text not in parsed:
                parsed[text] = ast.summarize(text)
            ext = sum(p.chars for p in pastes if p.provenance == "external" and lo < p.t <= t)
            ins = sum(n for tt, n in inserted if lo < tt <= t)
            span = min(horizon, t - t0) or 1.0
            gone = sum(max(0.0, min(b, t) - max(a, lo)) for a, b in away)
            ticks.append(RawTick(i, s.uid, s.problem_id, t, 0 if s.onset_s is not None and t >= s.onset_s else 1,
                                 j if j >= 0 and t - win_t[j] <= max_age else None,
                                 vector(process_features(ev, pcfg, window=(lo, t))), parsed.get(text) if text is not None else None,
                                 ext / ins if ins else 0.0, ext, gone / span))
    authors = {pid: ast.summarize(code) for pid, code in practice_authors.items()}
    return Prepared(exams, users, ticks, np.array([k.label for k in ticks], dtype=np.float64), practice, enroll,
                    windows, keydowns, finals, authors, alpha, min_nodes)


# ---------------------------------------------------------------- keystroke distances with a given encoder

def ks_distances(prep: Prepared, embedder: Any, g_min: int) -> list[NDArray[np.float64] | None]:
    """Per exam session, the distance of each window to its user's practice prototype (None: no baseline)."""
    protos = {u: (embedder.embed(w).mean(axis=0) if len(w) >= g_min else None) for u, w in prep.enroll.items()}
    out: list[NDArray[np.float64] | None] = []
    for s, wins in zip(prep.exams, prep.windows):
        p = protos[s.uid]
        out.append(np.linalg.norm(embedder.embed(wins) - p, axis=1).astype(np.float64) if p is not None and wins else None)
    return out


# ---------------------------------------------------------------- fold statistics and the design matrix

def _style_stats(summaries: Sequence[ast.AstSummary]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x = np.stack([s.style() for s in summaries])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(x, axis=0), np.nanstd(x, axis=0)


def design(prep: Prepared, train: frozenset[str], ks: Sequence[NDArray[np.float64] | None]) -> NDArray[np.float64]:
    """All ticks x COLUMNS, with every fitted statistic from `train` users only; NaN = unavailable."""
    a = prep.alpha
    s_k = pooled_within_sd({u: [v for v, _ in prep.practice[u].values()] for u in train if prep.practice[u]})
    b_u = {u: baseline([v for v, _ in mods.values()]) for u, mods in prep.practice.items() if mods}
    r_p, style_p = {}, {}
    for pid, author in prep.authors.items():
        fin = [author] + [prep.practice[u][pid][1] for u in train if pid in prep.practice[u]]
        r_p[pid] = ast.reference([ast.smoothed(f.counts, a) for f in fin])
        style_p[pid] = _style_stats(fin)
    b_ast = {u: ast.student_baseline([ast.tilt(ast.smoothed(prep.practice[u][pid][1].counts, a), r_p[pid])
                                      for pid in prep.authors if pid in prep.practice[u]])
             for u in prep.users if any(pid in prep.practice[u] for pid in prep.authors)}
    z_p = {u: [ast.style_z(prep.practice[u][pid][1].style(), *style_p[pid]) for pid in prep.authors if pid in prep.practice[u]]
           for u in prep.users}
    r_exam, style_exam = {}, {}
    for pid in {k.problem_id for k in prep.ticks}:
        fin = [f for (u, p), f in prep.finals.items() if p == pid and u in train]
        if fin:                                       # per task: training users' genuine final code (SPEC 6.3)
            r_exam[pid] = ast.reference([ast.smoothed(f.counts, a) for f in fin])
            style_exam[pid] = _style_stats(fin)
    rows = []
    for k in prep.ticks:
        d_ks = None if ks[k.session] is None or k.win is None else float(ks[k.session][k.win])
        d_proc = process_distance(k.proc, b_u[k.uid], s_k) if k.uid in b_u else None
        d_h = d_s = None
        if k.ast is not None and ast.available(k.ast, prep.min_nodes) and k.problem_id in r_exam and k.uid in b_ast:
            d_h = ast.jsd(ast.tilt(ast.smoothed(k.ast.counts, a), r_exam[k.problem_id]), b_ast[k.uid])
            d_s = ast.style_distance(ast.style_z(k.ast.style(), *style_exam[k.problem_id]), z_p[k.uid])
        vals = [d_ks, d_proc, d_h, d_s, k.ext_frac, math.log1p(k.ext_chars), k.focus_frac]
        rows.append([np.nan if v is None else float(v) for v in vals] + [float(d_ks is not None), float(d_h is not None)])
    return np.array(rows, dtype=np.float64)


def _genuine_medians(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
    with warnings.catch_warnings():                   # an input never available in a fold is imputed as 0 (coverage says so)
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(np.where(y[:, None] == 1, x, np.nan), axis=0)
    return np.where(np.isnan(med), 0.0, med)


def _logloss(p: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _folds(users: Sequence[str], k: int, rng: np.random.Generator) -> list[frozenset[str]]:
    order = list(rng.permutation(list(users)))
    return [frozenset(order[i::k]) for i in range(k)]


# ---------------------------------------------------------------- nested CV

@dataclass(frozen=True)
class CVSettings:
    outer_folds: int
    inner_folds: int
    c_grid: tuple[float, ...]
    lam: float
    false_flag_rate: float
    g_min: int
    seed: int


class Harness:
    """Caches design matrices per (training users, encoder), so C, inner folds and ablations reuse them."""

    def __init__(self, prep: Prepared, base_embedder: Any, finetune: Callable[[Any, Prepared, frozenset[str], int], Any] | None = None) -> None:
        self.prep = prep
        self.base = base_embedder
        self.finetune = finetune
        self._ks: dict[Any, list[NDArray[np.float64] | None]] = {}
        self._design: dict[tuple[Any, frozenset[str]], NDArray[np.float64]] = {}
        self._encoders: dict[tuple[frozenset[str], int], Any] = {}

    def encoder_for(self, outer_train: frozenset[str], seed: int) -> Any:
        if self.finetune is None:
            return self.base
        key = (outer_train, seed)
        if key not in self._encoders:
            self._encoders[key] = self.finetune(self.base, self.prep, outer_train, seed)
        return self._encoders[key]

    def matrix(self, encoder: Any, train: frozenset[str], g_min: int) -> NDArray[np.float64]:
        if id(encoder) not in self._ks:
            self._ks[id(encoder)] = ks_distances(self.prep, encoder, g_min)
        key = (id(encoder), train)
        if key not in self._design:
            self._design[key] = design(self.prep, train, self._ks[id(encoder)])
        return self._design[key]

    def _fit(self, x_all: NDArray[np.float64], train: frozenset[str], cols: Sequence[int], c: float) -> tuple[FusionModel, NDArray[np.float64]]:
        idx = np.array([k.uid in train for k in self.prep.ticks])
        x = x_all[idx][:, cols]
        med = _genuine_medians(x, self.prep.y[idx])
        names = [COLUMNS[i] for i in cols]
        model = fit_fusion(np.where(np.isnan(x), med, x), self.prep.y[idx], names, [n in INPUTS for n in names], c=c)
        return model, med

    def _scores(self, model: FusionModel, med: NDArray[np.float64], x_all: NDArray[np.float64], on: frozenset[str],
                cols: Sequence[int], lam: float) -> dict[int, tuple[NDArray[np.float64], NDArray[np.float64]]]:
        idx = [i for i, k in enumerate(self.prep.ticks) if k.uid in on]
        x = x_all[idx][:, cols]
        s = model.score(np.where(np.isnan(x), med, x))
        by: dict[int, tuple[list[float], list[float]]] = {}
        for i, v in zip(idx, s):
            k = self.prep.ticks[i]
            by.setdefault(k.session, ([], []))
            by[k.session][0].append(k.t)
            by[k.session][1].append(float(v))
        return {sid: (np.array(t), ewma_logit(np.array(v), lam)) for sid, (t, v) in by.items()}

    def cross_validate(self, st: CVSettings, columns: Sequence[str] = COLUMNS) -> dict[str, Any]:
        cols = [COLUMNS.index(c) for c in columns]
        rng = np.random.default_rng(st.seed)
        users = self.prep.users
        outcomes, folds, tick_p, tick_y = [], [], [], []
        for fold, test in enumerate(_folds(users, st.outer_folds, rng)):
            train = frozenset(users) - test
            enc = self.encoder_for(train, st.seed)
            inner = _folds(sorted(train), st.inner_folds, rng)
            loss = {}
            for c in st.c_grid:                       # C by inner-fold log loss over ticks
                p_all, y_all = [], []
                for val in inner:
                    x_all = self.matrix(enc, train - val, st.g_min)
                    model, med = self._fit(x_all, train - val, cols, c)
                    idx = np.array([k.uid in val for k in self.prep.ticks])
                    x = x_all[idx][:, cols]
                    p_all.append(model.score(np.where(np.isnan(x), med, x)))
                    y_all.append(self.prep.y[idx])
                loss[c] = _logloss(np.concatenate(p_all), np.concatenate(y_all))
            best = min(st.c_grid, key=lambda c: (loss[c], c))
            oof = []                                  # tau: out-of-fold plain-genuine training sessions
            for val in inner:
                x_all = self.matrix(enc, train - val, st.g_min)
                model, med = self._fit(x_all, train - val, cols, best)
                for sid, (_, sm) in self._scores(model, med, x_all, val, cols, st.lam).items():
                    if self.prep.exams[sid].label == "genuine":
                        oof.append(float(sm.min()))
            tau = float(np.quantile(oof, st.false_flag_rate)) if oof else 0.5
            x_all = self.matrix(enc, train, st.g_min)
            model, med = self._fit(x_all, train, cols, best)
            idx = np.array([k.uid in test for k in self.prep.ticks])
            x = x_all[idx][:, cols]
            tick_p.append(model.score(np.where(np.isnan(x), med, x)))
            tick_y.append(self.prep.y[idx])
            for sid, (tt, sm) in self._scores(model, med, x_all, test, cols, st.lam).items():
                s = self.prep.exams[sid]
                crossed = tt[sm < tau]
                onset = s.onset_s if s.onset_s is not None else float(tt[0])
                hit = float(crossed[crossed >= onset][0]) if (crossed >= onset).any() else None
                downs = self.prep.keydowns[sid]
                outcomes.append({
                    "uid": s.uid, "condition": s.label, "problem_id": s.problem_id, "flagged": bool(crossed.size),
                    "session_score": round(float(sm.min()), 4),
                    "ttd_s": round(hit - onset, 1) if hit is not None and s.label in ATTACK_LABELS else None,
                    "ttd_keys": int(((downs >= onset) & (downs <= hit)).sum()) if hit is not None and s.label in ATTACK_LABELS else None,
                    "covariates": s.covariates,
                })
            folds.append({"fold": fold, "test_users": len(test), "c": best, "tau": round(tau, 4),
                          "weights": {COLUMNS[i]: round(float(w), 4) for i, w in zip(cols, model.coef)},
                          "pinned_at_zero": [COLUMNS[i] for i, w in zip(cols, model.coef) if COLUMNS[i] in INPUTS and w == 0.0]})
        return {"outcomes": outcomes, "folds": folds, "tick_p": np.concatenate(tick_p), "tick_y": np.concatenate(tick_y)}


# ---------------------------------------------------------------- analyses

def _conditions(outcomes: Sequence[Mapping[str, Any]]) -> list[str]:
    present = {o["condition"] for o in outcomes}
    return [c for c in (*GENUINE_LABELS, *ATTACK_LABELS) if c in present]


def _user_picks(users: Sequence[str], resamples: int, seed: int) -> NDArray[np.int64]:
    return np.random.default_rng(seed).integers(0, len(users), size=(resamples, len(users)))


def _rate_by_user(outcomes: Sequence[Mapping[str, Any]], users: Sequence[str], keep: Callable[[Mapping[str, Any]], bool]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    flagged = np.array([sum(o["flagged"] for o in outcomes if o["uid"] == u and keep(o)) for u in users], dtype=np.float64)
    total = np.array([sum(1 for o in outcomes if o["uid"] == u and keep(o)) for u in users], dtype=np.float64)
    return flagged, total


def summary(outcomes: Sequence[Mapping[str, Any]], resamples: int, seed: int) -> dict[str, Any]:
    """Per condition: flagged rate with a user-cluster bootstrap CI (SPEC 12.5), median time to detection."""
    users = sorted({o["uid"] for o in outcomes})
    picks = _user_picks(users, resamples, seed)
    out = {}
    for cond in _conditions(outcomes):
        f, n = _rate_by_user(outcomes, users, lambda o, c=cond: o["condition"] == c)
        boot = f[picks].sum(1) / np.maximum(n[picks].sum(1), 1)
        hits = [o for o in outcomes if o["condition"] == cond and o["ttd_s"] is not None]
        out[cond] = {"sessions": int(n.sum()), "flagged_rate": round(float(f.sum() / max(n.sum(), 1)), 3),
                     "ci95": [round(float(np.quantile(boot, 0.025)), 3), round(float(np.quantile(boot, 0.975)), 3)],
                     "median_ttd_s": round(float(np.median([o["ttd_s"] for o in hits])), 1) if hits else None,
                     "median_ttd_keys": int(np.median([o["ttd_keys"] for o in hits])) if hits else None,
                     "not_detected": sum(1 for o in outcomes if o["condition"] == cond and o["ttd_s"] is None) if cond in ATTACK_LABELS else None}
    return out


def paired_difference(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], resamples: int, seed: int) -> dict[str, Any]:
    """Detection over all attack sessions, a minus b, paired by user (same resamples), with a 95% CI."""
    users = sorted({o["uid"] for o in a})
    picks = _user_picks(users, resamples, seed)
    is_attack = lambda o: o["condition"] in ATTACK_LABELS  # noqa: E731
    fa, na = _rate_by_user(a, users, is_attack)
    fb, nb = _rate_by_user(b, users, is_attack)
    diff = fa[picks].sum(1) / np.maximum(na[picks].sum(1), 1) - fb[picks].sum(1) / np.maximum(nb[picks].sum(1), 1)
    point = fa.sum() / max(na.sum(), 1) - fb.sum() / max(nb.sum(), 1)
    return {"difference": round(float(point), 3), "ci95": [round(float(np.quantile(diff, 0.025)), 3), round(float(np.quantile(diff, 0.975)), 3)]}


def per_user(outcomes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """SPEC 12.4: participant x condition, detected, S_session, time to detection."""
    return sorted(({"uid": o["uid"], "condition": o["condition"], "problem_id": o["problem_id"], "flagged": o["flagged"],
                    "session_score": o["session_score"], "ttd_s": o["ttd_s"], "ttd_keys": o["ttd_keys"]} for o in outcomes),
                  key=lambda r: (r["uid"], r["condition"], r["problem_id"]))


def calibration(p: NDArray[np.float64], y: NDArray[np.float64], bins: int = 10) -> dict[str, Any]:
    """Tick-level reliability (10 bins), ECE and Brier score (SPEC 8.5)."""
    edges = np.linspace(0, 1, bins + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        sel = which == b
        if sel.any():
            ece += sel.mean() * abs(float(p[sel].mean()) - float(y[sel].mean()))
            table.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(sel.sum()),
                          "mean_score": round(float(p[sel].mean()), 3), "genuine_share": round(float(y[sel].mean()), 3)})
    return {"ece": round(float(ece), 4), "brier": round(float(np.mean((p - y) ** 2)), 4), "reliability": table}


def false_flags_by_covariate(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Descriptive only (SPEC 12.4): flagged share of genuine-work sessions by each covariate value."""
    genuine = [o for o in outcomes if o["condition"] in GENUINE_LABELS]
    out: dict[str, list[dict[str, Any]]] = {}
    for key in sorted({k for o in genuine for k in o["covariates"]}):
        groups: dict[str, list[bool]] = {}
        for o in genuine:
            groups.setdefault(str(o["covariates"].get(key, "unknown")), []).append(o["flagged"])
        out[key] = [{"value": v, "sessions": len(f), "flagged": sum(f)} for v, f in sorted(groups.items())]
    return out


def evaluate(harness: Harness, st: CVSettings, resamples: int, lambdas: Sequence[float] = (1.0, 0.5, 0.3),
             repeat_seeds: Sequence[int] = (1, 2, 3)) -> dict[str, Any]:
    """Everything SPEC 12.4/12.5 asks for, from one prepared data set."""
    main = harness.cross_validate(st)
    runs = {"fused": main["outcomes"]}
    ablations: dict[str, Any] = {}
    for name, cols in MODALITIES.items():
        alone = harness.cross_validate(st, cols)
        without = harness.cross_validate(st, [c for c in COLUMNS if c not in cols])
        runs[name] = alone["outcomes"]
        ablations[name] = {"alone": summary(alone["outcomes"], resamples, st.seed),
                           "without": summary(without["outcomes"], resamples, st.seed)}
    attack_rate = {k: (lambda o: sum(x["flagged"] for x in o if x["condition"] in ATTACK_LABELS)
                       / max(1, sum(1 for x in o if x["condition"] in ATTACK_LABELS)))(v) for k, v in runs.items()}
    best_single = max(MODALITIES, key=lambda m: (attack_rate[m], m))
    lam_runs = {}
    for lam in lambdas:
        r = main if lam == st.lam else harness.cross_validate(CVSettings(**{**st.__dict__, "lam": lam}))
        lam_runs[str(lam)] = summary(r["outcomes"], resamples, st.seed)
    seeds = {}
    for seed in repeat_seeds:
        r = main if seed == st.seed else harness.cross_validate(CVSettings(**{**st.__dict__, "seed": seed}))
        s = summary(r["outcomes"], resamples, seed)
        seeds[str(seed)] = {c: v["flagged_rate"] for c, v in s.items()}
    return {
        "summary": summary(main["outcomes"], resamples, st.seed),
        "per_user": per_user(main["outcomes"]),
        "folds": main["folds"],
        "calibration": calibration(main["tick_p"], main["tick_y"]),
        "ablations": ablations,
        "attack_detection": {k: round(v, 3) for k, v in attack_rate.items()},
        "best_single_modality": best_single,
        "fused_vs_best_single": paired_difference(runs["fused"], runs[best_single], resamples, st.seed),
        "lambda": lam_runs,
        "repeat_seeds": seeds,
        "false_flags_by_covariate": false_flags_by_covariate(main["outcomes"]),
        "coverage": {"ticks": len(harness.prep.ticks), "users": len(harness.prep.users), "exam_sessions": len(harness.prep.exams),
                     "ks_window": float(np.mean([k.win is not None for k in harness.prep.ticks])),
                     "ast_available": float(np.mean([k.ast is not None and ast.available(k.ast, harness.prep.min_nodes)
                                                     for k in harness.prep.ticks]))},
    }


def render(r: Mapping[str, Any], title: str, banner: str | None, manifest_md: str, dataset_md: str) -> str:
    """The evaluation report (markdown). Every table names the data set, fold scheme, commit and config (SPEC 12.6)."""
    lines = [f"# {title}", ""]
    if banner:
        lines += [f"> **{banner}**", ""]
    lines += [manifest_md, "", dataset_md, "",
              f"Coverage: {r['coverage']['users']} users, {r['coverage']['exam_sessions']} exam sessions, {r['coverage']['ticks']} ticks; "
              f"keystroke window on {r['coverage']['ks_window']:.0%} of ticks, AST on {r['coverage']['ast_available']:.0%}.", "",
              "## Detection and false flags (pooled outer-test folds; 95% CI: user-cluster bootstrap)", "",
              "| Condition | Sessions | Flagged | 95% CI | Median time to detection | Not detected |", "|---|---|---|---|---|---|"]
    for c, v in r["summary"].items():
        ttd = f"{v['median_ttd_s']} s / {v['median_ttd_keys']} keys" if v["median_ttd_s"] is not None else "–"
        lines.append(f"| {c} | {v['sessions']} | {v['flagged_rate']:.1%} | {v['ci95'][0]:.1%}–{v['ci95'][1]:.1%} | {ttd} | "
                     f"{v['not_detected'] if v['not_detected'] is not None else '–'} |")
    lines += ["", "genuine, A7 and A8 are genuine work: their \"flagged\" is the false-flag rate (target 5% on plain genuine, "
              "tau from out-of-fold genuine training sessions). The rest are detection rates (SPEC 9.3).", "",
              "## Primary endpoint 2: fused vs best single modality", "",
              f"Best single modality: **{r['best_single_modality']}**. Detection over all attack sessions, fused minus best single: "
              f"{r['fused_vs_best_single']['difference']:+.3f} (95% CI {r['fused_vs_best_single']['ci95'][0]:+.3f} to "
              f"{r['fused_vs_best_single']['ci95'][1]:+.3f}, paired user-cluster bootstrap).", "",
              "## Ablations: detection over all attacks / plain-genuine false flags", "",
              "| Modality | Alone | Without it |", "|---|---|---|"]
    for name, v in r["ablations"].items():
        def cell(s: Mapping[str, Any]) -> str:
            att = [x for c, x in s.items() if c in ATTACK_LABELS]
            det = sum(x["flagged_rate"] * x["sessions"] for x in att) / max(1, sum(x["sessions"] for x in att))
            ffr = s.get("genuine", {}).get("flagged_rate")
            return f"{det:.1%} / {ffr:.1%}" if ffr is not None else f"{det:.1%} / –"
        lines.append(f"| {name} | {cell(v['alone'])} | {cell(v['without'])} |")
    lines += ["", "## Smoothing (lambda), each with its own tau", "", "| lambda | " + " | ".join(next(iter(r["lambda"].values())).keys()) + " |",
              "|---|" + "---|" * len(next(iter(r["lambda"].values())))]
    for lam, s in r["lambda"].items():
        lines.append(f"| {lam} | " + " | ".join(f"{v['flagged_rate']:.1%}" for v in s.values()) + " |")
    lines += ["", "## Training variance: repeat seeds (fold assignment)", "", "| Seed | " + " | ".join(next(iter(r["repeat_seeds"].values())).keys()) + " |",
              "|---|" + "---|" * len(next(iter(r["repeat_seeds"].values())))]
    for seed, s in r["repeat_seeds"].items():
        lines.append(f"| {seed} | " + " | ".join(f"{v:.1%}" for v in s.values()) + " |")
    lines += ["", "## Folds", "", "| Fold | C | tau | Distance weights pinned at 0 |", "|---|---|---|---|"]
    lines += [f"| {f['fold']} | {f['c']} | {f['tau']} | {', '.join(f['pinned_at_zero']) or '–'} |" for f in r["folds"]]
    lines += ["", "## Calibration (ticks)", "", f"ECE {r['calibration']['ece']}, Brier {r['calibration']['brier']}.", "",
              "| Score bin | n | Mean score | Genuine share |", "|---|---|---|---|"]
    lines += [f"| {b['bin']} | {b['n']} | {b['mean_score']} | {b['genuine_share']} |" for b in r["calibration"]["reliability"]]
    lines += ["", "## False flags by covariate (descriptive only; N is small)", ""]
    for key, rows in r["false_flags_by_covariate"].items():
        lines.append(f"- **{key}**: " + "; ".join(f"{x['value']} {x['flagged']}/{x['sessions']}" for x in rows))
    lines += ["", f"Per-user table (participant x condition): {len(r['per_user'])} rows, in the JSON report."]
    if banner:
        lines += ["", f"> **{banner}**"]
    return "\n".join(lines) + "\n"
