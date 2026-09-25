"""Config files parse and encode the fixed requirements from the brief (docs/SPEC.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
EXPECTED = {"global", "capture", "editor_policy", "features", "models", "scoring", "eval", "privacy"}


def cfg(name: str) -> dict[str, Any]:
    data = yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_all_expected_configs_present() -> None:
    assert {p.stem for p in CONFIG_DIR.glob("*.yaml")} == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_config_parses(name: str) -> None:
    cfg(name)


def test_seed_is_int() -> None:
    assert isinstance(cfg("global")["seed"], int)


def test_batching_matches_brief() -> None:
    batch = cfg("capture")["batch"]
    assert batch["max_keydowns"] == 15
    assert batch["max_age_ms"] == 5000


def test_editor_policy_blocks_untracked_insertion() -> None:
    opts = cfg("editor_policy")["monaco_options"]
    assert opts["quickSuggestions"] is False
    assert opts["inlineSuggest"]["enabled"] is False
    assert opts["snippetSuggestions"] == "none"
    assert opts["tabCompletion"] == "off"
    assert opts["autoClosingBrackets"] == "never"
    assert opts["autoClosingQuotes"] == "never"
    assert opts["autoSurround"] == "never"
    assert opts["formatOnPaste"] is False
    assert opts["formatOnType"] is False
    assert opts["dragAndDrop"] is False
    assert opts["dropIntoEditor"]["enabled"] is False


def test_encoder_config_matches_verified_typenet_values() -> None:
    """Values checked against TypeNet arXiv:2101.05570v3 (docs/p2_protocol.md)."""
    enc = cfg("models")["keystroke_encoder"]
    assert enc["learning_rate"] == 0.05
    assert enc["triplet_margin"] == 1.5
    assert (enc["dropout"], enc["recurrent_dropout"]) == (0.5, 0.2)
    assert (enc["max_epochs"], enc["batches_per_epoch"], enc["batch_size"]) == (200, 150, 512)
    rep = cfg("models")["reproduction"]
    assert (rep["train_subjects"], rep["test_subjects_k"]) == (68000, 1000)
    assert rep["g_values"] == [1, 2, 5, 7, 10]
    assert rep["genuine_query_indices"] == [10, 11, 12, 13, 14]


def test_keystroke_window_matches_brief() -> None:
    ks = cfg("features")["keystroke"]
    assert ks["window_keystrokes"] == 70
    assert cfg("features")["process"]["pause_thresholds_ms"] == [200, 2000]


def test_model_shape_matches_brief() -> None:
    enc = cfg("models")["keystroke_encoder"]
    assert (enc["lstm_layers"], enc["hidden_units"], enc["embedding_dim"]) == (2, 128, 128)
    assert enc["loss"] == "triplet"
    assert cfg("models")["enrollment"]["g_values"] == [1, 3, 5, 10]
    fusion = cfg("models")["fusion"]
    assert fusion["model"] == "logistic_regression"
    assert fusion["mlp_enabled"] is False


def test_scoring_states_and_false_flag_rate() -> None:
    scoring = cfg("scoring")
    assert scoring["states"] == ["auto_accept", "review", "insufficient_data"]
    assert scoring["target_false_flag_rate"] == 0.05


def test_privacy_minimums() -> None:
    privacy = cfg("privacy")
    assert privacy["min_participant_age"] >= 18
    assert privacy["pseudonym"]["prefix_synthetic"] == "SYN-"
    assert "OneDrive" in privacy["forbidden_data_root_markers"]
    # Open decisions stay explicit until the lead decides (SPEC section 15).
    assert "retention_days_after_project_end" in privacy
    assert privacy["real_collection_enabled"] is False  # flips only after ethics approval
    assert "data_root" in privacy
