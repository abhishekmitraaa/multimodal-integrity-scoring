# Personalized Multi-Modal Integrity Scoring for Live Coding Exams

University prototype for VIT BITE308L, built by a 3-person team.

This is a web-based live coding exam environment. It records keystroke timing, clipboard events and
code snapshots in a Monaco editor. It builds a per-student baseline from 2–3 short practice modules,
and during an exam it produces a continuous integrity confidence score $S \in [0,1]$ (high =
genuine). Sessions with a low score go to a human reviewer. **Nothing is ever acted on
automatically.**

The full design is in [docs/SPEC.md](docs/SPEC.md) and decisions are logged in
[docs/DECISIONS.md](docs/DECISIONS.md).

## What this system can and cannot show

- Keystroke timing proves a human was typing, not that the human was the author. Timing-only
  detection is weak against transcribing LLM output from a second device (copy-type) and against
  timing-forgery auto-typers.
- Therefore the system fuses four signals: (1) keystroke identity distance, (2) process features from
  the edit stream, (3) AST drift normalised per problem, (4) clipboard and paste metrics.
- Few-shot enrollment already exists in keystroke biometrics. TypeNet reports 4.5% EER at 1
  enrollment sequence and 1.2% at 10, for 70-keystroke sequences of short memorised English
  sentences, 1,000 test subjects and per-subject thresholds. The figures are checked against the
  arXiv text; see [docs/p2_protocol.md](docs/p2_protocol.md). Our contribution is code-domain
  adaptation, fusion, the calibration protocol and an adversarial evaluation. We do not claim
  more.
- Population AI-code detectors fail across domains and under humanising (a source is required by
  Phase 6). AST drift is a weak signal used only in fusion.
- A low score means "a human should look". It is not evidence of misconduct. Accessibility needs,
  injury, fatigue, mood and keyboard or device changes all cause false flags.
- The score S is defined so that high = genuine. The fusion inputs are anomaly distances, so their
  learned weights are constrained to be non-positive.
- Client-side telemetry can be forged by whoever controls the browser, and `isTrusted` is not a
  defence. The hash chain shows tampering after data reaches the server, not forging at the source.
  Server-side reconciliation of edits against keystrokes (Phase 3) raises the cost of naive
  forging only.

## Repository layout

| Path | Contents |
|---|---|
| [frontend/](frontend/) | Monaco exam app, practice modules, consent, reviewer dashboard (TypeScript, Vite, Playwright) |
| [backend/](backend/) | FastAPI + WebSocket ingest, hash chain, storage, replay, scoring, review and privacy APIs |
| [ml/](ml/) | Features (keystroke, process, AST, clipboard), keystroke encoder, digraph baseline, fusion, calibration |
| [eval/](eval/) | Adversarial harness A1–A8, splits, metrics, bootstrap CIs, reports |
| [shared/schema/](shared/schema/) | Event wire contract (JSON Schema) and synthetic example batches |
| [config/](config/) | All tunables as YAML |
| [docs/](docs/) | Spec, decisions, phase reports |
| [data/](data/) | Local data root. Only labelled synthetic fixtures are committed. |

## Phase status

| Phase | Scope | Status |
|---|---|---|
| P0 | Repo skeleton and spec | approved with changes |
| P1 | Capture app, server log, replay | approved ([report](docs/phase-reports/P1.md)) |
| P2 | Keystroke features and baseline model on public data | protocol written, awaiting review ([p2_protocol.md](docs/p2_protocol.md)); real-keyboard check ready ([keycheck.md](docs/keycheck.md)); Aalto licence requested; no training yet |
| P3 | Enrollment, process/AST/clipboard features, fusion, thresholds | not started |
| P4 | Reviewer dashboard | not started |
| P5 | Data collection tooling, evaluation harness, attack report | not started; ethics checklist first |
| P6 | Paper and patent-support documents | not started |

## Setup (Windows; use `.venv/bin/python` on Linux/macOS)

The repository lives at `C:\dev\integrity-exam`, outside OneDrive. You need Python 3.11 (pinned),
Node 22+ and Docker Desktop.

```bash
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt -e "backend[dev]" -e ml -e eval
.venv/Scripts/python scripts/make_secrets.py        # keys and tokens in ~/.integrity-exam/secrets (outside the repo)
docker compose up -d db                              # PostgreSQL 16 on 127.0.0.1:5432
cd frontend && npm install && npx playwright install chromium firefox webkit
```

## Running the app locally (development data only)

```powershell
# terminal 1 (PowerShell): data root, database schema, then the API on :8000
$env:INTEGRITY_DATA_ROOT = "C:\integrity-data"      # must be outside the repo and cloud sync
.venv\Scripts\python -m alembic -c backend\alembic.ini upgrade head
.venv\Scripts\python -m integrity_backend.app
# terminal 2: the web app on :5173, cross-origin isolated by default ($env:COI = "0" only to measure without)
cd frontend; npm run dev
```

Open http://127.0.0.1:5173. It creates `DEV-` participants. Real participants are refused until
`real_collection_enabled` is set after ethics approval. The reviewer replay page is at `#/replay`,
using the token in `~/.integrity-exam/secrets/reviewer_token.txt`. The real-keyboard check is at `#/keycheck`. It needs
only the web app, not the backend, and its files are development data ([docs/keycheck.md](docs/keycheck.md)).

## Running the tests

```bash
.venv/Scripts/python -m pytest          # all Python tests; the database tests need `docker compose up -d db`
cd frontend && npx playwright test      # starts its own backend on a throwaway database, plus Vite
```

## Data rules

- Synthetic data is used only for pipeline tests. It is labelled "synthetic" in code, filenames and
  reports, and is never reported as a result.
- No real participant data is collected until the ethics and consent checklist (Phase 5) is
  approved.
- Participant data must never be stored inside this repository or any cloud-synced folder. See
  `config/privacy.yaml`.
