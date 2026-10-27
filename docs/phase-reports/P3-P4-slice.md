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

## Addition: the baseline check (D-038, 2026-10-26; hardened 2026-10-27)

The lead asked for a test after the baseline that checks the baseline and supports detection. Setup
now has three steps: **practice** (3 tasks, the baseline), **baseline check** (1 task, held out),
then **exam**.

- **Checks the baseline.** The check task's windows are compared with the practice prototype.
  - If most are within the same-person range, the baseline is *confirmed*.
  - If not, it is a **review finding**: the baseline may not describe the person, or someone else
    (or a deliberately different style) typed the check.
- **Supports detection.** A confirmed check gives the person's own line: their largest check
  distance, **capped at 1.25 x the reference line**. The exam uses the higher of the two.
- **Hardened after a security review.** The first version switched the exam's typing comparison
  off when the check didn't match. That would have let a student fail the check on purpose to
  escape the comparison. Now:
  - a failed check never switches detection off;
  - only the first check counts, and only if submitted before the exam started;
  - the server allows one check session and decides each session's kind from the problem file;
  - students' own reports carry no distances or thresholds.

**Synthetic demo with the real model** (`eval/tools/detection_demo/`; two scripted typists, not
people, three runs, not an accuracy measurement). Reference line 2.13:

| Scenario | Check distances | Exam distances | Result |
|---|---|---|---|
| Same typist throughout | confirmed (0.90, 1.37) | 1.14, 0.97, 1.41 | No review flags |
| A different typist in the exam | confirmed (1.08, 1.54) | **3.95, 4.20, 4.14** | **Review**: typing rhythm |
| A different typist in the check | **does not match** (4.26, 4.50) | 0.84, 1.48, 1.11 (still compared) | **Review**: baseline check |

## Addition: reviewer decisions and student notes (D-039, 2026-10-27)

The first part of P4, built after "continue".

- **Reviewer decision.** Under each submitted exam on the dashboard: *concern confirmed*,
  *dismissed* or *inconclusive*, with required notes. A new decision supersedes the last one; the
  history stays and can't be edited, even directly in the database (append-only triggers).
- **Student notes.** On their own report the student can add a note to a submitted exam, such as
  "the pasted part is my own helper". The reviewer sees it next to the evidence.
- **What the student sees.** The outcome and date of the decision, not who decided or their notes.
- **Records.** Notes from both sides are encrypted at rest. Every decision and note is in the
  access log, which admins open from the dashboard (reviewers can't). Erasure removes all of it.
- The dashboard list has a **Decision** column ("Not reviewed" until someone decides).

## Addition: AST features and the hash-chain check (D-040, D-041, 2026-10-27)

- **AST features (SPEC 6.3)** in `ml/src/integrity_ml/ast_features.py`: tree-sitter parsing that
  tolerates syntax errors, the smoothed node histogram, the problem "tilt", JSD drift, four style
  scalars, availability, and AST jumps. Versions are pinned and hashes recorded. 11 unit tests on hand-written
  programs with known answers.
- **In the report:** "Code structure that arrived without typing" (AST jumps) as information, with
  purple markers on the reviewer's chart. Not a flag on its own.
- **Not shown:** AST drift. It is a weak, fusion-only signal, and it needs per-problem references
  from study data. Finding from the tests: on short programs it is small even between clearly
  different styles (about 0.04).
- **Decision panel:** the exam's hash-chain check, with the caveat that it shows tampering after
  the server received the data, not what the browser sent.

## Addition: governance, withdrawal and retention (D-042, 2026-10-27)

- Q4 is settled and the consent draft accepted. The values have one home, `config/privacy.yaml →
  governance`; the notice shows them, and "[to be set]" until the lead enters them. The backend
  won't start with real collection on while any is blank.
- **Withdraw:** "Withdraw from the study" (two steps) on the tasks page and the report. It closes
  any live recording and erases everything; the access log records the withdrawal without the
  pseudonym.
- **Retention job:** `scripts/purge_retention.py`, dry run unless `--apply`; refuses while the
  dates are blank. Derived features in the data root are reported as due, for manual deletion.

## Addition: process features (D-043, 2026-10-27)

- All 14 SPEC 6.2 features in `ml/src/integrity_ml/process_features.py`, over the whole module or
  any time window, with the baseline, the scale fit and the distance. 11 unit tests on hand-built
  logs with worked-out answers.
- The reviewer's report has a "How the code was written" table: exam beside the practice mean.
  Context only: what is unusual needs each feature's normal spread from study data. Participants
  don't see it.
- With this, every signal the fused score needs exists (keystroke, process, AST, clipboard). The
  fusion itself still waits for labelled study data.

## Addition: named reviewer accounts (D-044, 2026-10-27)

- `python scripts/staff_accounts.py add dr-rao --role reviewer` prints a token once; `list` and
  `disable` manage accounts. Decisions and the access log show the handle; the dashboard shows who
  is signed in. A disabled token stops working immediately.
- The shared development token still works for testing, but the backend refuses to start with
  real collection on while it is enabled.

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
| After D-038 hardening and D-039 (2026-10-27) | Python 351 passed (new: reviews API 3). Playwright 155 passed, 4 skipped (new: access log; the journey now adds a student note and a reviewer decision) |
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
4. **No fused score yet**, and AST drift is computed but unused until study data gives per-problem
   references. Decisions and student notes now exist (D-039),
   and decisions are signed by named reviewer accounts (D-044); the shared development token
   remains for testing and is refused once real collection is switched on.
5. **Report endpoints are not rate-limited.** That's fine on one laptop, but needed before any
   deployment Reports are rebuilt on every request; with AST parsing, a forged worst-case log costs
   about 3 s per exam (bounded by `features.ast.max_snapshots` and `max_parse_chars`). Cache per
   closed session before deployment.

## What the lead should decide next

1. **Try it:** run `scripts\dev.ps1`, do the three practice tasks and the exam yourself, then open
   your report and the dashboard (token in `~\.integrity-exam\secrets\reviewer_token.txt`).
2. **Confirm D-037** (minimum of 3 baseline windows), or ask for longer practice texts instead.
3. **The rule thresholds** in `config/scoring.yaml → report`: keep them as the starting point for
   the pilot?
4. **Next:** the rest of P3 (AST features, a fusion model fitted once study data exists), or the
   rest of P4 (named reviewer accounts, chain-verification status in the decision panel).
