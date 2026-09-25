# Decisions log

Each entry shows its status: **accepted** (fixed by the brief or approved by the lead), **proposed**
(an engineering default awaiting approval) or **open** (the lead must decide). Newest entries go at
the bottom. See [SPEC.md](SPEC.md) for context.

| ID | Decision | Status | Where |
|---|---|---|---|
| D-001 | Stack as in the brief: Python 3.11, FastAPI + WebSocket, PostgreSQL, Monaco + TypeScript + Vite, py-tree-sitter, PyTorch, scikit-learn, Docker Compose, pytest, Playwright. No browser extension in v1. | accepted | brief |
| D-002 | The wire contract is one JSON Schema file in `shared/schema/`, used by both the TS client and the Python server. | proposed | SPEC 4 |
| D-003 | Integer-only wire format: timestamps in µs, DPR ×100. The server rejects float tokens before schema validation. | proposed | SPEC 4.1 |
| D-004 | `KeyboardEvent.key` is never stored. `cat` is derived on the client and `code` is kept for digraphs. | proposed | SPEC 4.5 |
| D-005 | Monaco auto-indent stays on and is attributed as `typed`. Line commands (move/copy line) stay on and are attributed as `command`. | proposed | SPEC 4.7–4.8 |
| D-006 | Application-level AES-256-GCM on event payloads (P1), with associated data `session_id‖server_seq`. Keys live in `secrets/`. Ed25519 checkpoint signing is deferred (D-017). | accepted (Q1) | SPEC 10.6 |
| D-007 | Session score = minimum of EWMA-smoothed (logit) $S(t)$. Flag if it ever crosses $\tau$. The time-to-detection cost is stated in SPEC 8.3. | proposed | SPEC 8.3 |
| D-008 | User-disjoint nested CV (5 outer folds, inner validation). Test-access ledger. | accepted (Q5) | SPEC 12.3 |
| D-009 | Frontend unit tests use the Playwright Test runner rather than adding Vitest. | proposed | – |
| D-010 | SQLAlchemy 2 + Alembic + asyncpg for database access. | proposed | SPEC 5 |
| D-011 | Practice modules include a short transcription block (per-student transcription-mode profile aimed at A4). The awareness limitation is recorded in SPEC 1.4. | accepted (Q3) | SPEC 12.2 |
| D-012 | Only participants aged 18 or over. | proposed | SPEC 10.1 |
| D-013 | Fusion inputs are 7 modality-level distances plus 2 availability indicators. | proposed | SPEC 7.4 |
| D-014 | Paste provenance (internal / problem statement / external) by normalised SHA-256 match. | proposed | SPEC 6.4 |
| D-015 | Repository at `C:\dev\integrity-exam`, outside OneDrive. The data root is outside the repo and encrypted. Python pinned to 3.11 (`.python-version`, `requires-python >=3.11,<3.12`). | accepted (Q1) | SPEC 10.6 |
| D-016 | Run/Test executes in Pyodide in a Web Worker, Python only. Results are client-reported and forgeable. | accepted (Q2) | SPEC 1.4, 4.5 |
| D-017 | P1 implements a plain hash chain only. Signed checkpoints and signed receipts are deferred. Close returns an unsigned head hash. | accepted (pre-P1) | SPEC 4.4 |
| D-018 | Fusion distance weights are constrained $w \le 0$ during fitting (L-BFGS-B bounds), not only checked afterwards. | accepted (pre-P1) | SPEC 7.4 |
| D-019 | Recruit 50+ participants. A live-LLM A5 subset of 8–10 is labelled `A5_live`. Ethics approval is required before any real collection. | accepted (Q3) | SPEC 12.2 |
| D-020 | Cluster bootstrap over users. The exact TypeNet protocol is documented item by item before P2 training. | accepted (Q5) | SPEC 12.5, 12.7 |

## Open

- **Q4: data governance** (retention N, identity-map custodian, named responsible party, reviewers
  outside the team). Sent to the faculty guide as the governance one-pager
  (https://claude.ai/code/artifact/b8f7ee47-8b1a-4f57-bd0f-11e0c36d660b). It blocks the final
  consent notice and the retention job, not P1.
