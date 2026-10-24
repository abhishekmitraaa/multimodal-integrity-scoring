"""P2 TypeNet reproduction on D1 (Aalto 136M Keystrokes), following docs/p2_protocol.md.

Stages (each resumable; results and models go to <work>, outside the repository):
  baselines  non-deep baselines on the first k test subjects (CPU)
  lr         train M=70 for each learning-rate candidate on the training subjects minus a
             validation block; choose the rate by per-subject EER (Eq. 5, G=5) on that block
             (deviation 6, amended; no test access)
  train50    train M=50 with the chosen rate
  test       TypeNet Table 2 cells for M in {50, 70}: Eq. 5 (primary) and prototype (ablation),
             first k test subjects plus random draws; every test computation is ledgered first
  report     markdown report with the acceptance bands

Usage: python -m integrity_eval.p2_d1 <prepared dir> <work dir> --stage all [--epochs N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from integrity_ml.baselines import pooled_within_subject_mad, sequence_stats
from integrity_ml.keystroke import Keystroke

from .authentication import AuthResult, DigraphScorer, EmbeddingScorer, SeqStatScorer, run_authentication
from .ledger import record_test_access
from .manifest import REPO_ROOT, run_manifest

DATASET = "d1_aalto_136m_keystrokes"
# TypeNet Table 2, desktop, triplet loss (p2_protocol.md §8)
PUBLISHED = {50: {1: 5.4, 2: 3.6, 5: 2.2, 7: 1.8, 10: 1.6}, 70: {1: 4.5, 2: 2.8, 5: 1.7, 7: 1.4, 10: 1.2}}


def band(published: float) -> tuple[float, float]:
    tol = max(1.0, 0.5 * published)
    return published - tol, published + tol


def keystrokes_from_matrix(mat: np.ndarray, n: int) -> list[Keystroke]:
    """Rebuild a sentence's keystrokes from its TypeNet rows: code from keycode, press times from PL,
    releases from HL. Times start at 0 and are exact up to float16 storage rounding."""
    mat = np.asarray(mat, dtype=np.float64)
    out, down = [], 0.0
    for r in range(n):
        out.append(Keystroke(str(int(round(mat[r, 0] * 255))), round(down * 1e6), round((down + mat[r, 1]) * 1e6)))
        down += mat[r, 3]
    return out


def _cfg(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((REPO_ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8")))


class D1:
    def __init__(self, prepared: Path) -> None:
        self.x = np.load(prepared / "x.npy", mmap_mode="r")
        self.lengths = np.load(prepared / "lengths.npy")
        self.pids = np.load(prepared / "pids.npy")
        rep = _cfg("models")["reproduction"]
        n_train, n_val = int(rep["train_subjects"]), int(rep["validation_subjects"])
        if len(self.pids) < n_train + int(rep["test_subjects_k"]):
            raise ValueError("not enough participants for the TypeNet split")
        self.fit = np.arange(0, n_train - n_val)
        self.val = np.arange(n_train - n_val, n_train)
        self.test_pool = np.arange(n_train, min(len(self.pids), n_train + 100_000))
        self.k = int(rep["test_subjects_k"])

    def bank(self, idx: np.ndarray, m: int) -> Any:
        from integrity_ml.encoder import SequenceBank

        x = np.asarray(self.x[idx[0]:idx[-1] + 1])[:, :, :m]          # contiguous block
        lengths = np.minimum(self.lengths[idx[0]:idx[-1] + 1], m).astype(np.int64)
        return SequenceBank(x.reshape(-1, m, 5), lengths.reshape(-1), np.repeat(np.arange(len(idx)), x.shape[1]))

    def keystrokes(self, i: int, s: int, m: int = 70) -> list[Keystroke]:
        return keystrokes_from_matrix(np.asarray(self.x[i, s]), int(min(self.lengths[i, s], m)))


def _result_row(r: AuthResult, m: int | None) -> dict[str, Any]:
    return {"scorer": r.scorer, "m": m, "g": r.g, "eer_mean": r.per_subject.mean, "eer_sd": r.per_subject.sd,
            "n_subjects": r.per_subject.n_subjects, "global_eer": r.global_eer,
            "genuine_available": r.genuine_available, "impostor_available": r.impostor_available}


def _protocol(subjects: Sequence[Any], scorer: Any, g_values: Sequence[int]) -> list[AuthResult]:
    rep = _cfg("models")["reproduction"]
    return [run_authentication(subjects, scorer, g, rep["genuine_query_indices"], rep["impostor_query_index"],
                               rep["eer_threshold_steps"]) for g in g_values]


def stage_baselines(d: D1, work: Path, seed: int) -> None:
    out = work / "baselines.json"
    if out.exists():
        return
    models, rep = _cfg("models"), _cfg("models")["reproduction"]
    rng = np.random.default_rng(seed)
    scale_idx = rng.choice(d.fit, size=2000, replace=False)
    scale = pooled_within_subject_mad([[sequence_stats(d.keystrokes(i, s)) for s in range(15)] for i in scale_idx])
    test = d.test_pool[:d.k]
    record_test_access("p2 D1 non-deep baselines (TypeNet protocol)", DATASET, len(test), final=True, seed=seed)
    subjects = [[d.keystrokes(i, s) for s in range(15)] for i in test]
    dg = models["digraph_baseline"]
    rows = []
    for scorer in (DigraphScorer(dg["min_occurrences"], dg["min_shared_items"]), SeqStatScorer(scale)):
        t = time.time()
        rows += [_result_row(r, None) for r in _protocol(subjects, scorer, rep["g_values"])]
        print(f"  {scorer.name}: {time.time() - t:.0f}s", flush=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _train(d: D1, m: int, lr: float, epochs: int | None, seed: int, path: Path) -> Any:
    import torch

    from integrity_ml.encoder import EncoderConfig, TypeNetEncoder, train

    cfg = EncoderConfig.from_config(_cfg("models")["keystroke_encoder"], learning_rate=lr)
    if path.exists():
        model = TypeNetEncoder(cfg)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        return model.to("cuda" if torch.cuda.is_available() else "cpu")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    t = time.time()
    model, history = train(d.bank(d.fit, m), cfg, seed=seed, device=device, epochs=epochs,
                           log=lambda e, loss: print(f"    m={m} lr={lr} epoch {e + 1}: loss {loss:.4f}", flush=True) if (e + 1) % 10 == 0 else None)
    torch.save(model.state_dict(), path)
    path.with_suffix(".json").write_text(json.dumps({"m": m, "lr": lr, "epochs": len(history), "loss": history,
                                                      "seconds": time.time() - t, "train_subjects": int(len(d.fit))}), encoding="utf-8")
    return model


def _embed_subjects(d: D1, model: Any, idx: np.ndarray, m: int) -> list[list[np.ndarray]]:
    import torch

    from integrity_ml.encoder import embed

    device = next(model.parameters()).device.type
    x = np.asarray(d.x[idx], dtype=np.float16)[:, :, :m].reshape(-1, m, 5)
    lengths = np.minimum(d.lengths[idx], m).astype(np.int64).reshape(-1)
    with torch.no_grad():
        emb = embed(model, x, lengths, device=device).reshape(len(idx), 15, -1)
    return [list(e) for e in emb]


def stage_lr(d: D1, work: Path, epochs: int | None, seed: int) -> float:
    out = work / "lr_selection.json"
    if out.exists():
        return float(json.loads(out.read_text(encoding="utf-8"))["chosen"])
    results = {}
    for lr in _cfg("models")["reproduction"]["learning_rate_candidates"]:
        model = _train(d, 70, lr, epochs, seed, work / f"encoder_m70_lr{lr}.pt")
        [r] = _protocol(_embed_subjects(d, model, d.val, 70), EmbeddingScorer("eq5"), [5])
        results[str(lr)] = r.per_subject.mean
        print(f"  lr {lr}: validation EER (M=70, G=5) {r.per_subject.mean:.2%}", flush=True)
    chosen = min(results, key=lambda k: (results[k], -float(k)))   # ties keep the larger (paper) rate
    out.write_text(json.dumps({"validation_eer_g5_m70": results, "chosen": float(chosen),
                               "validation_subjects": int(len(d.val))}, indent=2), encoding="utf-8")
    return float(chosen)


def stage_test(d: D1, work: Path, lr: float, epochs: int | None, seed: int) -> None:
    out = work / "test.json"
    if out.exists():
        return
    rep = _cfg("models")["reproduction"]
    rows: list[dict[str, Any]] = []
    draws: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    draw_sets = [np.sort(rng.choice(d.test_pool, size=d.k, replace=False)) for _ in range(int(rep["random_test_draws"]))]
    for m in rep["m_values"]:
        model = _train(d, m, lr, epochs, seed, work / f"encoder_m{m}_lr{lr}.pt")
        record_test_access(f"p2 D1 TypeNet reproduction M={m}", DATASET, d.k, final=True, seed=seed, extra={"lr": lr})
        subjects = _embed_subjects(d, model, d.test_pool[:d.k], m)
        for rule in ("eq5", "prototype"):
            rows += [_result_row(r, m) for r in _protocol(subjects, EmbeddingScorer(rule), rep["g_values"])]  # type: ignore[arg-type]
        record_test_access(f"p2 D1 TypeNet reproduction M={m}: random draws", DATASET, d.k * len(draw_sets),
                           final=True, seed=seed, extra={"lr": lr})
        for j, idx in enumerate(draw_sets):
            for r in _protocol(_embed_subjects(d, model, idx, m), EmbeddingScorer("eq5"), rep["g_values"]):
                draws.append({**_result_row(r, m), "draw": j})
        print(f"  M={m} tested", flush=True)
    out.write_text(json.dumps({"first_k": rows, "random_draws": draws, "lr": lr}, indent=2), encoding="utf-8")


def stage_report(d: D1, work: Path, seed: int) -> str:
    test = json.loads((work / "test.json").read_text(encoding="utf-8"))
    base = json.loads((work / "baselines.json").read_text(encoding="utf-8"))
    lrsel = json.loads((work / "lr_selection.json").read_text(encoding="utf-8"))
    summary = json.loads((work.parent / "d1_typenet_m70" / "summary.json").read_text(encoding="utf-8")) \
        if (work.parent / "d1_typenet_m70" / "summary.json").exists() else {}
    manifest = run_manifest(seed, (DATASET,), synthetic=False)
    lines = ["# P2 results: TypeNet reproduction on D1 (Aalto 136M Keystrokes)", "",
             f"Run manifest: {manifest.as_markdown()}", ""]
    if summary:
        lines += [f"Data: {summary['kept_exactly_15_sentences']} of {summary['participants_in_zip']} participants have "
                  f"exactly 15 sentences. Keyboard types of kept participants: {summary['keyboard_types_of_kept']}.", ""]
    lines += [f"Split: {len(d.fit)} training subjects, {len(d.val)} validation subjects (held out from the 68,000), "
              f"test = first {d.k} of the next {len(d.test_pool)} subjects. Learning rate chosen on validation: "
              f"**{lrsel['chosen']}** (validation EER at M=70, G=5: "
              + ", ".join(f"{k}: {v:.2%}" for k, v in lrsel["validation_eer_g5_m70"].items()) + ").", "",
              "## Encoder, Eq. 5 (primary), against TypeNet Table 2 (triplet)", "",
              "| M | G | Ours: mean per-subject EER ± SD | Global EER | Published | Band | In band | Random draws (mean ± SD of 5) |",
              "|---|---|---|---|---|---|---|---|"]
    for r in test["first_k"]:
        if r["scorer"] != "encoder, Eq. 5":
            continue
        pub = PUBLISHED[r["m"]][r["g"]]
        lo, hi = band(pub)
        ours = 100 * r["eer_mean"]
        ds = [100 * x["eer_mean"] for x in test["random_draws"] if x["m"] == r["m"] and x["g"] == r["g"]]
        lines.append(f"| {r['m']} | {r['g']} | {ours:.2f}% ± {100 * r['eer_sd']:.2f} | {100 * r['global_eer']:.2f}% | {pub}% | "
                     f"[{lo:.2f}, {hi:.2f}] | {'yes' if lo <= ours <= hi else '**no**'} | {np.mean(ds):.2f}% ± {np.std(ds):.2f} |")
    lines += ["", "## Ablation: prototype scoring (SPEC 7.3)", "", "| M | G | Mean per-subject EER | Global EER |", "|---|---|---|---|"]
    lines += [f"| {r['m']} | {r['g']} | {100 * r['eer_mean']:.2f}% | {100 * r['global_eer']:.2f}% |"
              for r in test["first_k"] if r["scorer"] == "encoder, prototype"]
    lines += ["", "## Non-deep baselines (same test subjects, sentences truncated at 70 keystrokes)", "",
              "| Baseline | G | Mean per-subject EER ± SD | Global EER | Comparisons available |", "|---|---|---|---|---|"]
    lines += [f"| {r['scorer']} | {r['g']} | {100 * r['eer_mean']:.2f}% ± {100 * r['eer_sd']:.2f} | {100 * r['global_eer']:.2f}% | "
              f"{100 * min(r['genuine_available'], r['impostor_available']):.0f}% |" for r in base]
    lines.append("")
    report = "\n".join(lines)
    (work / "report.md").write_text(report, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P2 TypeNet reproduction on D1.")
    ap.add_argument("prepared", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--stage", choices=["baselines", "lr", "train50", "test", "report", "all"], default="all")
    ap.add_argument("--epochs", type=int, default=None, help="override max_epochs (smoke runs only)")
    args = ap.parse_args(argv)
    work = args.work.resolve()
    if REPO_ROOT.resolve() in work.parents:
        print("p2_d1: work dir must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    seed = int(_cfg("global")["seed"])
    d = D1(args.prepared)
    if args.stage in ("baselines", "all"):
        stage_baselines(d, work, seed)
    if args.stage in ("lr", "train50", "test", "all"):
        lr = stage_lr(d, work, args.epochs, seed)
        if args.stage in ("train50", "all", "test"):
            _train(d, 50, lr, args.epochs, seed, work / f"encoder_m50_lr{lr}.pt")
        if args.stage in ("test", "all"):
            stage_test(d, work, lr, args.epochs, seed)
    if args.stage in ("report", "all"):
        print(stage_report(d, work, seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
