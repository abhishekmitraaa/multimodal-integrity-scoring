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


def sample_triplets(bank: SequenceBank, batch: int, rng: np.random.Generator) -> tuple[NDArray[np.int64], ...]:
    """Random triplets (TypeNet §4.4): anchor and positive are two different sequences of one
    subject; the negative is a random sequence of another subject."""
    by_subject = [np.flatnonzero(bank.subject == s) for s in range(int(bank.subject.max()) + 1)]
    eligible = [s for s, idx in enumerate(by_subject) if idx.size >= 2]
    if not eligible:
        raise ValueError("no subject has two sequences")
    subj = rng.choice(eligible, size=batch)
    anchors, positives, negatives = (np.empty(batch, dtype=np.int64) for _ in range(3))
    for i, s in enumerate(subj):
        anchors[i], positives[i] = rng.choice(by_subject[s], size=2, replace=False)
        negatives[i] = rng.choice(np.flatnonzero(bank.subject != s))
    return anchors, positives, negatives


def seed_everything(seed: int) -> None:
    import random

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def train(
    bank: SequenceBank,
    cfg: EncoderConfig,
    seed: int,
    device: str = "cpu",
    epochs: int | None = None,
    log: Callable[[int, float], None] | None = None,
) -> tuple[TypeNetEncoder, list[float]]:
    """Fixed number of epochs of random-triplet batches; returns the final model (no selection)."""
    seed_everything(seed)
    rng = np.random.default_rng(seed)
    model = TypeNetEncoder(cfg).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate, betas=cfg.adam_betas, eps=cfg.adam_eps)
    x = torch.from_numpy(bank.x).to(device)
    lengths = torch.from_numpy(bank.lengths).to(device)
    history: list[float] = []
    for epoch in range(epochs if epochs is not None else cfg.max_epochs):
        model.train()
        total = 0.0
        for _ in range(cfg.batches_per_epoch):
            a, p, n = (torch.from_numpy(idx).to(device) for idx in sample_triplets(bank, cfg.batch_size, rng))
            idx = torch.cat([a, p, n])
            emb = model(x[idx], lengths[idx])
            fa, fp, fn = emb.split(cfg.batch_size)
            loss = triplet_loss(fa, fp, fn, cfg.triplet_margin)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.detach())
        history.append(total / cfg.batches_per_epoch)
        if log:
            log(epoch, history[-1])
    return model, history


@torch.no_grad()
def embed(model: TypeNetEncoder, x: NDArray[np.float32], lengths: NDArray[np.int64], device: str = "cpu", batch: int = 4096) -> NDArray[np.float32]:
    model.eval()
    out = []
    for i in range(0, len(x), batch):
        xb = torch.from_numpy(x[i:i + batch]).to(device)
        lb = torch.from_numpy(lengths[i:i + batch]).to(device)
        out.append(model(xb, lb).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.lstm2.hidden_size), dtype=np.float32)
