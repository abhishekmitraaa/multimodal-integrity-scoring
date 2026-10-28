"""Evaluate the study data (D2) with the harness (SPEC 12.3-12.6, D-047).

Reads a bundle written by integrity_eval.d2_export. Refuses a bundle labelled `development` (team
testing) unless --development is given, and then labels the report DEVELOPMENT, not for study
results. Every run appends a line to the test-access ledger (SPEC 12.3); --final marks the run that
goes into the report, and the report prints the ledger.

Usage:
  python -m integrity_eval.d2_eval --bundle D:\\integrity-data\\derived\\d2_... --encoder C:\\integrity-data\\models\\keystroke_encoder_m70.pt
      --out D:\\integrity-data\\derived\\d2_eval\\report.md [--finetune] [--final] [--purpose "primary analysis"]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from . import fusion_eval as fe
from .fusion_dryrun import _cfg, load_encoder, practice_texts, settings
from .ledger import read_ledger, record_test_access
from .manifest import run_manifest

DEVELOPMENT_BANNER = "DEVELOPMENT DATA (team testing): checks the pipeline on real browsers; not study results."


class BundleError(ValueError):
    pass


def load_bundle(folder: Path, allow_development: bool) -> tuple[dict[str, Any], list[fe.Session]]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset") == "development" or manifest.get("not_for_study"):
        if not allow_development:
            raise BundleError("this bundle is labelled development (not for study); use --development to test the pipeline on it")
    elif manifest.get("dataset") != "d2":
        raise BundleError(f"not a D2 bundle: dataset {manifest.get('dataset')!r}")
    sessions = []
    for line in (folder / "sessions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] == "practice" and r["stage"] == "baseline":
            sessions.append(fe.Session(r["pseudonym"], "practice", "practice", r["problem_id"], r["events"]))
        elif r["kind"] == "exam" and r["condition"]:
            sessions.append(fe.Session(r["pseudonym"], "exam", r["condition"], r["problem_id"], r["events"],
                                       onset_s=r["onset_s"], covariates=dict(r["covariates"])))
        # the baseline check (stage check) is held out of both the baseline and the exam set
    return manifest, sessions


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the D2 study data.")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--finetune", action="store_true", help="fine-tune the encoder per outer fold (SPEC 12.3 step 1)")
    parser.add_argument("--final", action="store_true", help="the run that goes into the report (ledger)")
    parser.add_argument("--purpose", default="d2 evaluation")
    parser.add_argument("--development", action="store_true", help="allow a development bundle (team testing)")
    args = parser.parse_args(argv)
    try:
        manifest, sessions = load_bundle(args.bundle, args.development)
    except BundleError as exc:
        parser.error(str(exc))
    seed = int(_cfg("global")["seed"])
    eval_cfg = _cfg("eval")
    prep = fe.prepare(sessions, practice_texts(), {"features": _cfg("features"), "scoring": _cfg("scoring"), "models": _cfg("models")})
    finetune = None
    if args.finetune:
        from .finetune import make_finetune

        finetune = make_finetune(_cfg("models")["keystroke_encoder"], _cfg("models")["finetune"])
    harness = fe.Harness(prep, load_encoder(args.encoder), finetune)
    st = settings(seed, int(eval_cfg["split"]["outer_folds"]), None)
    development = manifest["dataset"] == "development"
    entry = None
    if not development:                                         # every computation on test users is in the ledger
        entry = record_test_access(args.purpose, "d2", len(prep.users), args.final, seed,
                                   extra={"bundle": str(args.bundle), "finetune": args.finetune})
    result = fe.evaluate(harness, st, int(eval_cfg["bootstrap"]["resamples"]), repeat_seeds=tuple(eval_cfg["split"]["repeats_seeds"]))
    m = run_manifest(seed, (manifest["dataset"],), synthetic=False)
    dataset_md = (f"Data: `{manifest['dataset']}` bundle {args.bundle.name} ({manifest['participants']} participants, created "
                  f"{manifest['created_utc']}). Folds: user-disjoint nested CV, {st.outer_folds} outer folds. Encoder: "
                  f"{getattr(harness.encoder_for(frozenset(prep.users), seed), 'name', 'P2 encoder')}.")
    if entry is not None:
        finals = [e for e in read_ledger() if e.get("dataset") == "d2" and e.get("final")]
        dataset_md += (f"\n\nTest-access ledger: {len(read_ledger())} entries; this run: {entry['time_utc']} "
                       f"({'final' if args.final else 'not final'}). Final entries for D2: {len(finals)}"
                       + (" — more than one: explain in the report (SPEC 12.3)." if len(finals) > 1 else "."))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    title = "Evaluation on the study data (D2)" if not development else "Pipeline check on development data"
    args.out.write_text(fe.render(result, title, DEVELOPMENT_BANNER if development else None, m.as_markdown(), dataset_md), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps({"manifest": m.__dict__, "bundle": manifest, **result}, indent=2, default=str),
                                             encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
