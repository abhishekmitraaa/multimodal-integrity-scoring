# Scripted attacks A2, A3a, A3b (SPEC 12.2, D-046)

Real browser keyboard input, driven by Playwright, typing the frozen study material for one exam
task into a session created for a study participant. The session is labelled with the condition
(`study_labels.scripted = true`, onset = session start). Reviewers never see the label.

| Condition | Timing |
|---|---|
| A2 | constant rate (`config/study.yaml → a2`, ±1%) |
| A3a | log-normal jitter around population medians (`a3a`) |
| A3b | resampled from this participant's own practice flights and holds (consented, SPEC 10.3) |

Needs the app running (`scripts\dev.ps1`) and an admin token (`ADMIN_TOKEN`, else the bootstrap
`admin_token.txt`). The participant must be in the study protocol; for A3b they must have finished
practice tasks.

```powershell
node eval\tools\attack_runner\attack_runner.cjs --pseudonym P-XXXXXXXX --problem exam_balanced --condition A3b
```

Tested end to end in `frontend/tests/e2e/attack-runner.spec.ts` (A2, Chromium).
