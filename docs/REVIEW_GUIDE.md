# Review preparation guide

For the BITE308L project review. Slides: the "Integrity Scoring for Live Coding Exams" deck. Live
demo: `docs/DEMO.md`. Numbers here are as of 28 October 2026.

---

## 1. The 30-second pitch

> In an online coding exam, the code may not come from the student’s own head and hands. Our
> system records only what happens inside the code editor — key presses, edits, pastes — and
> builds each student’s personal typing baseline from practice tasks. During the exam it compares
> the student with themselves and produces evidence for a human reviewer. It never punishes
> anyone automatically. The software is complete up to the research stage; real student data
> waits for ethics approval.

---

## 2. Points to mention, in order

### Problem and framing (slides 2–3)
1. Three threats: pasted or AI-generated code, someone else typing, copy-typing from a second screen.
2. Webcam proctoring is intrusive and still ends with a human judgement.
3. **Our output is an integrity score S in [0, 1] (high = genuine) plus evidence; low scores go to a person.**
4. Say what it does **not** claim:
   - keystroke timing shows a person typed and whether it looks like *this* person, not who wrote the code;
   - the browser can be forged; the hash chain only shows tampering after data reaches the server;
   - code-structure (AST) drift is a weak signal, used only inside the fused score.
5. Our contribution: adapting keystroke biometrics to code, fusing four signals, calibrating, and testing against attacks. Few-shot keystroke enrollment itself is prior work (TypeNet).

### How it works (slides 4–9)
6. Architecture: browser (Monaco editor, capture, Python tests in Pyodide) → FastAPI server over WebSocket → PostgreSQL (encrypted, append-only, hash-chained log) → student and reviewer views. Self-hosted; no third-party services on the data path.
7. Student journey: 3 practice tasks (code shown, typed → baseline) → baseline check → exam → the student just leaves; reports are for reviewers (D-049).
8. Four signals: keystroke rhythm (TypeNet encoder), writing process (14 features), code structure (tree-sitter AST), clipboard and focus. Plus **server-side reconciliation**: text without matching key presses is flagged whatever the browser claims.
9. **The one real result:** the keystroke model reproduces all 10 published TypeNet results within their acceptance bands (section 3 below).
10. Baseline check: tests whether the baseline describes the student; a failed check is a review finding and never switches detection off.
11. Evidence rules today; the fused score S is built (weights ≤ 0, smoothing, threshold at 5% false flags) and waits for labelled study data.

### Review, security, privacy (slides 10–12)
12. Reviewer dashboard: evidence report and chart, keystroke-by-keystroke replay, hash-chain tamper check, decisions with required notes (never edited), named reviewer accounts, access log.
13. Webcam (demo feature): opt-in for test accounts only, encrypted, viewable by reviewers and admins, logged, **not analysed**. The head-movement panel is a "video demonstration" with example output — say so if asked.
14. Security: the student controls the browser, so the server trusts nothing it is told. Every automated security-review finding was fixed (examples on slide 11).
15. Privacy: editor only, pseudonyms, AES-256-GCM at rest, withdraw any time, retention job, adults only, and an **ethics gate**: real collection cannot start without ethics approval, governance values and named reviewer accounts.

### Study and evaluation (slides 13–15)
16. Study: 50+ students, two sittings a day apart; six exam tasks with conditions from a Williams Latin square (genuine ×2, A1 paste, A4 copy-type, A5 edit AI code, A7 refactor); scripted auto-typers A2/A3; reviewers blind to conditions.
17. Evaluation fixed in advance: nested cross-validation by student; primary endpoints = detection per attack at 5% false flags, and fused vs best single signal; bootstrap CIs over students; every attack reported, failures included; a ledger of every look at test students.
18. Synthetic dry run: the whole pipeline runs end to end. **Say clearly these are generated typists, not results.**

### Status and close (slides 16–19)
19. Engineering: ~430 Python tests, ~160 browser tests across Chromium/Firefox/WebKit, 49 logged design decisions, seeded and reproducible runs.
20. Limitations stated before the data (slide 17).
21. Next steps: ethics application, governance values, real-keyboard pilot, collection, evaluation, paper. Ask the reviewer for guidance on ethics and the timeline.

---

## 3. How the keystroke model was trained (P2)

**Goal.** Reproduce TypeNet (Acien et al., arXiv:2101.05570) on public data before using it on
code: a model that turns a window of key presses into a 128-number "typing fingerprint", so two
windows from the same person are close and from different people are far apart.

