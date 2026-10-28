# Personalized Multi-Modal Integrity Scoring for Live Coding Exams

**Was this code written by the student sitting the exam?** This system watches *how* code arrives in
the editor — typing rhythm, the writing process, code structure and pastes — compares it with each
student’s own baseline, and gives a human reviewer the evidence. It never accuses anyone on its own.

*Python 3.11 · FastAPI · PostgreSQL · PyTorch · TypeScript · Monaco · tree-sitter* — built for VIT’s
BITE308L by Sneha, Abhishek Mitra and Mehul Kumar Srivastava.

---

## Highlights

- **A complete exam platform** — a self-hosted web exam with a locked-down code editor, live capture
  of every key press, edit and paste, Python tests in the browser, and a reviewer dashboard.
- **A personal baseline from three short tasks** — no long history needed; a held-out *baseline
  check* tests the baseline before it is trusted.
- **Four signals, one score** — keystroke rhythm, writing process, code structure (AST) and
  clipboard behaviour, fused into an integrity score S ∈ [0, 1] with a model that can never treat
  more anomaly as more genuine.
- **A reproduced deep keystroke model** — our TypeNet-style encoder matches all **10 of 10**
  published results within pre-registered bands on 168,593 people (e.g. **1.57%** equal error rate
  vs 1.7% published), 15–20× better than classic statistical baselines.
- **Tamper-evident by design** — an encrypted, append-only, hash-chained event log; the server
  re-checks every edit against the key presses instead of trusting the browser.
- **Human in the loop** — evidence chart, keystroke-by-keystroke replay, tamper check, decisions
  with required notes, named reviewer accounts and a full access log.
- **Privacy built in** — records only the editor, pseudonyms, encryption at rest, one-click
  withdrawal, a retention job, and a hard lock on real data collection until ethics approval.
- **Research-grade evaluation, ready to run** — a two-sitting study protocol with balanced role-play
  attacks, scripted auto-typers, and a nested cross-validation harness with bootstrap confidence
  intervals.
- **Tested** — about 430 Python tests and 160 browser tests across Chromium, Firefox and WebKit;
  every design decision logged in [docs/DECISIONS.md](docs/DECISIONS.md).

## How it works

```
 Practice tasks ×3 ─► baseline check ─► exam                      Reviewer dashboard
        │                  │              │                               ▲
        ▼                  ▼              ▼                               │
  ┌─────────────────────────────────────────────┐    ┌──────────────────────────────────────┐
  │ Browser: Monaco editor + capture             │    │ Server: FastAPI                       │
  │ keys · edits · pastes · focus · snapshots ───┼───►│ validate · order · encrypt · hash-chain│
  └─────────────────────────────────────────────┘ WS │ features → evidence → score S ─────────┼─► report
                                                     └──────────────────────────────────────┘
```

| Signal | What it measures | How |
|---|---|---|
| Keystroke rhythm | Exam typing vs the student’s own practice typing | TypeNet-style LSTM encoder, distance to a personal prototype |
| Writing process | Bursts, pauses, corrections, linearity, how much typed text survives (14 features) | Computed from the event stream |
| Code structure | Structure that appears without typing; style drift | tree-sitter AST, Jensen–Shannon divergence |
| Clipboard & focus | Pastes from outside the editor, leaving the window | Paste fingerprints, focus events |

Plus **server-side reconciliation**: text that appears without matching key presses or a recorded
paste is flagged, whatever the browser claims.

## Results so far

| Enrollment samples (G) | 1 | 2 | 5 | 7 | 10 |
|---|---|---|---|---|---|
| Our EER (70-key windows) | 4.11% | 2.65% | 1.57% | 1.33% | 1.17% |
| TypeNet, published | 4.5% | 2.8% | 1.7% | 1.4% | 1.2% |

Aalto “136M Keystrokes” data, 67,000 training / 1,000 validation / 1,000 test subjects; protocol and
acceptance bands fixed before training. Details: [docs/phase-reports/P2-results.md](docs/phase-reports/P2-results.md).

The full system runs end to end. Detection rates on real students will come from the planned study
(30–50 consenting students, two sittings), which awaits ethics approval — see
[docs/SPEC.md §12](docs/SPEC.md).

## What it is — and isn’t

- Keystroke timing shows that a person typed and whether it looks like *this* person; it does not
  prove who wrote the code. That is why four signals are combined and a person always decides.
- The browser belongs to the student and can be forged; the hash chain shows tampering after data
  reaches the server, and reconciliation raises the cost of forging.
- Few-shot keystroke enrollment is prior work (TypeNet); our contribution is applying it to code,
  fusing it with process, structure and clipboard signals, calibration and an attack evaluation.
