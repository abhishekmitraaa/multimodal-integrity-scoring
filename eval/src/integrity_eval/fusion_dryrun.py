"""Fusion pipeline dry run on SYNTHETIC sessions (D-045, D-047). A test of the code, never a result.

The generator (integrity_eval.synthetic_sessions) stands in for the study data; everything else is
the evaluation harness the study will use (integrity_eval.fusion_eval): ticks, features, nested
CV with per-fold statistics, sign-constrained fusion, smoothing, tau, ablations, lambda grid,
repeat seeds, calibration and covariates. Every output says SYNTHETIC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import fusion_eval as fe
from .manifest import REPO_ROOT, run_manifest
from .synthetic_sessions import generate

BANNER = "SYNTHETIC: a test of the fusion pipeline on generated sessions. Not a result; never report these numbers."

# The SYNTHETIC exam solution every synthetic user types (the run-length task).
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


class StandInEmbedder:
    """Summary statistics of a window (hold and flight: mean, SD, median), NOT the P2 encoder."""

    name = "stand-in summary statistics (not the P2 encoder)"

    def embed(self, windows: Sequence[Any]) -> Any:
        import numpy as np

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


def settings(seed: int, outer_folds: int | None = None, inner_folds: int | None = None) -> fe.CVSettings:
    d, models, scoring = _cfg("eval")["fusion_dryrun"], _cfg("models"), _cfg("scoring")
    return fe.CVSettings(outer_folds or int(d["outer_folds"]), inner_folds or int(d["inner_folds"]),
                         tuple(float(c) for c in models["fusion"]["c_grid"]), float(scoring["smoothing"]["lambda"]),
                         float(scoring["target_false_flag_rate"]), int(models["enrollment"]["g_min"]), seed)


def run(cfg: Mapping[str, Any], seed: int, embedder: Any, users: int | None = None, outer_folds: int | None = None,
        inner_folds: int | None = None, resamples: int | None = None, full: bool = True, finetune: Any = None) -> dict[str, Any]:
    _, sessions = generate(users or int(cfg["users"]), practice_texts(), EXAM_TEXT, cfg, seed)
    prep = fe.prepare(sessions, practice_texts(), {"features": _cfg("features"), "scoring": _cfg("scoring"), "models": _cfg("models")})
    harness = fe.Harness(prep, embedder, finetune)
    st = settings(seed, outer_folds, inner_folds)
    n_boot = resamples or int(_cfg("eval")["bootstrap"]["resamples"])
    if full:
        result = fe.evaluate(harness, st, n_boot)
    else:                                              # the main run only (fast tests)
        main = harness.cross_validate(st)
        result = {"summary": fe.summary(main["outcomes"], n_boot, seed), "folds": main["folds"],
                  "calibration": fe.calibration(main["tick_p"], main["tick_y"]), "per_user": fe.per_user(main["outcomes"])}
    return {"synthetic": True, "banner": BANNER, "dataset_id": cfg["dataset_id"], "users": len(prep.users),
            "embedder": getattr(harness.encoder_for(frozenset(prep.users), seed), "name", "encoder"), **result}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fusion pipeline dry run on SYNTHETIC sessions.")
    parser.add_argument("--out", type=Path, required=True, help="report path; the file name must contain 'synthetic'")
    parser.add_argument("--encoder", type=Path, help="the P2 encoder file (default: a stand-in embedding)")
    parser.add_argument("--finetune", action="store_true", help="fine-tune the encoder per outer fold (SPEC 12.3 step 1)")
    parser.add_argument("--users", type=int)
    args = parser.parse_args(argv)
    if "synthetic" not in args.out.name.lower():
        parser.error("the output file name must contain 'synthetic' (SPEC 10.11)")
    if args.finetune and not args.encoder:
        parser.error("--finetune needs --encoder")
    seed = int(_cfg("global")["seed"])
    embedder = load_encoder(args.encoder) if args.encoder else StandInEmbedder()
    finetune = None
    if args.finetune:
        from .finetune import make_finetune

        finetune = make_finetune(_cfg("models")["keystroke_encoder"], _cfg("models")["finetune"])
    cfg = _cfg("eval")["fusion_dryrun"]
    result = run(cfg, seed, embedder, users=args.users, finetune=finetune)
    manifest = run_manifest(seed, (result["dataset_id"],), synthetic=True)
    dataset_md = (f"Data: {result['users']} SYNTHETIC users (`{result['dataset_id']}`), one session per condition each. "
                  f"Folds: user-disjoint nested CV. Keystroke embedding: {result['embedder']}. A5-A7 are not generated "
                  f"(they need code variation); IMP is impersonation (SPEC 9.4).")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(fe.render(result, "Fusion pipeline dry run — SYNTHETIC", BANNER, manifest.as_markdown(), dataset_md), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps({"manifest": manifest.__dict__, **result}, indent=2, default=str), encoding="utf-8")
    print(f"wrote {args.out} and {args.out.with_suffix('.json').name} (SYNTHETIC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