**Data.** The Aalto "136M Keystrokes" dataset (Dhakal et al., CHI 2018): 168,593 people, each
typing 15 English sentences, with millisecond key-down and key-up times. Licence: non-commercial
research with attribution. Read straight from the zip (sha256 recorded); nothing is redistributed.

**Protocol written first.** Before any training we wrote `docs/p2_protocol.md`, checking every
detail against the paper, marking what the paper does not state, and fixing acceptance bands in
advance: within max(1 point, 50% relative) of each published number.

**Split.** 67,000 training subjects, 1,000 validation subjects (held out from the paper's 68,000),
and as test set the first 1,000 of the next 100,000 subjects. Test subjects were never touched until
the end, and every test computation was written to a ledger.

**Input features** (per key press, as TypeNet §4.1): key code ÷ 255, hold time (HL), release→press
(IL), press→press (PL) and release→release (RL) latencies, in seconds. Sequences of M = 50 or
M = 70 keys, zero-padded with masking.

**Model.** Input batch normalisation → LSTM (128 units) → dropout 0.5 → LSTM (128 units); the final
hidden state is the 128-number embedding. About 200,000 parameters.

**Loss.** Triplet loss with squared Euclidean distance and margin 1.5: an anchor and a positive from
the same person are pulled together, a negative from another person pushed at least 1.5 further away.
Triplets chosen at random (as in the paper).

**Training settings.** Adam (β = 0.9, 0.999), 512 triplets per batch, 150 batches per epoch,
200 epochs, no early stopping, fixed seeds; checkpoints every 10 epochs (after one GPU crash) and a
test that a resumed run equals an uninterrupted one. **Hardware:** an RTX 3050 laptop GPU (6 GB),
about 80 minutes per M = 70 model and 51 minutes at M = 50.

**The one deviation: learning rate.** The paper's 0.05 did not train in our setup (the loss rose from
0.81 to 1.21; validation EER 36.5%). We chose among {0.05, 0.01, 0.005} on the 1,000 validation
subjects only: 0.005 gave 2.04% validation EER (decision D-032). Documented before any test access.

**How it was evaluated.** Equal error rate (EER): the point where wrongly accepting another person
and wrongly rejecting the right person are equally likely. For each test subject, G enrollment
sentences (G = 1, 2, 5, 7, 10) are compared with their own other sentences and with other people's;
the paper's scoring (Eq. 5) averages the distances to the G enrollment samples. EER is computed per
subject and averaged.

**Results (M = 70, mean per-subject EER, ours vs published):** G=1 4.11% vs 4.5% · G=2 2.65% vs 2.8%
· G=5 1.57% vs 1.7% · G=7 1.33% vs 1.4% · G=10 1.17% vs 1.2%. All 10 cells (M = 50 and 70) are in band.
For comparison, two non-deep baselines on the same subjects score 20.6–26.3% EER, so the LSTM is
15–20 times better.

**What the numbers do not mean.** They are English sentences typed in one sitting, not code typed
days apart; with one global threshold (what our system uses) the EER is 2–3× higher (3.42% at G=10);
and people vary a lot (per-subject SD 6.6 points at G=1). Identity is not authorship.

**How the trained model is used online.**
1. Practice typing is cut into windows of 70 key presses; each becomes an embedding; their mean is
   the student's **prototype** (D-033: the prototype rule matched Eq. 5 within 0.05 points and is
   cheaper online).
2. Exam typing is cut into sliding windows (every 35 keys); each window's distance to the prototype
   is compared with a **reference line**: the distance below which 95% of same-person comparisons
   fall, measured on the validation subjects (not test subjects). About 2.1 in the demo.
3. The baseline check can set the student's own, higher line (capped at 1.25 × the reference).
4. If half or more of the exam windows are beyond the line, the report flags the typing rhythm.

**Training still to come (needs study data).**
- Fine-tune the encoder on study students' code typing, once per cross-validation fold (D-047).
- Fit the fused score: a logistic regression over 7 distances + 2 availability flags, with every
  distance weight constrained to ≤ 0 (more anomaly can never raise S), C chosen on inner folds,
  threshold τ set so 5% of genuine validation sessions are flagged. The code is built and tested on
  synthetic data.

---

## 4. Live demo (about 8 minutes)

Before: start `scripts\dev.ps1`; copy the reviewer token
(`Get-Content "$HOME\.integrity-exam\secrets\reviewer_token.txt" | Set-Clipboard`); use a private window.

1. **Student:** http://127.0.0.1:5173/ → consent (tick the webcam box) → practice tasks → baseline
   check → exam: type a little, paste the rest → Submit → "you can close this window".
