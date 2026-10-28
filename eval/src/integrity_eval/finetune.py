"""Per-fold fine-tuning of the P2 encoder on training users' practice windows (SPEC 12.3, step 1)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray


class TunedEncoder:
    """A fine-tuned copy of the encoder with the serving model's embed() interface."""

    def __init__(self, model: Any, name: str) -> None:
        import torch

        self._torch = torch
        self.model = model.eval()
        self.name = name

    def embed(self, windows: Sequence[NDArray[np.float32]]) -> NDArray[np.float32]:
        if not windows:
            return np.zeros((0, self.model.lstm2.hidden_size), dtype=np.float32)
        x = self._torch.from_numpy(np.stack(windows).astype(np.float32))
        lengths = self._torch.full((len(windows),), x.shape[1], dtype=self._torch.int64)
        with self._torch.no_grad():
            return self.model(x, lengths).numpy()


def make_finetune(encoder_cfg: Mapping[str, Any], finetune_cfg: Mapping[str, Any]) -> Any:
    """finetune(base, prep, train_users, seed) -> TunedEncoder, for fusion_eval.Harness."""

    def finetune(base: Any, prep: Any, train: frozenset[str], seed: int) -> TunedEncoder:
        from integrity_ml.encoder import EncoderConfig, SequenceBank, train as train_encoder

        subjects = [[(w, w.shape[0]) for w in prep.enroll[u]] for u in sorted(train) if len(prep.enroll[u]) >= 2]
        if len(subjects) < 2:                                    # nothing to learn from: keep the pretrained encoder
            return TunedEncoder(base.model, getattr(base, "name", "P2 encoder"))
        cfg = EncoderConfig.from_config(encoder_cfg, learning_rate=float(finetune_cfg["learning_rate"]),
                                        batch_size=int(finetune_cfg["batch_size"]),
                                        batches_per_epoch=int(finetune_cfg["batches_per_epoch"]))
        model, _ = train_encoder(SequenceBank.build(subjects), cfg, seed, epochs=int(finetune_cfg["epochs"]),
                                 init_state=base.model.state_dict())
        return TunedEncoder(model.cpu(), f"{getattr(base, 'name', 'P2 encoder')}, fine-tuned per fold")

    return finetune
