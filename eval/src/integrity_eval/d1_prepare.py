"""Preprocess D1 (Aalto 136M Keystrokes) into TypeNet matrices, outside the repository.

Writes to <out>/ :
  x.npy        (P, 15, 70, 5) float16  TypeNet rows (keycode/255, HL, IL, PL, RL in s), zero-padded
  lengths.npy  (P, 15) int16           real keystrokes per sentence (<= 70)
  pids.npy     (P,) int64              participant ids, ascending (TypeNet's "first 68,000" order)
  summary.json                         counts, parse statistics, keyboard types, zip sha256
Only participants with exactly 15 non-empty sentences are kept (TypeNet §3). M = 50 is the first 50
rows, because latencies are computed before truncation (p2_protocol.md §3).

Usage: python -m integrity_eval.d1_prepare <Keystrokes.zip> <out dir> [--workers 8]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np

from integrity_ml.sequences import typenet_matrix

from .d1_aalto import keycode_of, parse_participant, participant_members
from .manifest import REPO_ROOT

M_MAX, SENTENCES = 70, 15
_zip: zipfile.ZipFile | None = None


def _init(zip_path: str) -> None:
    global _zip
    _zip = zipfile.ZipFile(zip_path)


def _work(item: tuple[int, str]) -> tuple[int, Any, Any, dict[str, int]]:
    pid, name = item
    assert _zip is not None
    p = parse_participant(pid, _zip.read(name).decode("utf-8", "replace"))
    stats = {k: int(v) for k, v in vars(p.stats).items()}
    stats["sentences"] = len(p.sentences)
    if len(p.sentences) != SENTENCES:
        return pid, None, None, stats
    mats = [typenet_matrix(s, M_MAX, keycode=keycode_of) for s in p.sentences]
    x = np.stack([m for m, _ in mats]).astype(np.float16)
    lengths = np.array([n for _, n in mats], dtype=np.int16)
    return pid, x, lengths, stats


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def keyboard_types(zip_path: Path, pids: set[int]) -> dict[str, int]:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith("metadata_participants.txt"))
        lines = z.read(name).decode("utf-8", "replace").splitlines()
    header = lines[0].split("\t")
    col = header.index("KEYBOARD_TYPE")
    counts: Counter[str] = Counter()
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) > col and f[0].isdigit() and int(f[0]) in pids:
            counts[f[col]] += 1
    return dict(counts.most_common())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Preprocess D1 into TypeNet matrices (outside the repo).")
    ap.add_argument("zip", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if REPO_ROOT.resolve() in out.parents or out == REPO_ROOT.resolve():
        print("d1_prepare: output must be outside the repository", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    members = participant_members(args.zip)
    totals: Counter[str] = Counter()
    sentence_counts: Counter[int] = Counter()
    kept_pids: list[int] = []
    tmp_x = np.lib.format.open_memmap(out / "x_all.npy", mode="w+", dtype=np.float16, shape=(len(members), SENTENCES, M_MAX, 5))
    tmp_len = np.zeros((len(members), SENTENCES), dtype=np.int16)
    with Pool(args.workers, initializer=_init, initargs=(str(args.zip),)) as pool:
        for i, (pid, x, lengths, stats) in enumerate(pool.imap(_work, members, chunksize=64)):
            sentence_counts[stats.pop("sentences")] += 1
            totals.update(stats)
            if x is not None:
                tmp_x[len(kept_pids)] = x
                tmp_len[len(kept_pids)] = lengths
                kept_pids.append(pid)
            if (i + 1) % 20000 == 0:
                print(f"  {i + 1}/{len(members)} parsed, {len(kept_pids)} kept", flush=True)
    n = len(kept_pids)
    x_final = np.lib.format.open_memmap(out / "x.npy", mode="w+", dtype=np.float16, shape=(n, SENTENCES, M_MAX, 5))
    for start in range(0, n, 10000):
        x_final[start:start + 10000] = tmp_x[start:min(start + 10000, n)]
    x_final.flush()
    del x_final, tmp_x
    (out / "x_all.npy").unlink()
    np.save(out / "lengths.npy", tmp_len[:n])
    np.save(out / "pids.npy", np.array(kept_pids, dtype=np.int64))
    summary = {
        "dataset": "d1_aalto_136m_keystrokes", "zip_sha256": sha256(args.zip), "participants_in_zip": len(members),
        "kept_exactly_15_sentences": n, "sentences_per_participant": {str(k): v for k, v in sorted(sentence_counts.items())},
        "parse": dict(totals), "keyboard_types_of_kept": keyboard_types(args.zip, set(kept_pids)),
        "m_max": M_MAX, "dtype": "float16", "licence": "non-commercial research use with attribution (readme.txt)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