2. **Reviewer:** http://127.0.0.1:5173/#/dashboard → paste the token → Open report: verdict, findings
   (paste, untyped code, reconciliation), typing chart, process table, replay, tamper check, video,
   "Video demonstration" panel → record a decision with notes.
3. **Detection demo participants:** show same typist (no flags), other typist in the exam (flagged),
   other typist in the check (review finding). Scripted typists: mechanism, not accuracy.
4. **Study mode:** http://127.0.0.1:5173/?study=1#/ → six tasks with role-play conditions.

---

## 5. Likely questions and answers

**Why not just use a webcam?** It is intrusive, raises consent and data issues, and still needs a
person to judge. Our signals come from the editor alone. The webcam exists only as an opt-in demo
feature and is not analysed.

**Can a student cheat the system?** Yes, a determined one can. The browser is theirs, so a client
rewritten to forge consistent key presses evades us; server-side reconciliation, the hash chain and
replay checks raise the cost. Copy-typing with your own hands (A4) and edited AI code (A5) are the
hard cases. That is why the output is evidence for a person, never a verdict.

**What about false accusations?** Nothing is automatic. The threshold is set for 5% false flags on
genuine sessions, every flag shows its evidence, decisions need notes, and the notice lists known
causes of false flags (accessibility needs, injury, fatigue, a new keyboard).

**Isn't TypeNet someone else's work?** Yes, and we say so. Reproducing it is our foundation and our
check that the implementation is correct. The contribution is applying it to code and combining it
with process, structure and clipboard signals, plus calibration and attack evaluation.

**Why did you change the learning rate?** The paper's value did not train in our setup. We chose a
new one on validation subjects only, before touching test data, and documented it (D-032).

**Why practice tasks with the code shown?** So every student produces comparable typing and nobody
gets stuck. The cost: the baseline is copy-typing, and composing has more pauses; we state that.

**What if a student uses a different keyboard?** That is attack condition A8, a false-flag test in
the study. The device is recorded as a covariate.

**Why not show the student their report?** The lead decided reports are for reviewers (D-049). The
study's data-access requirements will be settled with the guide before real collection.

**How accurate is it?** On real students: not measured yet — that needs ethics approval and the
study. On public data, the keystroke model matches TypeNet (1.57% EER at G=5). The synthetic dry run
only shows the pipeline works.

**What does the head-movement panel compute?** Nothing yet: it is a video demonstration with example
output, showing where a planned analysis would appear. Do not present its figures as measurements.

**Is the data secure?** Encrypted at rest with AES-256-GCM, keys outside the repository and cloud
folders, append-only hash-chained log, pseudonyms, access log, erasure on withdrawal, retention job.

**Why fuse with weights ≤ 0?** Every input measures anomaly; forcing weights ≤ 0 guarantees more
anomaly can never make a session look more genuine, even if the training data is noisy.

**Why nested cross-validation?** With 30–50 students a fixed split leaves only 6–10 test students;
nested CV tests every student with a model that never saw them, without leaking tuning.

---

## 6. Numbers to remember

| | |
|---|---|
| Aalto data | 168,593 people × 15 sentences |
| Training split | 67,000 train / 1,000 validation / 1,000 test |
| Model | 2 LSTM × 128, embedding 128, triplet margin 1.5 |
| Training | Adam lr 0.005, 512 triplets × 150 batches × 200 epochs, ~80 min on RTX 3050 |
| Result | 10/10 cells in band; M=70 G=5: 1.57% vs 1.7% |
| Baselines | 20.6–26.3% EER (LSTM 15–20× better) |
| Windows online | 70 keys; exam stride 35; baseline needs ≥ 3 windows |
| False-flag target | 5% of genuine sessions |
| Study | 50+ recruited, 2 sittings ≥ 1 day apart, 6 exam conditions |
| Tests | ~430 Python, ~160 browser; 49 design decisions logged |

---

## 7. What not to say

- Don't say the system "detects cheating" or "proves" anything: it produces evidence for review.
- Don't quote the synthetic dry-run percentages as accuracy.
- Don't present the head-movement figures as measured.
- Don't claim the browser data can't be forged.
- Don't claim few-shot keystroke enrollment as our invention.

---

## 8. Checklist before the review

- [ ] Fill the cover slide: full names and the guide's name.
- [ ] Share the deck from its Share menu, or download it as PowerPoint/PDF.
- [ ] Run `scripts\dev.ps1` and click through `docs/DEMO.md` once.
- [ ] Have the reviewer and admin tokens ready on the clipboard.
- [ ] Reread section 5 (questions) and section 6 (numbers).
