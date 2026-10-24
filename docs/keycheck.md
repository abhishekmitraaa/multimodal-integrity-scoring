# Real-keyboard check

Status: ready to run. It is P1 review decision 4. **Every file it produces is development data.**
No file from it ever becomes part of a study dataset.

## Why

Every timing measurement in P1 used keystrokes injected by Playwright. This check uses real hands on
real keyboards to answer three questions:

1. **Overlapping keys.** How often is the next key pressed before the previous one is released
   (a negative inter-key latency, IL)? How long are the overlaps?
2. **Held keys.** When a key is held down, how soon does auto-repeat start and how fast does it
   run? Do repeats carry the `repeat` flag, and does any browser send a keyup per repeat? Our
   features drop repeats by that flag (SPEC §6.1).
3. **Clocks.** Do `event.timeStamp` and `performance.now()` share a clock? How long after the key
   press does our handler run? Is `timeStamp` taken when the key is pressed (input time) or when the
   page gets round to handling it (dispatch time)? Task 4 answers the last question by stalling the
   page on purpose: keys pressed during a stall are stamped inside the stall only if `timeStamp` is
   the input time.

## Who and what

- **Team members only** (Mitra, Sneha, Mehul), voluntarily. Not participants, not friends, not
  classmates. Real participants wait for ethics approval.
- **Runs.** One run is one person × one keyboard × one browser. Aim for every person on:
  - keyboards: the laptop's built-in one, and an external USB or Bluetooth one if you have it;
  - browsers: Chrome or Edge, and Firefox (the study browsers, D-025).

  That is up to 4 runs each, about 5 minutes per run.
- Use a browser profile **without extensions that read page text** (Grammarly, translators,
  password managers that watch fields), or write the extension in the keyboard description. Such
  extensions can add key-handling work to the page.

## Already answered without a keyboard (2026-10-24)

OS-level injected keystrokes (Windows `SendInput`, synthetic; `eval/tools/os_inject/`) answered
two of the questions for Chrome, Edge and Firefox on Windows:

- `timeStamp` is the **input time**: keys typed during a page stall are stamped inside it.
- `isTrusted` is `true` for OS-injected keys.

They cannot answer what depends on keyboard hardware and real hands: overlaps, auto-repeat timing,
and differences between laptop and external keyboards. Those still need this check. Injected
holds don't auto-repeat at all.

## How to run it

The page runs entirely in the browser. It doesn't need the backend or the database.

```powershell
cd C:\dev\integrity-exam\frontend
npm install          # first time only
npm run dev          # serves http://127.0.0.1:5173, cross-origin isolated by default (D-021)
```

1. Open **http://127.0.0.1:5173/#/keycheck** in the browser you are testing.
2. Check the grey line under the form: it should say **cross-origin isolated: yes**. If it says no,
   stop and tell Mitra.
3. Keep the random `DEV-…` tester label, or type your own short label. **Don't use your name.** Use
   the same label for all your runs.
4. Choose the keyboard and the operating system. Optionally describe the keyboard (for example
   "Dell KB216" or "HP laptop").
5. Do the four tasks in order: click **Start**, do the task in the editor box, then click **Finish
   task**.
   - Tasks 1 and 2: type naturally and fix typos as you normally would. Don't aim for perfection.
   - Task 3: hold A for about 2 seconds and release, then do the same with Backspace.
   - Task 4: the page will stutter on purpose. Keep typing normally.
6. Click **Save file**. The browser saves `keycheck_<label>_<browser>_<keyboard>_<time>.dev.json`
   to your Downloads folder.
7. **Move** (don't copy) the file to `%INTEGRITY_DATA_ROOT%\dev\keycheck\` on the machine that
   will run the report, for example `C:\integrity-data\dev\keycheck\`. Delete it from Downloads.
   Never put it in the repository, OneDrive, Google Drive, WhatsApp or email.

## The report

```powershell
cd C:\dev\integrity-exam
$env:INTEGRITY_DATA_ROOT = "C:\integrity-data"
.venv\Scripts\python -m integrity_eval.keycheck "$env:INTEGRITY_DATA_ROOT\dev\keycheck" --out "$env:INTEGRITY_DATA_ROOT\dev\keycheck_report.md"
```

The report refuses to run if:

- a file isn't labelled `dataset: development`;
- synthetic and real files are mixed;
- the folder or the output path is inside the repository.

It has one row per run:

| Section | What to look for |
|---|---|
| Runs | Browser and version, isolation, and the grid that `timeStamp` values sit on (expected 5–20 µs isolated) |
| Overlapping keys | Share of IL < 0 with and without modifier keys. A held Shift always overlaps, so the "without modifiers" column shows real rollover. |
| Held keys | Initial repeat delay and interval. "Repeats without the flag" and "keyups during a hold" should both be 0. |
| timeStamp vs performance.now() | A negative minimum lag means the two do not share a clock. The task 4 verdict says whether `timeStamp` is the input time or the dispatch time. |

## What we do with the answers

- **Input time:** our timings don't include the page's own delays. **Dispatch time:** a busy page
  adds noise to every latency, and the Monaco editor's rendering work matters. We would then
  measure how much noise that adds before trusting sub-10 ms differences.
- **Overlaps and repeats:** these check the pairing rules in SPEC §6.1 (keyup matches the most
  recent unmatched keydown; repeats are dropped by their flag) against real behaviour.
- **Differences between browsers or keyboards:** these become covariates, and they support the
  rule that each participant uses the same browser in both sittings (D-025).

## Data handling

- **What a file contains:** key codes (`KeyA`, not the character), timings, flags, the browser and
  version, the OS and keyboard you chose, and your tester label. Typed text and key values are not
  stored.
- **Where it lives:** only under `INTEGRITY_DATA_ROOT`, outside the repository and any synced
  folder. Nothing is uploaded; the page never talks to the server.
- **How long:** delete the files once the lead has reviewed the P2 results, unless the lead
  decides otherwise.
- **Never study data.** Every file carries `dataset: development` and `not_for_study: true`. The P5
  study tooling must refuse such files.
- **Limits:** three people, a fixed text, one sitting each. The results describe browsers and
  keyboards, not typists.
