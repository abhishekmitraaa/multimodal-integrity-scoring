"""SYNTHETIC keystroke data (D3) for pipeline tests only. Never a person; never reported as a result.

Each synthetic subject types 15 sequences of the same length drawn from a shared word list. Timing
is log-normal around population values:

- shared by everyone: a difficulty factor per ordered key pair (flight) and a hold factor per key;
- per subject, scaled by `separation`: an overall speed, a deviation per key pair and per key;
- per keystroke: within-subject noise.

press_{i+1} = press_i + flight and release_i = press_i + hold, so overlaps (negative IL) arise
whenever a hold is longer than the next flight. separation = 0 makes every subject type
identically, so an identity EER near 50% is expected. Larger separation should give lower EER.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from .keystroke import Keystroke


@dataclass(frozen=True)
class SyntheticConfig:
    subjects: int
    sequences_per_subject: int
    keys_per_sequence: int
    alphabet: tuple[str, ...]
    vocabulary_words: int
    base_flight_ms: float
    base_hold_ms: float
    digraph_difficulty_log_sd: float
    key_hold_log_sd: float
    user_speed_log_sd: float
    user_digraph_log_sd: float
    user_hold_log_sd: float
    noise_flight_log_sd: float
    noise_hold_log_sd: float
    separation: float
    seed: int
    dataset_id: str

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], separation: float, seed: int, **overrides: Any) -> SyntheticConfig:
        fields = {k: v for k, v in cfg.items() if k in cls.__dataclass_fields__}
        fields["alphabet"] = tuple(fields["alphabet"])
        return cls(**{**fields, "separation": separation, "seed": seed, **overrides})


@dataclass(frozen=True)
class SyntheticKeystrokeDataset:
    subjects: list[list[list[Keystroke]]]   # subject -> sequence -> keystrokes
    config: SyntheticConfig
    synthetic: bool = True


def _vocabulary(rng: np.random.Generator, letters: int, n_words: int) -> list[list[int]]:
    lengths = rng.integers(2, 9, size=n_words)
    return [list(rng.integers(0, letters, size=int(n))) for n in lengths]


def _text(rng: np.random.Generator, words: list[list[int]], zipf: np.ndarray, space: int, n: int) -> list[int]:
    keys: list[int] = []
    while len(keys) < n:
        keys += words[int(rng.choice(len(words), p=zipf))] + [space]
    return keys[:n]


def generate(cfg: SyntheticConfig) -> SyntheticKeystrokeDataset:
    rng = np.random.default_rng(cfg.seed)
    n_keys = len(cfg.alphabet)
    space = cfg.alphabet.index("Space") if "Space" in cfg.alphabet else n_keys - 1
    letters = [i for i in range(n_keys) if i != space]
    words = [[letters[k] for k in w] for w in _vocabulary(rng, len(letters), cfg.vocabulary_words)]
    zipf = 1.0 / np.arange(1, len(words) + 1)
    zipf /= zipf.sum()

    difficulty = np.exp(rng.normal(0.0, cfg.digraph_difficulty_log_sd, size=(n_keys, n_keys)))
    hold_factor = np.exp(rng.normal(0.0, cfg.key_hold_log_sd, size=n_keys))
    s = cfg.separation
    subjects = []
    for _ in range(cfg.subjects):
        speed = np.exp(rng.normal(0.0, cfg.user_speed_log_sd * s))
        user_digraph = np.exp(rng.normal(0.0, cfg.user_digraph_log_sd * s, size=(n_keys, n_keys)))
        user_hold = np.exp(rng.normal(0.0, cfg.user_hold_log_sd * s, size=n_keys))
        sequences = []
        for _ in range(cfg.sequences_per_subject):
            keys = _text(rng, words, zipf, space, cfg.keys_per_sequence)
            t_us = 0.0
            seq = []
            for i, key in enumerate(keys):
                hold = cfg.base_hold_ms * hold_factor[key] * user_hold[key] * np.exp(rng.normal(0.0, cfg.noise_hold_log_sd))
                seq.append(Keystroke(cfg.alphabet[key], round(t_us), round(t_us + hold * 1000)))
                if i + 1 < len(keys):
                    nxt = keys[i + 1]
                    flight = (cfg.base_flight_ms * speed * difficulty[key, nxt] * user_digraph[key, nxt]
                              * np.exp(rng.normal(0.0, cfg.noise_flight_log_sd)))
                    t_us += flight * 1000
            sequences.append(seq)
        subjects.append(sequences)
    return SyntheticKeystrokeDataset(subjects, cfg)
