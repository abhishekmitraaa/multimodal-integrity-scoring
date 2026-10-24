"""TypeNet authentication protocol (p2_protocol.md §6–7) for any distance scorer.

For each test subject i: gallery = sequences 0..G-1; genuine queries = sequences 10..14 of i; one
impostor query = sequence 11 of every other test subject (the authors' README code). EER is
computed per subject with the authors' sweep and averaged (TypeNet §5.1). A global EER over all
pooled scores is reported too, since our system uses one threshold. Unavailable scores (None) are
dropped and counted, so the EER is "on available comparisons" (D-031).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Protocol, Sequence, TypeVar

import numpy as np

from integrity_ml.baselines import (
    DigraphProfile, digraph_distance, digraph_profile, seqstat_distance, sequence_stats,
)
from integrity_ml.eer import EerSummary, eer_exact, eer_sweep, summarise
from integrity_ml.keystroke import Keystroke

KeySeq = Sequence[Keystroke]
P = TypeVar("P")
G = TypeVar("G")


class Scorer(Protocol, Generic[P, G]):
    name: str

    def prepare(self, seq: KeySeq) -> P: ...
    def gallery(self, seqs: Sequence[KeySeq], prepared: Sequence[P]) -> G: ...
    def distance(self, gallery: G, query: P) -> float | None: ...


@dataclass(frozen=True)
class DigraphScorer:
    min_occurrences: int
    min_shared_items: int
    name: str = "digraph (SPEC 7.2)"

    def prepare(self, seq: KeySeq) -> DigraphProfile:
        return digraph_profile([seq], min_occurrences=1)

    def gallery(self, seqs: Sequence[KeySeq], prepared: Sequence[DigraphProfile]) -> DigraphProfile:
        return digraph_profile(seqs, self.min_occurrences)

    def distance(self, gallery: DigraphProfile, query: DigraphProfile) -> float | None:
        return digraph_distance(gallery, query, self.min_shared_items)


@dataclass(frozen=True)
class SeqStatScorer:
    scale: np.ndarray
    name: str = "sequence statistics (scaled Manhattan)"

    def prepare(self, seq: KeySeq) -> np.ndarray:
        return sequence_stats(seq)

    def gallery(self, seqs: Sequence[KeySeq], prepared: Sequence[np.ndarray]) -> Sequence[np.ndarray]:
        return prepared

    def distance(self, gallery: Sequence[np.ndarray], query: np.ndarray) -> float | None:
        return seqstat_distance(gallery, query, self.scale)


@dataclass(frozen=True)
class AuthResult:
    scorer: str
    g: int
    per_subject: EerSummary
    global_eer: float
    genuine_available: float
    impostor_available: float
    subjects_without_scores: int


def run_authentication(
    subjects: Sequence[Sequence[KeySeq]],
    scorer: Scorer[Any, Any],
    g: int,
    genuine_idx: Sequence[int],
    impostor_idx: int,
    steps: int,
) -> AuthResult:
    if any(len(s) <= max([*genuine_idx, impostor_idx, g - 1]) for s in subjects):
        raise ValueError("every subject needs the gallery, genuine-query and impostor-query sequences")
    if g > min(genuine_idx):
        raise ValueError("gallery overlaps the genuine queries")
    prepared = [[scorer.prepare(seq) for seq in subj] for subj in subjects]
    eers: list[float] = []
    all_g: list[float] = []
    all_i: list[float] = []
    n_gen = n_imp = avail_gen = avail_imp = skipped = 0
    for i, subj in enumerate(subjects):
        model = scorer.gallery(subj[:g], prepared[i][:g])
        gen = [scorer.distance(model, prepared[i][q]) for q in genuine_idx]
        imp = [scorer.distance(model, prepared[j][impostor_idx]) for j in range(len(subjects)) if j != i]
        n_gen, n_imp = n_gen + len(gen), n_imp + len(imp)
        gen_ok = [d for d in gen if d is not None]
        imp_ok = [d for d in imp if d is not None]
        avail_gen, avail_imp = avail_gen + len(gen_ok), avail_imp + len(imp_ok)
        if not gen_ok or not imp_ok:
            skipped += 1
            continue
        eers.append(eer_sweep(gen_ok, imp_ok, steps))
        all_g += gen_ok
        all_i += imp_ok
    return AuthResult(
        scorer=scorer.name,
        g=g,
        per_subject=summarise(eers),
        global_eer=eer_exact(all_g, all_i) if all_g and all_i else float("nan"),
        genuine_available=avail_gen / n_gen if n_gen else 0.0,
        impostor_available=avail_imp / n_imp if n_imp else 0.0,
        subjects_without_scores=skipped,
    )
