"""Reference ranges for the serving keystroke model, from D1 validation subjects (not test subjects).

For G = 1..10 enrollment sequences: prototype = mean embedding of the first G sentences; genuine
distances = the subject's sentences 10..14 to it; impostor distances = sentence 11 of every other
validation subject to it (the P2 protocol's indices). The same 1.5 s latency clip as live windows.
Writes <out>/keystroke_encoder_m70.pt and .calibration.json (outside the repository).

Usage: python -m integrity_eval.serving_calibration <prepared d1 dir> <trained .pt> <out dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import yaml

from integrity_ml.serving import prototype_distances

from .manifest import REPO_ROOT, run_manifest
from .p2_d1 import D1

QUANTILES = {"genuine": [50, 90, 95, 99], "impostor": [1, 5, 10, 50]}


def eer_threshold(genuine: np.ndarray, impostor: np.ndarray) -> float:
    thresholds = np.unique(np.concatenate([genuine, impostor]))
    far = np.searchsorted(np.sort(impostor), thresholds, side="left") / impostor.size
    frr = 1.0 - np.searchsorted(np.sort(genuine), thresholds, side="left") / genuine.size
    return float(thresholds[int(np.argmin(np.abs(far - frr)))])


def main(argv: list[str] | None = None) -> int:
    import torch

    from integrity_ml.encoder import EncoderConfig, TypeNetEncoder, embed

    ap = argparse.ArgumentParser(description="Reference ranges for the serving keystroke model.")
    ap.add_argument("prepared", type=Path)
    ap.add_argument("model", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if REPO_ROOT.resolve() in out.parents:
        print("serving_calibration: output must be outside the repository", file=sys.stderr)
        return 2
    cfg = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    feats = yaml.safe_load((REPO_ROOT / "config" / "features.yaml").read_text(encoding="utf-8"))["keystroke"]
    m, clip = int(feats["window_keystrokes"]), float(feats["latency_clip_ms"]) / 1000
    model = TypeNetEncoder(EncoderConfig.from_config(cfg["keystroke_encoder"]))
    model.load_state_dict(torch.load(args.model, map_location="cpu", weights_only=True))
    d = D1(args.prepared)
    x = np.asarray(d.x[d.val], dtype=np.float32)[:, :, :m].copy()
    x[..., 1:] = np.clip(x[..., 1:], -clip, clip)
    lengths = np.minimum(d.lengths[d.val], m).astype(np.int64)
    emb = embed(model, x.reshape(-1, m, 5), lengths.reshape(-1)).reshape(len(d.val), 15, -1)
    rep = cfg["reproduction"]
    by_g = {}
    for g in range(1, 11):
        protos = emb[:, :g].mean(axis=1)
        genuine = np.concatenate([prototype_distances(protos[i], emb[i, rep["genuine_query_indices"]]) for i in range(len(emb))])
        impostor = np.concatenate([prototype_distances(protos[i], np.delete(emb[:, rep["impostor_query_index"]], i, axis=0))
                                   for i in range(len(emb))])
        by_g[str(g)] = {
            "genuine": {f"p{q}": float(np.percentile(genuine, q)) for q in QUANTILES["genuine"]},
            "impostor": {f"p{q}": float(np.percentile(impostor, q)) for q in QUANTILES["impostor"]},
            "eer_threshold": eer_threshold(genuine, impostor),
        }
        print(f"G={g}: genuine p95 {by_g[str(g)]['genuine']['p95']:.3f}  impostor p5 {by_g[str(g)]['impostor']['p5']:.3f}  "
              f"EER threshold {by_g[str(g)]['eer_threshold']:.3f}")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "keystroke_encoder_m70.pt"
    shutil.copyfile(args.model, target)
    manifest = run_manifest(int(yaml.safe_load((REPO_ROOT / "config" / "global.yaml").read_text())["seed"]),
                            ("d1_aalto_136m_keystrokes",), synthetic=False)
    meta = {
        "source": "D1 (Aalto 136M Keystrokes) validation subjects 67000-67999, held out from training; not test subjects",
        "rule": "prototype (D-033)", "m": m, "latency_clip_s": clip, "model_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "note": "Memorised English sentences, not code typing: reference ranges, not calibrated probabilities.",
        "git_commit": manifest.git_commit, "config_sha256": manifest.config_sha256, "by_g": by_g,
    }
    target.with_suffix(".calibration.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {target} and its calibration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
