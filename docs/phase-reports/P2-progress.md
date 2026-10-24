# Phase 2 progress report: keystroke features and baseline model

Date: 2026-10-24. Status: **in progress. Everything that does not need the Aalto data is built
and tested. The TypeNet reproduction waits for the dataset licence.** Branch
`p2/protocol-and-keycheck`; `main` is unchanged since P1.

**No result in this report comes from real keystroke data.** Every number below is from labelled
SYNTHETIC data (D3). It shows that the code works and responds as intended, and nothing about
keystroke identity. Test results show that capture, labelling and computation are correct, not
that anything detects anything.

## Done since P1 approval

| Item | Where | Status |
|---|---|---|
| TypeNet protocol, checked against arXiv:2101.05570v3 and the authors' README | [p2_protocol.md](../p2_protocol.md) v0.3 | done; decisions taken (D-031); deviation 6 amended |
| P1 review decisions: isolation by default, Chromium + Firefox, threat model, find/replace | SPEC v0.3, D-021…D-027 | done |
| Real-keyboard check page and report | [keycheck.md](../keycheck.md), `#/keycheck` | ready; **not yet run by the team** |
| Secrets moved out of the repo, guarded, encrypted backup script | SPEC 10.6, D-028 | done; **first offline backup not yet made** |
| Keystroke pairing and latencies (SPEC 6.1) | `ml/src/integrity_ml/keystroke.py` | done |
| EER: the authors' sweep (matches their code to 1e-9) and exact global EER | `ml/src/integrity_ml/eer.py` | done |
| Non-deep baselines: SPEC 7.2 digraph and sequence-statistics scaled Manhattan | `ml/src/integrity_ml/baselines.py` | done |
| TypeNet input matrices and legacy keycode table | `ml/src/integrity_ml/sequences.py` | done |
| TypeNet-style encoder (PyTorch, GPU), triplet training, embedding | `ml/src/integrity_ml/encoder.py` | done; parameter count matches the paper |
| TypeNet authentication protocol runner, Eq. 5 and prototype scorers | `eval/src/integrity_eval/authentication.py` | done |
| Synthetic pipeline check with run manifest | `python -m integrity_eval.p2_synthetic [--encoder]` | done |
| Aalto loader, D1 reproduction run, gap analysis | — | **blocked on the licence** |

## Tests

| Suite | Result |
|---|---|
| Python, all packages (3.11.9; torch 2.11.0+cu128) | **297 passed** (P1: 214) |
| Playwright, Chromium + Firefox + WebKit, isolated origin | **134 passed, 1 skipped** (the known WebKit clipboard skip), rerun on 2026-10-24 after the secrets move |

## Synthetic pipeline check (SYNTHETIC — not a result)

TypeNet protocol, 60 test subjects per row (40 others used only for fitting), mean per-subject
EER at G = 5:

| Separation | Digraph (SPEC 7.2) | Sequence statistics | Encoder, Eq. 5 (lr 0.05, 20 epochs, 40 training subjects) |
|---|---|---|---|
| 0 (identical subjects) | 50.7% | 49.5% | 48.5% |
| 0.5 | 16.0% | 22.1% | 50.0% |
| 1.0 | 0.2% | 14.8% | 35.2% |

How to read it:

- Identical subjects give about 50%, so nothing leaks between the gallery and the queries.
- Error falls as separation grows, and more gallery sentences help the digraph baseline.
- The per-subject EER is below the global-threshold EER. That is TypeNet's optimism again (p2_protocol §0.1).
- The digraph baseline does best because the generator stores identity exactly in per-digraph timing.

**Encoder diagnostic** (200 training and 100 test subjects, 10 epochs, G = 5): with learning rate
0.05 the EER is 34.6% at separation 1.0 and 22.5% at 2.0. With 0.005 it is **5.6% and 0.8%**. So
the encoder works, but the paper's printed rate barely trains in our setup. The protocol now
chooses the rate on held-out *training* subjects before any test access (deviation 6, amended;
D-032).

## What works

- Every P2 component that does not need D1 runs end to end, from keystrokes to EER, on the
  GPU, with the exact TypeNet indices. The TypeNet-specific details are verified: parameter
  count, evaluation indices and the authors' EER algorithm.
- The reproduction can start the day the data arrives. The remaining work is a loader for the
  Aalto file format, which is still [VERIFY].
- Secrets are out of the repo, and the backend refuses to start with them in the repo or a
  synced folder.

## What is weak

1. **No real keystroke data yet.** Nothing here measures identity.
2. **The learning rate is the first real departure from the paper.** If D1 validation also
   prefers 0.005, our reproduction differs from TypeNet on a printed hyperparameter. The
   acceptance band still applies.
3. **The synthetic generator is simple.** It stores identity exactly where the digraph baseline
   looks, so the baseline-versus-encoder ranking on synthetic data means nothing.
4. **Aalto format, subject count and "one sitting" are unverified** (p2_protocol §0.1, §1).
5. **The real-keyboard check has not been run** with real keyboards.
6. **The first secrets backup doesn't exist yet.** Until the lead runs it, losing the laptop
   loses the dev data.
7. ruff and mypy are still not installed, so they were not run.

## What the lead should do or decide next

1. **The Aalto licence and download.** This is the critical path for P2. Put the data under
   `INTEGRITY_DATA_ROOT\external\aalto_desktop\`.
2. **Make the first secrets backup** onto an offline drive:
   `.venv\Scripts\python scripts\backup_secrets.py backup <drive>:\integrity-secrets.bak`, then
   `verify`. Keep the passphrase in a password manager.
3. **Run the real-keyboard check** with Sneha and Mehul ([keycheck.md](../keycheck.md)), about 5
   minutes per run.
4. **Optional:** sign BiDA Lab's TypeNet Benchmark licence (D-031).
5. **Merge the branch into `main`** when you have reviewed it.