- A flag means “a person should look”. Accessibility needs, injury, fatigue or a new keyboard can
  all change typing.
- The optional webcam recording is a demo feature for test accounts; it is not analysed, and its
  head/eye-movement panel is a video demonstration with example output.

## Quick start (Windows)

You need Python 3.11, Node 22+ and Docker Desktop.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -e "backend[dev]" -e ml -e eval
.venv\Scripts\python scripts\make_secrets.py          # keys and tokens in ~\.integrity-exam\secrets (outside the repo)
cd frontend; npm install; npx playwright install chromium firefox webkit; cd ..
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`dev.ps1` starts the database, runs the migrations, starts the API on :8000 and the web app on
:5173. Then open:

| Page | URL |
|---|---|
| Student: consent → practice → baseline check → exam | http://127.0.0.1:5173/ |
| Study mode: six tasks with role-play conditions | http://127.0.0.1:5173/?study=1#/ |
| Reviewer dashboard (token in `~\.integrity-exam\secrets\reviewer_token.txt`) | http://127.0.0.1:5173/#/dashboard |
| Real-keyboard timing check | http://127.0.0.1:5173/#/keycheck |

The keystroke model is not in the repository (it is trained on the Aalto dataset, licensed for
non-commercial research). Without it the app runs and the report says the typing check is
unavailable; to train it, see [docs/p2_protocol.md](docs/p2_protocol.md). PyTorch with CUDA:
`pip install torch --index-url https://download.pytorch.org/whl/cu128`.

<details><summary>Manual start (what the script does)</summary>

```powershell
docker compose up -d db
$env:INTEGRITY_DATA_ROOT = "C:\integrity-data"      # must be outside the repo and any cloud-synced folder
.venv\Scripts\python -m alembic -c backend\alembic.ini upgrade head
.venv\Scripts\python -m integrity_backend.app       # terminal 1: API on :8000
cd frontend; npm run dev                            # terminal 2: web app on :5173
```
</details>

<details><summary>Admin and research tools</summary>

| Task | Command |
|---|---|
| Named reviewer account (token shown once) | `python scripts/staff_accounts.py add <handle> --role reviewer` |
| Retention job (dry run; `--apply` to delete) | `python scripts/purge_retention.py` |
| Encrypted backup of the keys | `python scripts/backup_secrets.py backup <file on a USB drive>` |
| Detection demo with scripted typists | `node eval/tools/detection_demo/detection_demo.cjs` |
| Evaluation pipeline on synthetic data (tests the code, not a result) | `cd eval; python -m integrity_eval.fusion_dryrun --out <...synthetic...md>` |
| Study data export and evaluation (after ethics approval) | `python -m integrity_eval.d2_export` / `d2_eval` |
</details>

## Tests

```powershell
.venv\Scripts\python -m pytest          # Python tests (the database tests need `docker compose up -d db`)
cd frontend; npx playwright test        # browser tests; start their own backend and web app
```

## Repository layout

| Path | Contents |
|---|---|
| [frontend/](frontend/) | Exam app, capture, study mode, reviewer dashboard (TypeScript, Vite, Playwright) |
| [backend/](backend/) | FastAPI + WebSocket ingest, hash chain, storage, replay, reports, review, privacy and study APIs |
| [ml/](ml/) | Keystroke, process, AST and clipboard features; the encoder; fusion; smoothing |
| [eval/](eval/) | TypeNet reproduction, evaluation harness, synthetic sessions, attack runner, detection demo |
| [config/](config/) | Every setting, as YAML |
| [shared/schema/](shared/schema/) | The event wire format (JSON Schema) |
| [docs/](docs/) | Specification, decision log, phase reports, demo and review guides, project report |

## Documentation

- [docs/SPEC.md](docs/SPEC.md) — the full specification
- [docs/DECISIONS.md](docs/DECISIONS.md) — every design decision and why
- [docs/reports/Project_Report_Review2.pdf](docs/reports/Project_Report_Review2.pdf) — project report
- [docs/DEMO.md](docs/DEMO.md) — a 15-minute demo walkthrough
- [docs/phase-reports/](docs/phase-reports/) — what each phase delivered

## Team

Sneha (24BIT0228) · Abhishek Mitra (24BIT0477) · Mehul Kumar Srivastava (24BIT0251) —
Vellore Institute of Technology, BITE308L.

## Licence

No licence is granted: **all rights reserved**. You may view the code on GitHub, but copying,
modifying or redistributing it needs the authors’ permission.

Data rules: participant data is never stored in this repository or in a cloud-synced folder;
synthetic data is labelled as such and never reported as a result.
