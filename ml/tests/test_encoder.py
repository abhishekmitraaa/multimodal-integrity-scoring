"""TypeNet-style encoder (SPEC 7.1). Skipped where PyTorch is not installed. SYNTHETIC inputs only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

torch = pytest.importorskip("torch")

from integrity_ml.encoder import (  # noqa: E402
    EncoderConfig, SequenceBank, TypeNetEncoder, embed, sample_triplets, train, triplet_loss,
)
from integrity_ml.sequences import typenet_matrix  # noqa: E402
from integrity_ml.synthetic_keystrokes import SyntheticConfig, generate  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ENC = yaml.safe_load((REPO / "config" / "models.yaml").read_text(encoding="utf-8"))["keystroke_encoder"]
SYN = yaml.safe_load((REPO / "config" / "eval.yaml").read_text(encoding="utf-8"))["synthetic_keystrokes"]


def test_parameter_count_matches_typenet_plus_pytorch_second_bias() -> None:
    model = TypeNetEncoder(EncoderConfig.from_config(ENC))
    n = sum(p.numel() for p in model.parameters() if p.requires_grad)
    assert n == 200_458 + 2 * 4 * 128   # TypeNet §4.2 count + PyTorch's extra bias vector per LSTM


def test_config_values_come_from_models_yaml() -> None:
    cfg = EncoderConfig.from_config(ENC)
    assert (cfg.learning_rate, cfg.triplet_margin, cfg.dropout, cfg.batch_size) == (0.05, 1.5, 0.5, 512)


def test_keras_style_initialisation() -> None:
    model = TypeNetEncoder()
    for lstm in (model.lstm1, model.lstm2):
        h = lstm.hidden_size
        assert torch.all(lstm.bias_ih_l0[h:2 * h] == 1) and torch.all(lstm.bias_hh_l0 == 0)
        w = lstm.weight_hh_l0.detach()
        # each 128x128 block of an orthogonal 512x128 matrix has orthonormal columns overall
        np.testing.assert_allclose((w.T @ w).numpy(), np.eye(h), atol=1e-4)


def test_embedding_shape_and_padding_invariance() -> None:
    torch.manual_seed(0)
    model = TypeNetEncoder().eval()
    x = torch.randn(1, 10, 5)
    padded = torch.cat([x, torch.zeros(1, 20, 5)], dim=1)
    e1 = model(x, torch.tensor([10]))
    e2 = model(padded, torch.tensor([10]))
    assert e1.shape == (1, 128)
    torch.testing.assert_close(e1, e2)


def test_triplet_loss_values() -> None:
    a = torch.tensor([[0.0, 0.0]])
    p = torch.tensor([[1.0, 0.0]])          # d^2 = 1
    n = torch.tensor([[2.0, 0.0]])          # d^2 = 4
    assert float(triplet_loss(a, p, n, margin=1.5)) == 0.0       # 1 - 4 + 1.5 < 0
    assert float(triplet_loss(a, n, p, margin=1.5)) == pytest.approx(4.5)


def _bank(subjects: int = 8, m: int = 30, separation: float = 2.0) -> SequenceBank:
    data = generate(SyntheticConfig.from_config(SYN, separation=separation, seed=5, subjects=subjects))
    return SequenceBank.build([[typenet_matrix(s, m) for s in subj] for subj in data.subjects])


def test_triplet_sampling_rules() -> None:
    bank = _bank()
    a, p, n = sample_triplets(bank, 500, np.random.default_rng(0))
    assert np.all(a != p)
    assert np.all(bank.subject[a] == bank.subject[p])
    assert np.all(bank.subject[a] != bank.subject[n])


def test_short_training_run_is_finite_reproducible_and_learns() -> None:
    bank = _bank()
    cfg = EncoderConfig.from_config(ENC, batch_size=32, batches_per_epoch=10)
    model, history = train(bank, cfg, seed=1, epochs=6)
    _, again = train(bank, cfg, seed=1, epochs=6)
    assert all(np.isfinite(history))
    assert history == pytest.approx(again, rel=1e-4)          # same seed, same run (CPU)
    assert np.mean(history[-2:]) < np.mean(history[:2])       # loss goes down
    emb = embed(model, bank.x, bank.lengths)
    assert emb.shape == (len(bank.x), 128) and np.all(np.isfinite(emb))
