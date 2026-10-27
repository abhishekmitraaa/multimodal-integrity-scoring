# Detection demo (D-038), SYNTHETIC

Two scripted typists with different rhythms (A: short holds and quick gaps; B: longer holds and
pauses) go through the real app: three practice tasks, the baseline check, then the exam. The real
keystroke model judges the result.

| Scenario | Practice | Check | Exam | Expected |
|---|---|---|---|---|
| A | A | A | A | check confirmed, no review flags |
| B | A | A | B | check confirmed, exam flagged |
| C | A | B | A | check does not match: review finding; exam still compared |

This shows the mechanism works end to end. It is **not** an accuracy measurement: scripted typists
are not people, and three runs are not a sample. Each run creates a `DEV-` participant. Numbers come
from the reviewer report (reviewer token from the secrets folder): participants' own reports carry none.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1     # in one window, with the model installed
node eval\tools\detection_demo\detection_demo.cjs          # in another; set DEMO_OUT to keep screenshots
```

Result on 2026-10-26: see docs/phase-reports/P3-P4-slice.md.
