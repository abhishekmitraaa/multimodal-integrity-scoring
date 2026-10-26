"""The trained keystroke encoder at report time (prototype rule, D-033), with reference ranges.

The model file (from P2, trained on D1) and its calibration JSON live in the data folder, never in
the repository (D1 licence). The reference ranges come from D1 *validation* subjects: for G
enrollment windows, the distances of genuine queries and of other people's queries to a
prototype. They describe memorised English sentences, not code typing, so reports present them as
reference ranges, not as calibrated probabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Reference:
    g: int
    genuine: dict[str, float]          # distance quantiles for the same person, e.g. {"p50": .., "p95": ..}
    impostor: dict[str, float]         # distance quantiles for other people
    eer_threshold: float               # global threshold where false accepts = false rejects


class KeystrokeModel:
    def __init__(self, model_path: Path, encoder_cfg: Mapping[str, Any]) -> None:
        import torch

        from .encoder import EncoderConfig, TypeNetEncoder

        self._torch = torch
        self.model = TypeNetEncoder(EncoderConfig.from_config(encoder_cfg))
        self.model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
        self.model.eval()
        cal = json.loads(model_path.with_suffix(".calibration.json").read_text(encoding="utf-8"))
        self.calibration_meta = {k: v for k, v in cal.items() if k != "by_g"}
        self.references = {int(g): Reference(int(g), r["genuine"], r["impostor"], float(r["eer_threshold"]))
                           for g, r in cal["by_g"].items()}

    def reference(self, g: int) -> Reference:
        return self.references[min(max(g, 1), max(self.references))]

    def embed(self, windows: Sequence[NDArray[np.float32]]) -> NDArray[np.float32]:
        if not windows:
            return np.zeros((0, self.model.lstm2.hidden_size), dtype=np.float32)
        x = self._torch.from_numpy(np.stack(windows).astype(np.float32))
        lengths = self._torch.full((len(windows),), x.shape[1], dtype=self._torch.int64)
        with self._torch.no_grad():
            return self.model(x, lengths).numpy()


def prototype_distances(prototype: NDArray[np.float32], embeddings: NDArray[np.float32]) -> NDArray[np.float64]:
    return np.linalg.norm(embeddings.astype(np.float64) - prototype.astype(np.float64), axis=1)
