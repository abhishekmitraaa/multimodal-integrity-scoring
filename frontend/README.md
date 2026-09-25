# frontend

Monaco exam app (TypeScript, Vite): consent (DRAFT), device questionnaire, practice/exam sessions,
Run/Test in Pyodide, submission receipt, and a minimal reviewer replay page (`#/replay`).

| Path | Contents | SPEC |
|---|---|---|
| `src/capture/keys.ts` | Key categories; `KeyboardEvent.key` is used here and dropped | 4.6 |
| `src/capture/log.ts` | Event log: seq at creation, async hash slots, ack/resend bookkeeping | 4.2 |
| `src/capture/transport.ts` | WebSocket hello/welcome, batches, ack/nack, reconnect, pagehide beacon | 4.2 |
| `src/capture/capture.ts` | Monaco and DOM listeners, change-cause hints, snapshots | 4.5–4.7, 4.10 |
| `src/capture/device.ts` | Device covariates, timer probe | 4.9 |
| `src/editor.ts` | Monaco with only the needed contributions, policy self-check | 4.8 |
| `src/runner/` | Pyodide in a Web Worker (results client-reported, forgeable) | 1.4 |
| `src/replay.ts` | Client-side replay for the reviewer page | 4.10 |

Pyodide is served from our own origin (`scripts/copy-pyodide.mjs` copies it into `public/pyodide/`),
and so is Monaco. No CDN is used.

## Tests

`npx playwright test` runs the unit tests (`tests/unit`), the end-to-end tests (`tests/e2e`) and the
measurements (`tests/e2e/measure.spec.ts`, writing to `measurements/`) in Chromium, Firefox and
WebKit. It starts the backend on a throwaway `integrity_e2e` database, plus Vite on :5173 (plain)
and :5174 (COOP/COEP). Set `BASE_URL=http://127.0.0.1:5174` to run the suite cross-origin
isolated. All test participants are `synthetic`.
