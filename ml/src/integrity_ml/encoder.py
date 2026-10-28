"""TypeNet-style keystroke encoder in PyTorch (SPEC 7.1; p2_protocol.md §4–5, deviations §9).

Masking -> BatchNorm(5) -> LSTM(128) -> BatchNorm(128) -> Dropout(0.5) -> LSTM(128); the embedding is
the second LSTM's hidden state at the last real keystroke (TypeNet §4.2, Fig. 2). Deviations:

- no recurrent dropout (deviation 3), so the fast cuDNN LSTM can be used;
- packed sequences, with batch norm statistics over real keystrokes only (deviation 4);
- Keras defaults copied where they matter (deviation 2): batch norm momentum 0.99 (PyTorch
  0.01) and eps 1e-3; Glorot-uniform input weights; orthogonal recurrent weights; zero biases with
  forget-gate bias 1.

Loss: max(0, d(a,p)^2 - d(a,n)^2 + margin) with random triplets (TypeNet Eq. 4, §4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import torch
from numpy.typing import NDArray
from torch import Tensor, nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


@dataclass(frozen=True)
class EncoderConfig:
    input_features: int = 5
    hidden_units: int = 128
    dropout: float = 0.5
    triplet_margin: float = 1.5
    learning_rate: float = 0.05
    adam_betas: tuple[float, float] = (0.9, 0.999)
    adam_eps: float = 1e-8
    batch_size: int = 512
    max_epochs: int = 200
    batches_per_epoch: int = 150

    @classmethod
    def from_config(cls, enc: Mapping[str, Any], **overrides: Any) -> EncoderConfig:
        if enc.get("lstm_layers", 2) != 2 or enc.get("embedding_dim", enc.get("hidden_units")) != enc.get("hidden_units"):
            raise ValueError("this encoder implements TypeNet's 2 LSTM layers with embedding = hidden size")
        fields = {k: v for k, v in enc.items() if k in cls.__dataclass_fields__}
        if "adam_betas" in fields:
            fields["adam_betas"] = tuple(fields["adam_betas"])
        return cls(**{**fields, **overrides})


def _masked_bn(bn: nn.BatchNorm1d, x: Tensor, mask: Tensor) -> Tensor:
    """Batch norm over real time steps only; padded steps stay zero."""
    out = torch.zeros_like(x)
    out[mask] = bn(x[mask])
    return out


class TypeNetEncoder(nn.Module):
    def __init__(self, cfg: EncoderConfig = EncoderConfig()) -> None:
        super().__init__()
        f, h = cfg.input_features, cfg.hidden_units
        self.bn_in = nn.BatchNorm1d(f, momentum=0.01, eps=1e-3)
        self.lstm1 = nn.LSTM(f, h, batch_first=True)
        self.bn_mid = nn.BatchNorm1d(h, momentum=0.01, eps=1e-3)
        self.dropout = nn.Dropout(cfg.dropout)
        self.lstm2 = nn.LSTM(h, h, batch_first=True)
        for lstm in (self.lstm1, self.lstm2):
            nn.init.xavier_uniform_(lstm.weight_ih_l0)
            nn.init.orthogonal_(lstm.weight_hh_l0)
            nn.init.zeros_(lstm.bias_ih_l0)
            nn.init.zeros_(lstm.bias_hh_l0)
            with torch.no_grad():
                lstm.bias_ih_l0[h:2 * h].fill_(1.0)   # PyTorch gate order: input, forget, cell, output

    def forward(self, x: Tensor, lengths: Tensor) -> Tensor:
        """x: (B, M, 5) zero-padded; lengths: (B,) >= 1. Returns (B, 128)."""
        b, m, _ = x.shape
        mask = torch.arange(m, device=x.device)[None, :] < lengths[:, None]
        x = _masked_bn(self.bn_in, x, mask)
        cpu_lengths = lengths.detach().cpu()
        out, _ = self.lstm1(pack_padded_sequence(x, cpu_lengths, batch_first=True, enforce_sorted=False))
        out, _ = pad_packed_sequence(out, batch_first=True, total_length=m)
        out = self.dropout(_masked_bn(self.bn_mid, out, mask))
        _, (h_n, _) = self.lstm2(pack_padded_sequence(out, cpu_lengths, batch_first=True, enforce_sorted=False))
        return h_n[-1]


def triplet_loss(anchor: Tensor, positive: Tensor, negative: Tensor, margin: float) -> Tensor:
    d_ap = (anchor - positive).pow(2).sum(dim=1)
    d_an = (anchor - negative).pow(2).sum(dim=1)
    return torch.clamp(d_ap - d_an + margin, min=0.0).mean()


@dataclass(frozen=True)
class SequenceBank:
    """All training sequences: x (N, M, 5), lengths (N,), subject index per sequence."""

    x: NDArray[np.float32]
    lengths: NDArray[np.int64]
    subject: NDArray[np.int64]

    @classmethod
    def build(cls, subjects: Sequence[Sequence[tuple[NDArray[np.float32], int]]]) -> SequenceBank:
        rows = [(mat, n, s) for s, seqs in enumerate(subjects) for mat, n in seqs if n > 0]
        if len({s for _, _, s in rows}) < 2:
            raise ValueError("triplets need at least two subjects")
        return cls(np.stack([r[0] for r in rows]), np.array([r[1] for r in rows], dtype=np.int64),
                   np.array([r[2] for r in rows], dtype=np.int64))


@dataclass(frozen=True)
class TripletIndex:
    """Sequences grouped by subject once, so sampling a batch is vectorised (68,000 subjects)."""

    order: NDArray[np.int64]     # sequence indices sorted by subject
    start: NDArray[np.int64]     # first position in `order` for each eligible subject
    count: NDArray[np.int64]     # sequences per eligible subject (>= 2)
    subject: NDArray[np.int64]   # subject of every sequence

    @classmethod
    def build(cls, bank: SequenceBank) -> TripletIndex:
        order = np.argsort(bank.subject, kind="stable")
        subjects, start, count = np.unique(bank.subject[order], return_index=True, return_counts=True)
        keep = count >= 2
        if not keep.any():
            raise ValueError("no subject has two sequences")
        if len(subjects) < 2:
            raise ValueError("triplets need at least two subjects")
        return cls(order, start[keep], count[keep], bank.subject)


def sample_triplets(bank: SequenceBank, batch: int, rng: np.random.Generator,
                    index: TripletIndex | None = None) -> tuple[NDArray[np.int64], ...]:
    """Random triplets (TypeNet §4.4): anchor and positive are two different sequences of one
    subject; the negative is a random sequence of another subject."""
    ix = index or TripletIndex.build(bank)
    pick = rng.integers(0, len(ix.start), size=batch)
    start, count = ix.start[pick], ix.count[pick]
    a_off = rng.integers(0, count)
    p_off = (a_off + rng.integers(1, count)) % count            # a different sequence of the same subject
    anchors, positives = ix.order[start + a_off], ix.order[start + p_off]
    negatives = rng.integers(0, len(ix.subject), size=batch)
    clash = ix.subject[negatives] == ix.subject[anchors]
    while clash.any():                                          # redraw the rare same-subject negatives
        negatives[clash] = rng.integers(0, len(ix.subject), size=int(clash.sum()))
        clash = ix.subject[negatives] == ix.subject[anchors]
    return anchors, positives, negatives


def seed_everything(seed: int) -> None:
    import random

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _save_checkpoint(path: Path, model: TypeNetEncoder, opt: torch.optim.Optimizer, history: list[float],
                     rng: np.random.Generator) -> None:
    state = {
        "model": model.state_dict(), "opt": opt.state_dict(), "history": history,
        "numpy_rng": rng.bit_generator.state, "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(state, tmp)
    tmp.replace(path)   # atomic: a crash mid-write never leaves a broken checkpoint


def train(
    bank: SequenceBank,
    cfg: EncoderConfig,
    seed: int,
    device: str = "cpu",
    epochs: int | None = None,
    log: Callable[[int, float], None] | None = None,
    checkpoint: Path | None = None,
    checkpoint_every: int = 10,
    init_state: Mapping[str, Any] | None = None,
) -> tuple[TypeNetEncoder, list[float]]:
    """Fixed number of epochs of random-triplet batches; returns the final model (no selection).

    With `checkpoint`, state (model, optimiser, loss history and every RNG) is saved every
    `checkpoint_every` epochs and training resumes from it, so a resumed run equals an
    uninterrupted one. With `init_state` (a state_dict), training starts from those weights:
    fine-tuning the P2 encoder on study users (SPEC 12.3, step 1).
    """
    seed_everything(seed)
    rng = np.random.default_rng(seed)
    model = TypeNetEncoder(cfg).to(device)
    if init_state is not None:
        model.load_state_dict(init_state)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate, betas=cfg.adam_betas, eps=cfg.adam_eps)
    history: list[float] = []
    if checkpoint is not None and checkpoint.exists():
        state = torch.load(checkpoint, map_location=device, weights_only=False)   # our own file: includes RNG state
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        history = list(state["history"])
        rng.bit_generator.state = state["numpy_rng"]
        torch.set_rng_state(state["torch_rng"])
        if state["cuda_rng"] and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(state["cuda_rng"])
    # The bank may be float16 (D1: about 0.7 GB for 68,000 x 15 x 70 x 5); batches are cast to float32.
    x = torch.from_numpy(np.array(bank.x, copy=True)).to(device)
    lengths = torch.from_numpy(np.array(bank.lengths, copy=True)).to(device)
    index = TripletIndex.build(bank)
    total_epochs = epochs if epochs is not None else cfg.max_epochs
    for epoch in range(len(history), total_epochs):
        model.train()
        total = 0.0
        for _ in range(cfg.batches_per_epoch):
            a, p, n = (torch.from_numpy(idx).to(device) for idx in sample_triplets(bank, cfg.batch_size, rng, index))
            idx = torch.cat([a, p, n])
            emb = model(x[idx].float(), lengths[idx])
            fa, fp, fn = emb.split(cfg.batch_size)
            loss = triplet_loss(fa, fp, fn, cfg.triplet_margin)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.detach())
        history.append(total / cfg.batches_per_epoch)
        if log:
            log(epoch, history[-1])
        if checkpoint is not None and ((epoch + 1) % checkpoint_every == 0 or epoch + 1 == total_epochs):
            _save_checkpoint(checkpoint, model, opt, history, rng)
    return model, history


@torch.no_grad()
def embed(model: TypeNetEncoder, x: NDArray[np.float32], lengths: NDArray[np.int64], device: str = "cpu", batch: int = 4096) -> NDArray[np.float32]:
    model.eval()
    out = []
    for i in range(0, len(x), batch):
        xb = torch.from_numpy(np.ascontiguousarray(x[i:i + batch])).to(device).float()
        lb = torch.from_numpy(lengths[i:i + batch]).to(device)
        out.append(model(xb, lb).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.lstm2.hidden_size), dtype=np.float32)
