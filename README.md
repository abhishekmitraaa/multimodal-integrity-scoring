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
- Few-shot enrollment already exists in keystroke biometrics (TypeNet reports about 4.5% EER at 1
  enrollment sequence and 1.2% at 10, on English free text; the figures are to be checked against
  the paper). Our contribution is code-domain adaptation, fusion, the calibration protocol and an
  adversarial evaluation. We do not claim more.
- Population AI-code detectors fail across domains and under humanising (a source is required by
  Phase 6). AST drift is a weak signal used only in fusion.
- A low score means "a human should look". It is not evidence of misconduct. Accessibility needs,
  injury, fatigue, mood and keyboard or device changes all cause false flags.
- The browser client is untrusted. The hash-chained log is tamper-evident on the server. It cannot
  prove what an altered client sent.

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
| P1 | Capture app, server log, replay | done, awaiting approval ([report](docs/phase-reports/P1.md)) |
| P2 | Keystroke features and baseline model on public data | not started; Aalto licence pending |
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
.venv/Scripts/python scripts/make_secrets.py        # local keys and tokens in secrets/ (git-ignored)
docker compose up -d db                              # PostgreSQL 16 on 127.0.0.1:5432
cd frontend && npm install && npx playwright install chromium firefox webkit
```

## Running the app locally (development data only)

```powershell
# terminal 1 (PowerShell): data root, database schema, then the API on :8000
$env:INTEGRITY_DATA_ROOT = "C:\integrity-data"      # must be outside the repo and cloud sync
.venv\Scripts\python -m alembic -c backend\alembic.ini upgrade head
.venv\Scripts\python -m integrity_backend.app
# terminal 2: the web app on :5173 ($env:COI = "1" first to serve it cross-origin isolated)
cd frontend; npm run dev
```

Open http://127.0.0.1:5173. It creates `DEV-` participants. Real participants are refused until
`real_collection_enabled` is set after ethics approval. The reviewer replay page is at `#/replay`,
using the token in `secrets/reviewer_token.txt`.

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
