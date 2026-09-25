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
| D-006 | Application-level AES-256-GCM for event payloads, snapshots and notes, plus an encrypted disk. Ed25519 signs chain checkpoints. Keys live in `secrets/`. | proposed | SPEC 10.6 |
| D-007 | Session score = minimum of EWMA-smoothed (logit) $S(t)$. Flag if it ever crosses $\tau$. | proposed | SPEC 8.3 |
| D-008 | User-disjoint nested CV (5 outer folds, inner validation) instead of one 60/20/20 split. Test-access ledger. | open (Q5) | SPEC 12.3 |
| D-009 | Frontend unit tests use the Playwright Test runner rather than adding Vitest, to stay within the stated stack. | proposed | – |
| D-010 | SQLAlchemy 2 + Alembic + asyncpg for database access. | proposed | SPEC 5 |
| D-011 | Practice modules include a short transcription block, giving a per-student transcription-mode profile aimed at A4. | open (Q3) | SPEC 12.2 |
| D-012 | Only participants aged 18 or over, to avoid the DPDP children's-data rules on behavioural monitoring. | proposed | SPEC 10.1 |
| D-013 | Fusion inputs are 7 modality-level distances plus 2 availability indicators, not raw features, to limit overfitting with 30–50 users. | proposed | SPEC 7.4 |
| D-014 | Paste provenance (internal / problem statement / external) by normalised SHA-256 match against in-session copies. | proposed | SPEC 6.4 |

## Open questions for the lead (Phase 0)

1. **Q1: Location and toolchain.** The repo is in a OneDrive-synced folder, and Python 3.11 is not
   installed (3.10.1 is). Move the repo out of OneDrive? How should we get 3.11?
2. **Q2: Run/Test execution.** In-browser Pyodide or a server-side sandbox?
3. **Q3: Study protocol.** Two sittings? The condition set? Frozen LLM outputs? The transcription
   block (D-011)?
4. **Q4: Data governance.** Retention period, identity-map custodian, Data Fiduciary contact, who the
   reviewers are.
5. **Q5: Evaluation.** Nested CV (D-008)? The P2 "within reason" definition (SPEC 12.7)?
