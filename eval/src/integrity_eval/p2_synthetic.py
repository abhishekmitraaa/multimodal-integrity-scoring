"""P2 pipeline check: both non-deep baselines under the TypeNet protocol on SYNTHETIC data (D3).

This shows that the features, baselines, protocol and EER code run end to end and respond to how
separable the synthetic subjects are. It says nothing about real keystroke identity, and its
numbers are never reported as results (SPEC 10.11).

Usage: python -m integrity_eval.p2_synthetic [--subjects N] [--out report.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

from integrity_ml.baselines import pooled_within_subject_mad, sequence_stats
from integrity_ml.synthetic_keystrokes import SyntheticConfig, generate

from .authentication import AuthResult, DigraphScorer, SeqStatScorer, run_authentication
from .manifest import REPO_ROOT, run_manifest

TRAIN_FRACTION = 0.4   # subjects used only to fit the sequence-statistics scale (open set, like TypeNet)


def _cfg(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((REPO_ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8")))


def run(subjects: int | None = None) -> tuple[list[tuple[float, AuthResult]], dict[str, Any]]:
    models, evalcfg, seed = _cfg("models"), _cfg("eval"), int(_cfg("global")["seed"])
    syn, rep = evalcfg["synthetic_keystrokes"], models["reproduction"]
    digraph = DigraphScorer(models["digraph_baseline"]["min_occurrences"], models["digraph_baseline"]["min_shared_items"])
    results: list[tuple[float, AuthResult]] = []
    for separation in syn["separations"]:
        overrides = {"subjects": subjects} if subjects else {}
        data = generate(SyntheticConfig.from_config(syn, separation=separation, seed=seed, **overrides))
        n_train = max(2, int(len(data.subjects) * TRAIN_FRACTION))
        train, test = data.subjects[:n_train], data.subjects[n_train:]
        scale = pooled_within_subject_mad([[sequence_stats(s) for s in subj] for subj in train])
        for scorer in (digraph, SeqStatScorer(scale)):
            for g in rep["g_values"]:
                results.append((separation, run_authentication(
                    test, scorer, g, rep["genuine_query_indices"], rep["impostor_query_index"], rep["eer_threshold_steps"])))
    return results, {"seed": seed, "dataset_id": syn["dataset_id"], "subjects": subjects or syn["subjects"]}


def render(results: Sequence[tuple[float, AuthResult]], info: dict[str, Any]) -> str:
    manifest = run_manifest(info["seed"], (info["dataset_id"],), synthetic=True)
    lines = [
        "# P2 pipeline check: non-deep baselines on SYNTHETIC data",
        "",
        "**SYNTHETIC — NOT A RESULT.** Generated subjects (D3), used only to test the code path. "
        "Nothing here says anything about real keystroke identity.",
        "",
        f"Protocol: TypeNet (gallery = sequences 0..G−1, genuine = 10–14, impostor = sequence 11 of "
        f"every other subject); {info['subjects']} synthetic subjects per separation, "
        f"{int(TRAIN_FRACTION * 100)}% used only to fit the scale; EER = mean per-subject EER (authors' sweep).",
        "",
        "| Separation | Baseline | G | Per-subject EER (mean ± SD) | Global EER | Genuine available | Impostor available | Subjects without scores |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sep, r in results:
        lines.append(
            f"| {sep:g} | {r.scorer} | {r.g} | {r.per_subject.mean:.1%} ± {r.per_subject.sd:.1%} | {r.global_eer:.1%} | "
            f"{r.genuine_available:.0%} | {r.impostor_available:.0%} | {r.subjects_without_scores} |"
        )
    lines += ["", "Run manifest: " + manifest.as_markdown(), ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2 baselines on synthetic data (pipeline check only).")
    parser.add_argument("--subjects", type=int, default=None, help="override the configured subject count")
    parser.add_argument("--out", type=Path, help="write the report here as UTF-8")
    args = parser.parse_args(argv)
    report = render(*run(args.subjects))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
