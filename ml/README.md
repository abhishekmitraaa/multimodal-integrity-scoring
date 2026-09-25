# ml

Feature extraction and models. The backend imports these functions for online scoring, so the
features used online and offline are identical.

## Planned modules

| Module | Responsibility | Phase | SPEC |
|---|---|---|---|
| `features.keystroke` | Keydown/keyup pairing, HL/PL/IL/RL, windows, digraph profile | P2 | 6.1 |
| `features.process` | Pauses, bursts, revision, linearity, locality, speed and timing regularity, run cadence | P3 | 6.2 |
| `features.ast` | tree-sitter histograms, Laplace smoothing, per-problem tilt, JSD, scalar style features, AST jumps | P3 | 6.3 |
| `features.clipboard` | Paste provenance, volumes, focus-loss coupling | P3 | 6.4 |
| `models.typenet` | Siamese/triplet LSTM encoder (pretrain on Aalto, fine-tune on code typing) | P2 | 7.1 |
| `models.digraph` | Non-deep digraph baseline (Manhattan) | P2 | 7.2 |
| `models.fusion` | Logistic regression fusion, weight-sign guard, calibration | P3 | 7.4, 8 |

Every artifact embeds a run manifest (git commit, config hash, seed, dataset IDs, synthetic flag).

## Tests

```bash
python -m pytest ml/tests
```
