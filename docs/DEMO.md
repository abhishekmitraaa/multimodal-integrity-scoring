# Demo guide (about 15 minutes)

For showing the prototype to the project team or the faculty guide. Everything runs on one laptop
with development data. No real participant data exists yet: real collection waits for ethics approval.

## Before the demo

1. Start everything: `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1` (Docker, database,
   migrations, backend on :8000, web app on :5173). Wait for `http://127.0.0.1:5173/`.
2. Optional, so the dashboard already has examples: `node eval\tools\detection_demo\detection_demo.cjs`
   (three scripted typists, about 5 minutes; see `eval/tools/detection_demo/README.md`).
3. Have the tokens ready (in `C:\Users\<you>\.integrity-exam\secrets\`): `reviewer_token.txt` for
   the dashboard, `admin_token.txt` for the access log.
4. Use **Chrome, Edge or Firefox** (D-025). Open a private window so earlier test data in the tab
   doesn't get in the way.

## 1. The student's side (5 min)

| Step | Where | What to point out |
|---|---|---|
| Consent | `http://127.0.0.1:5173/` | What is recorded (keys and timing inside the editor only, no camera or screen), the false-flag notice, withdrawal. Governance fields show "[to be set]" until the lead enters them. |
| Practice tasks | Step 1 on the tasks page | The code to type is shown (D-035): this typing builds the student's personal baseline. |
| Baseline check | Step 2 | One more typed task, held out, to confirm the baseline really describes this student. |
| Exam | Step 3 | Type part of the solution, then **paste** a few lines from outside. Run the tests and submit. |
| Own report | "See your report" | A plain verdict and findings, **no numbers** (so a student can't learn how close to the line they can go). The student can add a note for the reviewer. |

## 2. The reviewer's side (5 min)

| Step | Where | What to point out |
|---|---|---|
| Dashboard | `#/dashboard`, reviewer token | Every participant, progress, decision status. Says who is signed in. |
| Report | "Open report" | Typing-rhythm chart against the student's own baseline (and their personal range from the check); paste markers; findings: external paste, code not typed, text without key presses (server-side reconciliation), auto-typer rhythm, AST jumps; "How the code was written" (process features). **No single score is shown**: that needs study data. |
| Tamper check | Under the exam | The event log's hash chain verifies (shows changes after the server received the data). |
| Replay | "Replay this exam" | The code rebuilt keystroke by keystroke from the log. |
| Decision | Under the exam | Confirm / dismiss / inconclusive, with required notes; kept permanently; the student sees only the outcome. |
| Access log | "Access log (admin)" with the admin token | Every read and decision is recorded. |

The detection-demo participants show the three outcomes: same typist (no flags), a different typist
in the exam (flagged on typing rhythm), a different typist in the baseline check (review finding).
These are scripted typists, not people: it shows the mechanism, not accuracy.

## 3. The study protocol (2 min)

Open `http://127.0.0.1:5173/?study=1#/` (a dev tester in the study protocol):

- Sitting 2 has six exam tasks, each with a condition from a balanced Latin square: solve it
  yourself ×2, paste a solution (A1), copy-type it from another screen (A4), make generated code
  look like yours (A5), reorganise your own code (A7). All role-play, no consequences.
- An A1/A4/A5 task has "I'm starting now" (marks the attack onset) and opens a frozen AI-generated
  solution in its own tab. Reviewers never see the conditions.
- Real participants also get the sitting rules: the same browser in both sittings, a day between them.

## 4. Withdrawal (1 min)

"Withdraw from the study" at the bottom of the tasks page: two clicks, everything deleted, the access
log keeps no identifier.

## 5. What the research will measure (2 min)

| Result | Where | Status |
|---|---|---|
| TypeNet keystroke model reproduced on 168,000-person Aalto data, all 10 published cells within their acceptance bands (e.g. M=70, G=5: 1.57% EER vs 1.7% published) | `docs/phase-reports/P2-results.md` | **real result** |
| The full evaluation pipeline (nested cross-validation, fused score, attack detection, ablations, calibration) | `D:\integrity-data\derived\fusion_dryrun\fusion_dryrun_synthetic_p2encoder.md` | **SYNTHETIC test of the code only, never a result** |
| Detection on real students per attack (A1-A8), false flags, time to detection | runs on the study data with `integrity_eval.d2_eval` | after ethics approval and collection |

## Honest framing to keep in the talk

- Keystroke timing shows that a person typed, and whether it looks like *this* person; it does not
  show that they wrote the code.
- Nothing is ever punished automatically: every flag goes to a person, who records a decision.
- The browser can forge what it sends; the hash chain only shows tampering after the data reaches
  the server. Server-side reconciliation raises the cost of forging, but doesn't prevent it.
- AST drift is a weak signal, used only inside the fused score.
- Expected hard cases: copy-typing with your own hands (A4) and edited AI code (A5).

## If something goes wrong

- The consent page says the server is not running: start `scripts\dev.ps1` again.
- "Starting Python…" takes up to a minute the first time on a slow laptop (Pyodide loads once).
- A study task says "please use Chrome, Edge or Firefox": Playwright's or another Chromium build
  isn't accepted by the study protocol; use the normal browser.
