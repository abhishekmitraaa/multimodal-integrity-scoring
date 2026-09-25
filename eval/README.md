# eval

Adversarial evaluation harness and reports (Phase 5). The rules it enforces are in SPEC section 12.

## Planned contents

| Item | Purpose |
|---|---|
| `splits` | User-disjoint nested CV. Split files are committed as hashes of pseudonyms. |
| `attacks` | A2 and A3a/b scripted auto-typers driving real browser input; the collection protocol for A1, A4–A8 |
| `metrics` | Detection rate at 5% false-flag rate, EER against G, time-to-detection with censoring, calibration |
| `bootstrap` | Participant-level cluster bootstrap, 95% CIs |
| `ledger` | Test-access ledger (`eval/ledger/test_access.jsonl`, git-ignored). Every test-set computation is logged. |
| `reports` | Per-attack and per-user tables, ablations. Refuses to mix synthetic and real data. |

Results are reported for every attack, including the ones the system fails on.

## Tests

```bash
python -m pytest eval/tests
```
