# P3/P4 first slice: baseline, exam check, evidence report, dashboard

Date: 2026-10-26. Status: **built and tested; for the lead's review.** It was started at the lead's
request (D-036) after P2 approval, because the app stopped after the practice tasks: nothing
built a baseline, checked the exam or showed a result.

**Everything shown in tests and demos comes from scripted (synthetic) or DEV input.** It shows the
system works end to end. It says nothing about how well it detects cheating.

## What now happens, start to finish

1. **Setup:** "Step 1: practice tasks" (three tasks with the code shown, D-035) and "Step 2: exam".
   Submitted tasks get a ✓.
2. **Each practice task** is typed, tested and submitted. Its key presses become baseline windows
   (70 key presses each, non-overlapping).
3. **The exam** is solved without shown code. After submitting, "See your report" opens the
   participant's own report (submitted sessions only).
4. **The report** for each exam:
   - **Typing rhythm vs baseline:** the P2 encoder's distance from the person's practice prototype
     for each 70-key window, compared with the same-person 95% line from the reference data.
   - **Pastes from outside the editor**, and **pasting soon after returning to the window.**
   - **Code that was not typed:** the share of inserted characters from paste or non-typing edits.
   - **Code without matching key presses:** the server's own check (D-026). It catches insertions
     the browser labelled "typed" with no key presses behind them.
   - **Evenness of typing rhythm:** an auto-typer is near 0.
   - **Time away from the window:** context only.

   Overall state: **review** if any rule fires, **not enough data** if the typing check couldn't
   run and nothing fired, otherwise **no review flags**. There is **no single score** (D-036).
5. **The reviewer dashboard** (`#/dashboard`) lists every participant with progress, opens the same
   report, and links each exam to its keystroke-by-keystroke replay. Every read is access-logged.

## How it's built

| Part | Where |
|---|---|
| Session signals (shared offline and online) | `ml/src/integrity_ml/session_features.py` |
| Keystroke model at report time, with reference ranges | `ml/src/integrity_ml/serving.py`; ranges from `eval/src/integrity_eval/serving_calibration.py` |
| Report builder and its rules | `backend/src/integrity_backend/report.py`, `config/scoring.yaml → report` |
| API | `GET /api/participants`, `GET /api/participants/{p}/report` (staff), `GET /api/me/report` (participant) |
| Pages | `#/dashboard`, `#/my-report`, a two-step setup, links on the receipt page |
| Model files | `C:\integrity-data\models\` (outside the repo, D1 licence) |

**Reference ranges.** These come from the 1,000 D1 *validation* subjects, held out from training,
so the test set was not reused. At G = 3 / 5 / 10 enrollment windows, the same-person 95%
distance is 2.21 / 2.09 / 1.96 and the other-person 5% distance is 2.20 / 2.16 / 2.13. They
describe memorised English sentences, not code typing.

## Fixes found on the way

- **Python could time out before it started.** The 10 s limit on a Test run included loading the
  Python runtime, so on a slow computer the first click reported "time limit exceeded" and
  restarted the load. Loading is now waited for separately (up to 3 minutes, with "Starting
  Python…"), and only running the code is timed. A test delays the runtime by 12 s to check this.
- **Thin baseline.** Three short practice tasks gave only 4 windows, below the old minimum of 5.
  The minimum is now 3 (D-037). Longer practice texts would be better.
- **Security review findings.** No mid-exam report for participants (it would let a student check
  whether they're flagged), no server paths in participant reports, and bounded reconciliation cost.

## Tests

| Suite | Result |
|---|---|
| Python | 334 passed. New: session signals 8, report rules 10, report API 3, serving model 2, problems 6 |
| Playwright (Chromium, Firefox, WebKit) | 152 passed, 4 skipped. New: the full journey (practice → exam → own report → dashboard), and slow-Python start |
| Demo (Chromium, DEV, human-like scripted typing) | 3 practice tasks (3/3 each) and a typed exam (3/3). Baseline 4 windows, typing check ran on 3 exam windows, **No review flags** |

The skips: the known WebKit clipboard case; the slow-start test (Chromium only, by design); and
the journey in WebKit. During that test's long scripted typing, Playwright's WebKit never finishes
loading Python, even after 4 minutes, though it loads in shorter WebKit tests. Safari is out of
scope (D-025); this stays an open question.

## What is weak

1. **The rules are hand-set.** Thresholds such as "40 pasted characters" or "50% of windows above
   the line" are reasonable guesses, not calibrated. They need the pilot and the study data.
2. **The reference ranges are from memorised English sentences**, not code. And the baseline comes
   from copying shown code (D-035), so genuine composing may sit further from it.
   **Expect false flags on the typing check** until P3 measures this.
3. **The baseline is small:** about 4–6 windows from three short tasks.
4. **No fused score, no AST features, no decisions or appeals in the dashboard yet.**
5. **Report endpoints are not rate-limited.** That's fine on one laptop, but needed before any
   deployment.

## What the lead should decide next

1. **Try it:** run `scripts\dev.ps1`, do the three practice tasks and the exam yourself, then open
   your report and the dashboard (token in `~\.integrity-exam\secrets\reviewer_token.txt`).
2. **Confirm D-037** (minimum of 3 baseline windows), or ask for longer practice texts instead.
3. **The rule thresholds** in `config/scoring.yaml → report`: keep them as the starting point for
   the pilot?
4. **Next:** the rest of P3 (AST features, a fusion model fitted once study data exists) or P4
   (reviewer decisions and appeals).
