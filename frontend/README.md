# frontend

Monaco exam app (TypeScript, Vite). It will be scaffolded in P1 with `npm create vite`, so that
real dependency versions are pinned in `package-lock.json` rather than guessed now.

## Planned contents (P1, P4)

- `capture/`: event capture (SPEC 4.5), key categorisation (4.6), change-source hints (4.7),
  batching and resend (4.2), timer probe (4.9).
- `editor/`: Monaco setup from `config/editor_policy.yaml`, with a policy self-check.
- `pages/`: consent, device questionnaire, practice modules, exam, receipt.
- `dashboard/`: reviewer timeline, replay scrubber, decisions and appeals (P4).
- `tests/`: Playwright end-to-end tests, plus unit tests on the Playwright Test runner (D-009).

Monaco is bundled locally, not loaded from a CDN, so no third party sees participants' traffic.
