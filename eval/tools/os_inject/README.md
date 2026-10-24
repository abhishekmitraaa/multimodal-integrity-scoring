# OS-level keystroke injection check (Windows, SYNTHETIC)

Types into the `#/keycheck?synthetic=1` page in real, headed browser windows (Edge, Chrome and
Playwright's Firefox) through Windows `SendInput`, the path that AutoHotkey-style auto-typers use.
It is the first piece of the A2 attack harness: a constant-rate typer (150 ms press-to-press, 80 ms
hold).

**Safety.** `inject.ps1` checks before every event that the foreground window title starts with
"Coding Practice Study", and aborts (releasing any pressed keys) if it doesn't. It sends only
letters, space and Backspace.

**Data.** Every file is labelled `synthetic: true` and `dataset: development` and is written to
`%INTEGRITY_DATA_ROOT%\dev\keycheck-os-injected\`. Never put these files in the same folder as
real-keyboard check files (the report refuses to mix them).

```powershell
cd C:\dev\integrity-exam\frontend; npm run dev        # terminal 1
cd C:\dev\integrity-exam; $env:INTEGRITY_DATA_ROOT = "C:\integrity-data"   # terminal 2
node eval\tools\os_inject\os_inject_check.cjs edge chrome firefox
.venv\Scripts\python -m integrity_eval.keycheck "$env:INTEGRITY_DATA_ROOT\dev\keycheck-os-injected" --out "$env:INTEGRITY_DATA_ROOT\dev\keycheck-os-injected_report.md"
```

Results from 2026-10-24 are in SPEC §4.5 and §4.11.
