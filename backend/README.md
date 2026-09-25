# backend

FastAPI server: the source of truth for the event log.

## Planned modules (P1 onward)

| Module | Responsibility | SPEC |
|---|---|---|
| `ingest` | WebSocket batches: float rejection, schema validation, ordering (ack/nack), `server_seq`, `t_server_us` | 4.2 |
| `chain` | Hash chain, Ed25519 checkpoints, `verify_chain`, receipts | 4.4 |
| `replay` | UTF-16-aware document replay, snapshot consistency, change-source attribution | 4.7, 4.10 |
| `storage` | SQLAlchemy models, Alembic migrations, append-only roles, field encryption | 5, 10.6 |
| `scoring` | Online ticks, calling feature functions from `ml/`, $S(t)$, cases | 8 |
| `review` | Dashboard API, decisions, appeals, access log | 10.10, 11 |
| `privacy` | Consent records, erasure endpoint, retention job, data-root guard | 10 |

Dependencies are added in the phase that first uses them.

## Tests

```bash
python -m pytest backend/tests
```
