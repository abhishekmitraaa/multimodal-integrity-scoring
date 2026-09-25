# SPEC: Personalized Multi-Modal Integrity Scoring for Live Coding Exams

Version 0.3, 2026-09-26. Course: BITE308L, VIT. Status: **P0 and P1 approved; P2 started with
the protocol write-up** ([p2_protocol.md](p2_protocol.md)). Q4 is with the faculty guide.
Repository: `C:\dev\integrity-exam`, outside any cloud-synced folder. Python is pinned to 3.11.

Markers used in this document:

| Marker | Meaning |
|---|---|
| **[BRIEF]** | Fixed by the project brief. Change only with the lead's approval. |
| **[PROPOSED]** | Engineering default chosen here. Needs approval; listed in [DECISIONS.md](DECISIONS.md). |
| **[OPEN]** | Needs a decision from the lead before the phase that depends on it. |
| **[VERIFY]** | A fact, number or library behaviour not yet checked against its source. Must be checked before we rely on it (library behaviour in P1–P3, citations in P6). |

MUST / SHOULD / MAY follow RFC 2119. The canonical wire contract is
[shared/schema/event.v1.schema.json](../shared/schema/event.v1.schema.json). If this document and
the schema disagree, the schema wins and this document gets fixed.

---

## 1. Goal and honest framing

### 1.1 Goal

A web-based live coding exam environment that:

1. captures keystroke telemetry, clipboard events and code-structure snapshots in a Monaco editor,
2. builds a per-student baseline from 2–3 short practice modules,
3. produces a continuous integrity confidence score $S \in [0,1]$ during the exam (high = genuine),
4. routes low-$S$ sessions to a human reviewer dashboard with the evidence.

**No automated punishment, ever.** The system never grades, penalises, or notifies anyone other
than the reviewer queue.

### 1.2 What the system can and cannot show [BRIEF]

- Keystroke timing proves a human was typing, not that the human was the author. Timing-only
  detection is weak against transcribing LLM output from a second device (copy-type) and against
  timing-forgery auto-typers.
- Therefore the system fuses four signals: (1) keystroke identity distance, (2) process features
  from the edit stream, (3) AST drift normalised per problem, (4) clipboard and paste metrics.
- Few-shot enrollment already exists in keystroke biometrics. TypeNet reports 4.5% EER at 1
  enrollment sequence and 1.2% at 10 (desktop, triplet loss, 70-keystroke sequences, **1,000 test
  subjects**, EER averaged over per-subject thresholds, short memorised English sentences). These
  figures are checked against arXiv:2101.05570v3, Table 2; the published version is [VERIFY]. The
  168,000 figure is the dataset size, not the test set. See [p2_protocol.md](p2_protocol.md) §0.
  Our contribution is code-domain adaptation, fusion, the calibration protocol, and an adversarial
  evaluation. We do not claim more.
- Population AI-code detectors fail across domains and under humanising **[VERIFY: needs a
  source in P6 or the sentence is dropped]**. AST drift is a weak signal used only in fusion.

Two more limits follow from the design:

- $S$ only decides who goes to the review queue. It is not evidence of misconduct. "Auto-accept"
  means "not routed to review", not "certified honest".
- The client is untrusted. Whoever controls the browser (the student) can forge any client-side
  telemetry: timings, key codes, `isTrusted`, change causes, snapshots and run results.
  `isTrusted` is not a defence (§4.5). The hash chain (§4.4) shows tampering *after the data
  reaches the server*, not forging at the source. Server-side reconciliation (§4.7, P3) raises the
  cost of naive forging; it cannot stop a fully rewritten client.

### 1.3 Non-goals for v1

- No browser extension, lockdown browser, webcam, microphone, screen recording or mouse-movement
  capture.
- No detection of second devices except through behavioural traces inside the editor.
- No authorship proof and no automated academic decision.
- Python is the only exam language (tree-sitter-python). Other languages come later, if at all.
- Safari is out of scope. The study browsers are Chromium-based (Chrome, Edge) and Firefox (D-025).

### 1.4 Known limitations, stated up front

- **Run/Test results are client-reported and forgeable.** Code runs in Pyodide inside a Web Worker
  in the student's browser (decision Q2). The server logs what the client says the result was.
  Results are never used for grading, only for the run-cadence process feature.
- **Role-play is not real cheating.** Attack conditions A1, A4 and A5 are performed by consenting
  volunteers told to "cheat" with no stakes. Real cheaters are motivated, may practise evasion,
  and may behave differently under exam stress. Detection rates measured on role-play may overstate
  or understate real-world performance. Every report carries this caveat.
- **Participants know transcription is studied.** The practice modules include a transcription
  block, and A4 asks participants to copy-type. Participants therefore know copy-typing is being
  studied and may type differently from an unaware student. The transcription-mode profile may
  partly capture "typing while observed".
- **Small, local sample.** 50+ volunteers from one university, with mostly similar keyboards and
  layouts. Results do not generalise to other populations without new data.
- **Client-side trust.** See section 1.2: someone who controls the browser can forge any telemetry,
  and `isTrusted` does not stop an auto-typer.
- **Timing is only as good as the browser's.** All P1 timing used injected keystrokes. Real-keyboard
  behaviour (overlaps, auto-repeat, what `timeStamp` measures) is measured with the check in
  [keycheck.md](keycheck.md). Its output is development data only.

---

## 2. Architecture

```
 Browser: Monaco + TypeScript (Vite)       Server: FastAPI, Python 3.11                PostgreSQL
 ┌─────────────────────────┐  WSS batch  ┌──────────────────────────────────┐ append ┌────────────┐
 │ capture layer           │────────────▶│ ingest: validate, order,         │───────▶│ events     │
 │  keys, content deltas,  │◀────────────│ server_seq, t_server, hash chain │        │ checkpoints│
 │  clipboard, focus,      │   ack/nack  ├──────────────────────────────────┤        │ scores     │
 │  snapshots, run/submit  │             │ incremental feature state        │◀──────▶│ cases      │
 └─────────────────────────┘             │ scoring per tick → S(t)          │        │ audit log  │
                                         ├──────────────────────────────────┤        └────────────┘
 Reviewer dashboard  ◀──── REST / WS ────│ review API, replay, access log   │
                                         └──────────────────────────────────┘
 ml/    offline: encoder pretrain + fine-tune, fusion fit, threshold calibration → versioned artifacts
 eval/  offline: attack generators, collection protocol, metrics, reports
```

| Package | Owns |
|---|---|
| `frontend/` | Monaco exam app, practice modules, consent screen, Pyodide Run/Test in a Web Worker, reviewer dashboard UI, Playwright tests |
| `backend/` | FastAPI app, WebSocket ingest, hash chain, storage, replay, online scoring, review and privacy endpoints |
| `ml/` | Feature extraction (keystroke, process, AST, clipboard), keystroke encoder, digraph baseline, fusion, calibration |
| `eval/` | Attack harness (A1–A8), dataset splits, metrics, bootstrap, reports, test-access ledger |
| `shared/schema/` | Event wire contract (JSON Schema), used by both the TS client and the Python server |
| `config/` | All tunables as YAML. No magic numbers in code. |
| `docs/` | This spec, decisions log, phase reports, later the paper and ethics material |

Feature code lives in `ml/` and is imported by `backend/` for online scoring, so online and offline
features are computed by the same functions. The server never reimplements a feature.

---

## 3. Entities

| Entity | Definition |
|---|---|
| Participant | Identified only by a pseudonym: 8 Crockford base32 characters from a CSPRNG, after a prefix. Three kinds [D-022]: `P-` real (refused until `privacy.real_collection_enabled` is set after ethics approval); `SYN-` synthetic (generated by scripts, never a person); `DEV-` team members testing the app (never used in results, purged routinely). |
| Problem | `problem_id`, statement, starter code, tests, reference solutions. |
| Session | One attempt at one problem: `kind ∈ {practice, exam}`. Has a `session_id` (UUIDv4) and a secret `session_nonce` (32 random bytes). |
| Segment | One page lifetime inside a session. A reload starts a new segment with a new clock origin. Numbered by `epoch = 0, 1, 2, …` |
| Enrollment set | The participant's practice sessions (2–3 modules). |
| Condition | Experimental label for a study session (`genuine`, `A1` … `A8`) plus attack onset time. Stored by the study tooling and **never sent to the scoring path**. |

---

## 4. Event capture

### 4.1 Clocks

- **Client time.** `t_client_us = round(event.timeStamp × 1000)`: the DOMHighResTimeStamp in
  microseconds, relative to `performance.timeOrigin` of the current segment. For events without a
  DOM event (for example snapshots) the client uses `performance.now()`.
- **Segment origin.** `segment_start` carries `time_origin_unix_us = round(performance.timeOrigin × 1000)`
  so absolute client time can be reconstructed.
- **Server time.** `t_server_us` is UTC wall-clock microseconds at batch receipt. All events in one
  batch share it.
- **Clock sync.** Every 30 s the server pings and the client pongs. The server records a
  `clock_sync` event with RTT and estimated offset.
- **No floats on the wire.** Every number in an event is an integer, so hashing and replay are
  exact. Device pixel ratio is sent as `dpr_x100`. JSON Schema treats `1000000.0` as an integer,
  so the schema alone cannot enforce this. The server's JSON parser MUST reject any number token
  containing `.`, `e` or `E` (a `parse_float` hook) before schema validation. P1 test.
- **[VERIFY-P1] Timer resolution.** Browsers coarsen timers, and the amount depends on the browser
  and on cross-origin isolation (COOP/COEP headers). P1 measures the real resolution of
  `KeyboardEvent.timeStamp` and `performance.now()` in Chromium, Firefox and WebKit, with and
  without COOP/COEP, and checks whether `timeStamp` is the OS input time or the dispatch time. Every
  segment records its measured resolution (§4.9). The keystroke modality is marked unavailable for
  segments whose resolution is worse than `features.keystroke.max_timer_resolution_us`.
- **Cross-origin isolation [DECIDED D-021].** The app is served with COOP/COEP by default (5–20 µs
  timers instead of 100 µs–1 ms). Every enrollment and exam session in the study MUST use the same
  setting. It is recorded per segment (`timer.cross_origin_isolated`), and a study session without
  isolation is excluded from keystroke features. We make **no claim** that isolation improves
  identity accuracy: keyboard hardware, OS input handling and scheduling jitter are much larger than
  1 ms. P5 collection tooling enforces the setting (§13).

### 4.2 Transport, batching and ordering

- The client assigns `client_seq = 0, 1, 2, …` per session, in dispatch order, at the moment the
  event is created.
- **Flush rule [BRIEF + PROPOSED].** The client sends a batch when any of these is true:
  15 `keydown` events are buffered; 5000 ms have passed since the oldest unsent event; a priority
  event occurs (`paste`, `cut`, `copy`, `drop`, `blur`, `visibility`, `run`, `submit`,
  `segment_end`); or `pagehide` fires.
- **Connect.** On (re)connect the server replies `welcome {next_client_seq, epoch}`. A new page
  starts at `next_client_seq` with `epoch + 1`.
- **Acceptance.** The server accepts a batch only if its events are consecutive in `client_seq`.
  - First seq == expected: accept all.
  - First seq < expected: drop the already-stored prefix (idempotent resend) and accept the rest.
  - First seq > expected: reject with `nack {resend_from: expected}`.
- **Ack.** `ack {next_client_seq}`. The client keeps every unacked event and resends it after
  `capture.resend_timeout_ms` or after reconnect.
- **Lost events.** Events buffered but not delivered before a tab dies are lost. The server cannot
  count them. It flags a segment that has no `segment_end` as `unclean_end`. The dashboard shows it.
- **Server-origin events.** `clock_sync`, `ws_open`, `ws_close` and `gap` are created by the
  server and chained like client events, with `origin = "server"` and `client_seq = null`.

### 4.3 Stored event record (server)

| Column | Type | Source |
|---|---|---|
| `session_id` | uuid | session |
| `server_seq` | bigint | server, gapless from 0 per session |
| `epoch` | int | batch envelope |
| `client_seq` | bigint, null for server events | client |
| `origin` | `client` \| `server` | server |
| `type` | text | client or server |
| `t_client_us` | bigint, null for server events | client |
| `t_server_us` | bigint | server |
| `batch_id` | bigint | server |
| `data` | encrypted bytes (§10.6) | client or server |
| `prev_hash`, `hash` | 32 bytes each | server |

### 4.4 Hash chain and checkpoints

$$
h_{-1} = \mathrm{SHA256}(\texttt{"IMS-CHAIN-v1"} \,\|\, \texttt{session\_id} \,\|\, \texttt{session\_nonce})
$$
$$
h_k = \mathrm{SHA256}(h_{k-1} \,\|\, C(e_k))
$$

$C(e)$ is the UTF-8 encoding of the JSON object
`{session_id, server_seq, epoch, client_seq, origin, type, t_client_us, t_server_us, data}` with
sorted keys, separators `(",", ":")`, `ensure_ascii=False`, computed over the **plaintext** before
encryption. Because the schema bans floats, this form is unambiguous.

**P1 scope: plain hash chain only** (decision before P1). Signed checkpoints are deferred.

- **Verification.** `verify_chain(session_id)` recomputes the chain and reports the first bad
  index.
- **Head hash at close.** Closing a session returns `{n_events, head_hash}` and the submit screen
  shows it. This is unsigned. It is included because it costs nothing.
- **What it detects in P1.** Accidental corruption, and any edit, insertion, deletion or reordering
  of stored events by someone who does not also recompute every later hash. It also catches a full
  recomputation, but only if the participant kept the head hash from their submit screen.
- **What it does not detect in P1.** A deliberate rewrite by someone with database write access who
  recomputes the whole chain, when nobody kept the head hash. Signed checkpoints would close this
  gap and are deferred.
- **What it never detects.** Anything a dishonest client sent in the first place.
- **Deferred.** Every `capture.checkpoint_every_events` events and at close, the server signs
  `(session_id, server_seq, h)` with an Ed25519 key held outside the database, and the receipt
  carries the signature.

### 4.5 Event types

Common fields for every client event: `client_seq`, `type`, `t_client_us`, `data`. Per-type `data`
fields are defined exactly in the JSON Schema. Summary:

| `type` | When | `data` fields |
|---|---|---|
| `segment_start` | page load or new segment | `time_origin_unix_us`, `page` (practice\|exam), `problem_id`, `editor_policy_id`, `editor_policy_sha256`, `device` (§4.9), `timer` (§4.9), `synthetic` |
| `segment_end` | submit, unload, timeout, abort | `reason` |
| `keydown`, `keyup` | KeyboardEvent inside the editor or its find widget | `code`, `cat`, `rep`, `mods`, `trusted`, `composing`, `target`, `line`, `col` |
| `content_change` | each change in Monaco `onDidChangeModelContent` | `version_id`, `idx`, `n`, `offset`, `del_len`, `ins_len`, `text`, `start_line`, `start_col`, `end_line`, `end_col`, `cause`, `undo`, `redo`, `flush` |
| `paste` | DOM paste on the editor, merged with Monaco `onDidPaste` | `len`, `newlines`, `trusted`, `mimes`, `start_line`, `start_col`, `end_line`, `end_col` |
| `copy`, `cut` | DOM copy or cut in the editor or problem panel | `source`, `len`, `sha256` |
| `drop` | DOM drop that reaches the editor (policy blocks it; logged if it happens) | `len` |
| `focus`, `blur` | editor or window focus change | `target` |
| `visibility` | `visibilitychange` | `state` |
| `cursor` | cursor or selection change **not** caused by typing (throttled) | `line`, `col`, `sel_len`, `reason`, `source` |
| `composition` | IME composition | `phase`, `len` |
| `run` | Run or Test finishes in the Pyodide worker. **Client-reported, forgeable.** | `kind`, `n_tests`, `n_passed`, `status`, `dur_ms`, `version_id` |
| `submit` | Submit | `version_id`, `sha256` |
| `snapshot` | timer, large insert, run, submit, segment start, resync | `version_id`, `reason`, `len`, `sha256`, `text` |
| `client_notice` | reconnect, buffer overflow, policy mismatch, clock regression, error | `code`, `detail` |
| `clock_sync` *(server)* | every 30 s | `rtt_us`, `offset_us` |
| `ws_open`, `ws_close` *(server)* | connection lifecycle | `code` |
| ~~`gap`~~ *(server)* | Not used. Within a page, gaps cannot occur (nack/resend). Events lost when a tab dies without a beacon are counted in `sessions.unclean_segments`. | – |

Field notes:

- **`code`** is `KeyboardEvent.code`, the physical key, for example `KeyA`, `Digit1`,
  `BracketLeft`. It is needed for digraphs and does not depend on keyboard layout.
- **`key` is deliberately not stored.** The client derives `cat` from `KeyboardEvent.key`
  (layout-aware) and then drops `key`. The schema rejects events that contain it.
- **`mods`** is a bitmask: 1 = Shift, 2 = Ctrl, 4 = Alt, 8 = Meta.
- **`rep`** marks auto-repeat keydowns. They are excluded from timing features.
- **`trusted`** is `event.isTrusted`. It catches only synthetic events dispatched from page
  JavaScript by an unmodified page. **It is not a defence.** It does not catch OS-level injection
  (AutoHotkey, xdotool, USB injectors) or CDP-driven input. The browser owner can also make it
  report anything. **Measured in P1:** Playwright-driven keystrokes report `isTrusted = true` in
  Chromium, Firefox and WebKit, so browser-automation auto-typers (A2/A3) look trusted. OS-level
  injection on Windows was not measured. It is logged as weak evidence only.
- **Lengths and offsets** are in **UTF-16 code units**, as Monaco reports them. The server's replay
  is UTF-16-aware and is tested with non-BMP characters.
- **Lines and columns** are 1-based, as in Monaco.
- **Copy hashes.** `sha256` is the hex SHA-256 of the copied text after normalising line endings
  (`\r\n` and `\r` become `\n`). Copied text itself is not stored.

### 4.6 Key categories (`cat`)

| `cat` | Rule, applied to `KeyboardEvent.key` in this order |
|---|---|
| `modifier` | Shift, Control, Alt, Meta, CapsLock, AltGraph |
| `backspace` | Backspace, Delete (told apart by `code`) |
| `whitespace` | " " (space), Tab, Enter |
| `navigation` | Arrow keys, Home, End, PageUp, PageDown |
| `bracket` | `( ) [ ] { }` |
| `letter` | single character matching `\p{L}` |
| `digit` | single character matching `\p{Nd}` |
| `symbol` | any other single printable character |
| `other` | everything else: Escape, F-keys, Dead, Unidentified, … |

This is the brief's eight categories plus `other`, so that every key has exactly one category.

### 4.7 Change-source attribution (`cause`)

Every `content_change` carries a `cause`. The client computes a hint. The server will recompute it
from the ordered log with the same rules, and **the server's value is canonical**. Disagreements
are counted and shown. **P1 stores the client hint only; server-side recomputation is part of
P3**, where the features first consume it.

| `cause` | Rule |
|---|---|
| `undo`, `redo` | Monaco `isUndoing` / `isRedoing` |
| `flush` | Monaco `isFlush` (whole-model replace). Always followed by a snapshot. |
| `paste` | a DOM `paste` event reached the editor just before the change. Monaco's `onDidPaste`, and so our `paste` event, fires **after** its content change (measured in Chromium and Firefox). |
| `cut` | follows a `cut` event in the same task |
| `drop` | follows a `drop` event |
| `ime` | ends a `composition` |
| `typed` | follows one non-modifier keydown in the same task, and either inserts at most 1 character, or is a deletion by Backspace/Delete, or is Enter/Tab inserting only whitespace (auto-indent) |
| `find_replace` | the edit came from the find widget: focus is in it, or it was used after the last editor keydown [D-027]. Replace is disabled (§4.8), so this only appears if the policy was bypassed. |
| `command` | follows a keydown with a Ctrl/Alt/Meta chord that ran an editor command: move line, copy line down, delete line, comment toggle, indent |
| `other` | reserved for a future known non-keystroke edit; not emitted today |
| `unknown` | nothing above matched |

"Untyped insertion" means characters whose cause is `paste`, `drop`, `find_replace`, `other` or
`unknown`. `command` edits are internal rearrangements and are **not** untyped insertion. This
matters for A7.

**`unknown` is a flag, not noise [D-027].** An `unknown` change with `ins_len > 0` has no
keystroke, paste or command behind it. It always counts as untyped insertion, appears as its own
marker on the reviewer timeline, and is counted per session. Events with it are never dropped as
noise. `find_replace` is treated the same way.

**Server-side reconciliation is mandatory in P3 [D-026].** The client's `cause` is a hint that
the browser owner can forge. The server recomputes the cause from the ordered log and checks every
insertion against its evidence. The server's value is canonical, and every disagreement is
counted and shown:

- An insertion of n characters labelled `typed` needs matching character-producing editor
  keydowns (auto-repeat included) since the previous change. The exception is auto-indent
  whitespace after Enter or a colon.
- An insertion labelled `paste` needs a `paste` event whose length matches.
- An insertion labelled `command` needs a Ctrl/Alt/Meta chord keydown.
- An insertion labelled `ime` needs a `composition` end.
- An insertion with no matching evidence becomes **unexplained insertion**, whatever the client's
  label says. The same goes for a large insert (§4.10) with no matching keydowns: it is flagged
  even when the client says `typed`.
- Session-wide, typed characters cannot exceed character-producing keydowns plus auto-indent
  whitespace.

This catches naive injection, such as `editor.setValue` from devtools, an extension writing into
the page, or a forged label on pasted text. It cannot catch a client rewritten to forge keydowns
and deltas consistently. Nor can it catch OS-level auto-typers (A2/A3), which produce real
keydowns; timing and process features have to catch those.

**Measured in P1** (details in [phase-reports/P1.md](phase-reports/P1.md)):

- A typed character logs `keydown → content_change → keyup` in all three browsers.
- `paste` follows its content change.
- Multi-change events arrive ordered from the end of the document to the start. The Monaco
  typings state the same, and replay applies them in that order.
- Cursor `source` values seen: `mouse`, `model`, `api`, `deleteRight`.

### 4.8 Editor policy

Monaco options live in [config/editor_policy.yaml](../config/editor_policy.yaml). The policy is
served to the client, hashed, and logged in every `segment_start`. If the client detects that the
applied options differ from the policy, it sends `client_notice {code: policy_mismatch}`.

| Feature | Setting | Why |
|---|---|---|
| Suggestions, snippets, word completion, parameter hints, tab completion | off | insert text without keystrokes |
| Inline (AI) suggestions | off | brief: no AI completion |
| Auto-closing brackets and quotes, auto-surround, overtype | never | insert text without keystrokes |
| Format on type, format on paste | off | rewrite text without keystrokes |
| Drag and drop inside the editor, drop into the editor, paste-as | off | untracked insertion |
| Context menu, command palette | off | untracked commands |
| Linked editing, code lens, lightbulb code actions | off | untracked edits |
| Auto-indent | **on**, attributed as `typed` [PROPOSED D-005] | turning it off makes Python painful and hurts ecological validity; its output is predictable whitespace after Enter |
| Line commands (move line, copy line down, comment toggle) | on, attributed as `command` | normal editing, needed for A7 |
| Find | on | read-only |
| Replace | **off** [D-027]: the replace toggle and replace row are hidden, and every replace shortcut is blocked (`blocked_keys`). A replace that still happens is logged as `find_replace`. | non-keystroke insertion |

**Stronger than switching off [D-023].** The client imports only the Monaco contributions it needs:
clipboard, find, multicursor, line operations, comment, word operations, cursor undo and bracket
matching. Suggest, snippets, inline completions, code actions, formatting, drop/paste-into, rename
and the command palette are **never loaded**, so they cannot insert text whatever the options say.

**Blocked keys [D-027].** `blocked_keys` in the policy lists key chords (code plus an exact set of
modifiers) that a capture-phase listener on the editor stops before Monaco's handlers see them.
The keydown is still logged. The list covers Monaco 0.57's replace shortcuts on Windows/Linux and
macOS: Ctrl+H or Cmd+Alt+F opens replace; Ctrl/Cmd+Shift+1 replaces one match; Ctrl/Cmd+Alt+Enter
replaces all. It also covers F1. It replaces the P1 `disabled_commands` list, which was never
applied by the client.

**Measured while fixing this (P2):** with the find widget open, Ctrl+Shift+1 and Ctrl+Alt+Enter
replaced matches even with the replace row hidden. With an empty replace string this deletes the
matches. Before D-027 these edits would have been labelled `command`, which is not untyped
insertion. An end-to-end test now checks that they change nothing.

**Measured in P1** (Monaco 0.57.0):

- Every policy option name exists, except `wordBasedSuggestions`. That one is a global option
  Monaco cannot read back, and it is moot because the suggest module isn't loaded.
- A self-check compares each option with the value Monaco computed and sends
  `client_notice {policy_mismatch}` on any difference. It needed two normalisations:
  `quickSuggestions: false` is stored as all-"off", and `autoIndent: "advanced"` as enum 3.
- In Playwright, typing `("x` inserts exactly `("x`, and no suggestion widget appears.

### 4.9 Device metadata and timer probe

Stored in `segment_start.data`. These are covariates only and are never model inputs for identity.

| Field | Source |
|---|---|
| `os_family`, `browser_family`, `browser_major` | parsed from User-Agent Client Hints or the UA string. The full UA string is **not** stored. |
| `layout`, `layout_source` | `navigator.keyboard.getLayoutMap()` where available (Chromium), otherwise self-report |
| `keyboard_type` | self-report: `laptop_builtin` \| `external` \| `other` \| `unknown` (cannot be detected) |
| `screen_w`, `screen_h`, `dpr_x100` | `screen.*`, `devicePixelRatio × 100` |
| `timer.resolution_us` | smallest positive difference of consecutive `performance.now()` readings in a 50 ms busy loop |
| `timer.cross_origin_isolated` | `self.crossOriginIsolated` |

**Measured in P1:** the user-agent OS guess is unreliable. Playwright's WebKit reports a macOS user
agent even on Windows, so `os_family` came out as `macos`. `os_family` is a covariate only, and the
device questionnaire should ask for the OS if analysis depends on it.

### 4.10 Snapshots and replay consistency

- **When [BRIEF + PROPOSED].** A snapshot is taken every `capture.snapshot_interval_ms` (10 s) if
  the model version changed; on every large insert (a single change with
  `ins_len ≥ capture.large_insert_min_chars` (32) or `≥ capture.large_insert_min_lines` (2)
  newlines, whatever its cause); on `run`; on `submit`; and at `segment_start`.
- **What.** A snapshot is the full document text, its UTF-16 length, its SHA-256 and the Monaco
  `version_id`.
- **Replay check.** The server keeps a replayed document per session by applying
  `content_change` events in order. At each snapshot it compares SHA-256 values. On mismatch it
  logs `replay_mismatch`, adopts the snapshot as the new base, and shows the mismatch on the
  dashboard. This is how dropped events or client-side tampering become visible.
- **Base document.** The first `segment_start` snapshot of a session (the starter code, never
  typed) is the replay's base and is not counted as a mismatch.
- **Reloads.** A later `segment_start` snapshot, after a reload, **is** compared, because the
  restored editor must equal the replay. P1 tests this in all three browsers.

### 4.11 Browser and library behaviour that P1 must measure, not assume

The results are in [phase-reports/P1.md](phase-reports/P1.md). Summary:

| # | Question | Result |
|---|---|---|
| 1 | Timer resolution | 100 µs (Chromium) or 1 ms (Firefox, WebKit) without COOP/COEP; 5–20 µs with it. `timeStamp` semantics with **real** keyboards are not yet measured: Playwright input is synthetic. The real-keyboard check ([keycheck.md](keycheck.md)) measures them. |
| 2 | Monaco options take effect | Yes (§4.8) |
| 3 | Event order | keydown → content_change → keyup; `paste` after its change |
| 4 | Multi-change order | end of document to start |
| 5 | `isTrusted` | Playwright input is `true` everywhere. OS-level auto-typer not measured. |
| 6 | Keyboard Map API | Chromium only |
| 7 | Beacon on reload | unload batch delivered in Chromium, Firefox and WebKit |

---

## 5. Storage (PostgreSQL)

The database library is SQLAlchemy 2 with Alembic migrations and asyncpg [PROPOSED D-010].

| Table | Contents | Notes |
|---|---|---|
| `participants` | pseudonym, created_at, consent_version, withdrawn_at, modality_exclusions, is_synthetic | **no names, emails or registration numbers** |
| `consent_records` | pseudonym, notice_version, notice_sha256, choices, given_at, withdrawn_at | append-only |
| `sessions` | session_id, pseudonym, kind, problem_id, nonce, editor_policy_sha256, created_at, closed_at, unclean_end, is_synthetic | |
| `events` | §4.3 | append-only: the app role has INSERT and SELECT only |
| `chain_checkpoints` | session_id, server_seq, head_hash, signature, signed_at | append-only |
| `scores` | session_id, tick, t_server_us, s, s_smoothed, modality_inputs, availability, model_version | |
| `cases` | case_id, session_id, opened_at, trigger, state | |
| `review_decisions` | case_id, reviewer, decision (confirm\|dismiss\|inconclusive), notes, at | append-only |
| `appeals` | case_id, pseudonym, note, at | |
| `access_log` | actor, role, action, target, at | append-only; every read of session data |
| `erasure_log` | tombstone: hash of pseudonym, requested_at, completed_at, actor | no personal data |

The identity map (real identity ↔ pseudonym) is **not** in this database (§10.5).

---

## 6. Features

Every feature is computed by one function in `ml/`, used both offline and online. Each has a unit
test on hand-built synthetic sequences with known answers.

### 6.1 Keystroke features [BRIEF]

Keystroke $i$ is a non-repeat keydown with its matched keyup. A keyup matches the most recent
unmatched keydown with the same `code`, which handles rollover. Unmatched events are dropped and
counted.

Per keystroke, the TypeNet vector is below. Checked against TypeNet §4.1: keycode ÷ 255, and the
four latencies in seconds. Pairing and latencies are implemented in
`ml/src/integrity_ml/keystroke.py`.

| Feature | Definition |
|---|---|
| keycode | normalised `code` index |
| HL (hold) | $\text{up}_i - \text{down}_i$ |
| PL (press-press, "down-to-down flight") | $\text{down}_{i+1} - \text{down}_i$ |
| IL (release-press, "up-to-down flight") | $\text{down}_{i+1} - \text{up}_i$ (negative under rollover) |
| RL (release-release) | $\text{up}_{i+1} - \text{up}_i$ |

Latencies are clipped to `features.keystroke.latency_clip_ms` on our data. TypeNet does not clip,
so the D1 reproduction doesn't either ([p2_protocol.md](p2_protocol.md) §3).

- **Windows.** $M$ = 70 keystrokes (50 as an ablation). TypeNet §6.1 reports no significant gain
  beyond M = 70. But its sequences are single sentences of about 70 characters, zero-padded, so
  its plateau may reflect sentence length rather than typing (our inference). Enrollment windows
  do not overlap. Exam windows slide with stride 35.
- **Scope.** Only `target = editor` keystrokes count. Modifier keys are included by default
  (config switch).
- **Digraph latencies** for the non-deep baseline: median PL per ordered `code` pair, and median
  HL per `code`.

### 6.2 Process features [BRIEF]

These features target the copy-type gap. They are computed over a trailing horizon
$H_{proc}$ = 120 s in the exam and over whole modules for the baseline.

| Feature | Definition |
|---|---|
| `ins_del_ratio` | typed chars inserted / (chars deleted + 1) |
| `pause_frac_200ms`, `pause_frac_2s` | fraction of inter-keydown intervals above 200 ms and above 2 s |
| `pre_burst_pause` | median pause before bursts of ≥ 40 typed chars, divided by the median intra-burst interval |
| `burst_len` | median keydowns per burst, where a burst ends at a pause > 2 s |
| `revision_rate` | Backspace/Delete keydowns per 100 typed chars |
| `short_survival` | fraction of chars typed in the horizon that were deleted within the horizon |
| `edit_locality` | median \|line distance\| between consecutive edit positions |
| `linearity` | typed chars inserted exactly at the previous insertion end (the frontier), divided by all typed chars |
| `speed_cv` | coefficient of variation of chars per 10 s bin over active bins |
| `flight_cv`, `hold_cv` | coefficient of variation of PL and HL. Near 0 for a constant-rate typer. |
| `runs_per_100` | Run/Test events per 100 typed chars |
| `edits_between_runs` | median typed chars between consecutive runs |

The process baseline $b_u$ is the mean feature vector over the participant's practice modules. The
per-feature scale $s_k$ is the pooled **within-user** SD from training users; per-user SDs from 2–3
modules are too noisy to use.

### 6.3 AST features [BRIEF]

The parser is tree-sitter with the Python grammar, pinned version, grammar hash recorded. It tolerates
syntax errors: `ERROR` nodes are counted and kept.

- **Vocabulary** $V$: all named node types from the grammar's `node-types.json`, plus `ERROR`.
- **Histogram and Laplace smoothing.** For snapshot $s$ with named-node counts $h_s$ and total $N$:
  $P_s(v) = \dfrac{h_s(v) + \alpha}{N + \alpha|V|}$. Default $\alpha$ = 0.5 [PROPOSED]. With
  $|V| \approx 100$ node types, $\alpha = 1$ would add about 100 pseudo-counts to a 200-node program,
  which is heavy. $\alpha$ is a config value and is ablated.
- **Per-problem reference.** $R_p$ is the mean of $P$ over reference final solutions to problem $p$:
  author solutions plus **training-fold users only**. Practice problems get references too.
- **Problem-normalised ("tilted") distribution.** $Q_s(v) \propto P_s(v) / R_p(v)$, renormalised to
  sum to 1. This removes what the problem dictates and keeps what the student adds.
- **Student baseline.** $B_u$ is the normalised mean of $Q$ over the practice modules.
- **Histogram drift.** $d_{ast,h} = \mathrm{JSD}_2(Q_{exam}, B_u) \in [0,1]$, using base-2 logs.
  No raw KL divergence.
- **Scalar style features.** Max control-flow nesting depth (`if/for/while/try/with/match/def/lambda`),
  mean identifier length, fraction of 1-character identifiers, and comment characters / total
  characters. Each is z-scored against the per-problem population mean and SD, then
  $d_{ast,s} = \operatorname{mean}_k |z_{exam,k} - z_{base,k}|$.
- **Availability.** AST features are computed only when the snapshot has ≥
  `features.ast.min_named_nodes` (50) named nodes.
- **AST jump** (dashboard evidence): between consecutive snapshots, ≥ 30 named nodes appear while
  < 30 keydowns were typed. In other words, structure arrived without typing.

With only 2–3 practice problems, $B_u$ is noisy. That is why AST drift is a weak, fusion-only
signal.

### 6.4 Clipboard features [BRIEF]

- **Paste provenance** (server-computed). A paste is `internal` if its normalised SHA-256 matches a
  `copy`/`cut` earlier in the same session with `source = editor`. It is `problem_statement` if it
  matches a `copy` from the problem panel. Otherwise it is `external`.
- **Features over the horizon and cumulatively:**
  - paste count and volume,
  - external paste volume,
  - paste-to-typed ratio,
  - inter-paste intervals,
  - total and maximum focus-loss duration,
  - focus-loss→paste coupling: an external paste within 10 s after the editor regains focus,
  - untyped-insertion fraction (§4.7).

---

## 7. Models

### 7.1 Keystroke encoder [BRIEF]

- **Architecture.** A TypeNet-style Siamese network. Input is $M \times 5$ per window. Masking →
  batch norm → LSTM(128) → batch norm + dropout 0.5 → LSTM(128), whose final state is the 128-d
  embedding. The paper also uses recurrent dropout 0.2. Training uses triplet loss on squared
  distances, margin 1.5, random triplets, Adam with learning rate 0.05, and 200 epochs of 150
  batches of 512. All of this is checked against TypeNet §4.2–4.4. The layer order is confirmed by
  the paper's 200,458-parameter count. Values are in `config/models.yaml`; deviations are in
  [p2_protocol.md](p2_protocol.md) §9.
- **Pretraining.** Aalto 136M-keystroke desktop dataset. **Blocked until the lead confirms the
  licence and downloads it.** Pretraining can be subsampled if the RTX 3050 (6 GB) budget requires
  it; any subsampling is reported.
- **Fine-tuning.** On collected code-typing data, training-fold users only.
- **Distance.** Euclidean between embeddings.

### 7.2 Non-deep baseline [BRIEF]

The digraph profile from enrollment keeps pairs with ≥ `models.digraph.min_occurrences` (3). The
distance to a test window is the mean absolute difference of median PL over shared digraphs plus
the same for per-key HL (Manhattan, divided by the number of shared items). If fewer than 5 items
are shared, the baseline is unavailable.

### 7.3 Enrollment [BRIEF]

- **Prototype.** $c_u = \frac{1}{G}\sum_{g=1}^{G} f(w_g)$, the mean embedding over $G$ enrollment
  windows from the practice modules.
- **Distance.** $d_{ks}(w) = \lVert f(w) - c_u \rVert_2$.
- **[OPEN, P2 question 2]** TypeNet scores differently: it averages the distances to each
  enrollment embedding, $\frac{1}{G}\sum_g \lVert f(w) - f(w_g) \rVert$ (Eq. 5). The P2
  reproduction uses Eq. 5. For our data, the proposal is to pre-register both rules, with Eq. 5
  primary.
- **Report.** EER against $G \in \{1, 3, 5, 10\}$ for both the encoder and the digraph baseline.
- **Minimum.** The keystroke modality is unavailable for a participant with fewer than
  `models.enrollment.g_min` (5) valid enrollment windows.

### 7.4 Fusion [BRIEF]

- **Inputs.** Seven scalars, all oriented so that **higher = more anomalous**, standardised with
  training-fold statistics:

| $x_j$ | Modality |
|---|---|
| $d_{ks}$ | keystroke |
| $d_{proc} = \sqrt{\tfrac{1}{K}\sum_k \big((p_k - b_{u,k})/s_k\big)^2}$ | process |
| $d_{ast,h}$, $d_{ast,s}$ | AST |
| external-paste fraction, $\log(1 + \text{external paste chars})$, focus-loss fraction | clipboard |

  Two availability indicators are added, one for keystroke and one for AST. A missing input is
  imputed with the **genuine** training median, which counts as neutral evidence.
- **Model.** L2 logistic regression; $C$ is chosen by inner cross-validation. An MLP is added only
  if a pre-registered, cross-validated ablation shows a gain whose 95% CI excludes 0. With 30–50
  users an MLP will overfit.
- **Sign constraint (implemented: `ml/src/integrity_ml/fusion.py`).** Distance weights are
  **constrained** $w_j \le 0$ during fitting (L-BFGS-B with bounds), not just checked afterwards,
  because high $S$ means genuine. Standardisation divides by a positive scale, so the constraint
  carries over to raw inputs. Availability indicators and the intercept are unconstrained. The
  objective equals scikit-learn's L2 logistic regression, and the fit matches it when no bound is
  active.
- **Tests (`ml/tests/test_fusion.py`):**
  - on data where an unconstrained fit gives a distance feature a positive weight, the constrained
    weight sits at exactly 0;
  - no distance weight is positive over 20 random synthetic datasets;
  - raising any distance input never raises $S$;
  - the fit matches scikit-learn when the bounds are inactive.
- **Guard.** `assert_weight_signs` runs on every trained artifact.
- **Weights pinned at 0.** A distance weight stuck at the bound means the data disagreed with the
  orientation. Training logs it, and the report names it.

---

## 8. The integrity score $S$ and decision states

### 8.1 Scoring ticks

A tick fires on any of:

- every 35 new keydowns once a 70-keystroke window exists,
- every `paste`, `cut`, `drop` or large insert,
- every snapshot that changes the AST,
- and at least every 30 s while the session is active.

At each tick, every modality input is recomputed on its trailing horizon. The keystroke input uses
the most recent full window if that window ended within 120 s; otherwise it counts as unavailable.

### 8.2 Score

$$
S(t) = \sigma\Big(b + \sum_{j} w_j\, x_j(t) + \sum_m v_m\, a_m(t)\Big), \qquad S \in (0,1),\ \text{high = genuine}
$$

where $a_m$ are the availability indicators.

### 8.3 Smoothing and session score [PROPOSED D-007]

- **Smoothing.** An EWMA on the logit: $\tilde\ell_k = \lambda\,\mathrm{logit}\,S(t_k) + (1-\lambda)\,\tilde\ell_{k-1}$,
  with $\lambda$ = 0.5, and $\tilde S = \sigma(\tilde\ell)$.
- **Session score.** $S_{session} = \min_k \tilde S(t_k)$. A session is flagged if its smoothed
  score **ever** crosses the threshold, so the live rule and the session rule are the same rule,
  and time-to-detection is simply the first crossing.
- **Known weakness.** Long sessions get more chances to cross. P5 reports false-flag rate against
  session length.

**How smoothing affects time-to-detection** (implemented and tested in
`ml/src/integrity_ml/smoothing.py`):

Time-to-detection is the sum of two parts:

$$
\text{TTD} = T_{evidence} + T_{smoothing}
$$

- **$T_{evidence}$:** the time until raw ticks reflect the attack. It does not depend on
  smoothing.
  - A paste triggers a tick immediately.
  - A keystroke window is only fully post-onset after 70 keystrokes following the onset. Until then
    it mixes pre-onset and post-onset typing.
- **$T_{smoothing}$:** extra ticks caused by the EWMA. Suppose the smoothed logit is $\ell_0 > \theta$
  at onset ($\theta = \mathrm{logit}\,\tau$) and the attack holds the raw logit at $\ell_1 < \theta$.
  Then the first crossing happens after

$$
k^* = \left\lfloor \frac{\ln r}{\ln(1-\lambda)} \right\rfloor + 1 \ \text{ticks}, \qquad r = \frac{\theta - \ell_1}{\ell_0 - \ell_1}
$$

  and $T_{smoothing}$ is the $k^* - 1$ ticks beyond the first.
  - With $\lambda = 1$ (no smoothing), $k^* = 1$.
  - If $\ell_1 \ge \theta$ the attack is never detected, whatever $\lambda$ is.

What this means in practice:

- **Strong evidence costs nothing.** A single tick crosses when
  $\ell_1 < (\theta - (1-\lambda)\ell_0)/\lambda$. With $\lambda = 0.5$ that means twice as far
  below $\theta$ as the score was above it. A large external paste (A1) should clear this, so it
  costs no extra ticks.
- **Weak, sustained evidence costs a few ticks.** Worked example: $\lambda = 0.5$, the score sits 2
  logits above threshold, and the attack holds it 0.5 below. Then $k^* = 3$, which is 2 extra ticks.
  At 35 keystrokes per tick that is roughly 70 extra keystrokes, which is 30–60 s at typical coding
  speeds. Copy-type (A4) and edited LLM code (A5) are expected to look like this.
- **Whole-session attacks pay nothing.** The EWMA starts at the first score, so an attack that
  starts before the first tick has no smoothing delay.
- **Smoothing also cuts false flags.** A one-tick dip must be deeper to cross, so genuine sessions
  cross less often. $\tau$ is recalibrated for each $\lambda$ on validation data, so the trade is
  "fewer false flags for a later detection". P5 reports detection rate, time-to-detection and
  false-flag rate for $\lambda \in \{1, 0.5, 0.3\}$, each at its own validation-calibrated $\tau$.

### 8.4 States [BRIEF]

The rules are evaluated in this order:

1. **review** if $S_{session} < \tau$. Anomaly evidence overrides missing data, so a paste-only
   session is **not** "insufficient".
2. **insufficient_data** if coverage is below minimum: the keystroke or process modality was
   unavailable for more than 50% of ticks, or enrollment is incomplete.
3. **auto_accept** otherwise, meaning "not routed to review".

Nothing is auto-actioned in any state. "Insufficient data" is not a pass. It is shown to the
reviewer as its own queue.

### 8.5 Thresholds and calibration [BRIEF]

- **Threshold.** $\tau$ is set on **validation** genuine sessions so that 5% of them are flagged
  (`scoring.target_false_flag_rate`). It is never set on test users.
- **Prior-independence.** $\tau$ is defined by the genuine false-flag rate, so it does not depend
  on how common cheating is.
- **What $S$ is.** $S$ is $P(\text{genuine}\mid x)$ under the **study's** mix of genuine and attack
  sessions. It is not calibrated to real exam base rates. Reports say so.
- **Calibration reports.** Reliability diagram (10 bins), ECE and Brier score for window-level $S$,
  on validation and test.

### 8.6 Compute budget

- Per tick: one LSTM forward pass over 70 steps, $O(M)$ feature updates, and one tree-sitter parse
  of the current snapshot.
- No DTW and no method quadratic in session length.
- Target: under 50 ms per tick on CPU. Measured in P3.

---

## 9. Threat model

### 9.1 Assets

- Validity of the integrity signal.
- Participants' personal data.
- Fairness to honest students: false flags are a harm.

### 9.2 Trust assumptions

- The server and database host are trusted.
- The signing key is held separately from database credentials.
- The client and the network before TLS termination are **untrusted**. The browser owner (the
  student) controls the client and can forge any telemetry it sends, including `isTrusted`, change
  causes, timings and run results [D-026].
- Reviewers are trusted but audited.

### 9.3 Attack catalogue and expected signals

"Expected" is a hypothesis to test, not a result.

| ID | Attack | Keystroke identity | Process | AST drift | Clipboard | Honest expectation |
|---|---|---|---|---|---|---|
| A1 | plain paste of external code | n/a (no keys) | untyped insertion | weak | **strong** (external paste) | should be caught |
| A2 | constant-rate auto-typer | **strong** | **strong** (`flight_cv ≈ 0`) | weak | none | should be caught |
| A3a | auto-typer, jitter sampled from a population histogram | moderate | moderate (no revisions, high linearity) | weak | none | uncertain |
| A3b | auto-typer, jitter sampled from **this student's own** enrollment timing | weak | moderate | weak | none | partial evasion likely; digraph-conditioned sampling would evade more |
| A4 | copy-type from a second screen | weak or none: it is the student's own hands | the main hope: linearity, low revision, pause structure | weak | none | expect weak to moderate; reported as found |
| A5 | LLM code, then hand edits, renames, refactor | weak | moderate if pasted, weak if typed | weak (humanised) | strong if pasted, none if typed | hardest case; expect low detection |
| A6 | strong student, clean idiomatic code (genuine) | – | – | false-flag risk | – | false-positive test |
| A7 | legitimate refactor and block moves (genuine) | – | false-flag risk | false-flag risk | internal paste, must not count | false-positive test |
| A8 | keyboard or device change since enrollment (genuine) | **false-flag risk** | small | none | none | false-positive test; mitigation: re-enroll, device covariate |

### 9.4 Other adversaries

| Adversary | Coverage |
|---|---|
| Impersonation (another person types the exam) | This is where keystroke identity is strongest. |
| Enrollment impersonation (someone else does the practice modules) | Not detectable by design. The baseline must be collected under supervision or with low stakes. Stated as a limitation. |
| Client tampering by the browser owner: modified JS, forged or replayed telemetry, devtools injection, extensions writing into the page [D-026] | Forged telemetry cannot be detected from its content alone. **`isTrusted` is not a defence.** The hash chain covers only what happens after the data reaches the server. What raises the cost: **mandatory P3 server-side reconciliation** of content deltas against keydowns (§4.7), where an unexplained insertion is flagged whatever the client's label says; replay consistency against snapshots (§4.10); and the editor policy's blocked keys (§4.8). A client rewritten to forge keydowns and deltas consistently still evades all of these. |
| Insider misuse of data | Least privilege, pseudonyms only, access log, erasure. |

### 9.5 Out of scope for v1

- Webcam or second-device detection.
- VM or remote-desktop detection.
- Browser lockdown.
- Hardware keystroke injectors (treated as A2/A3).
- Collusion by sharing screens.

---

## 10. Privacy and ethics design

### 10.1 Legal frame [VERIFY: not legal advice; to be checked against the notified texts with the faculty guide]

The India Digital Personal Data Protection Act 2023 and the DPDP Rules 2025. The design points we
rely on:

- A notice that itemises the personal data and purposes.
- Consent that is free, specific, informed, unconditional and unambiguous, and as easy to withdraw
  as to give.
- Reasonable security safeguards, including encryption, access control and logs.
- Erasure once the purpose is served or consent is withdrawn.
- Breach intimation.
- **For children (under 18): verifiable parental consent, and a prohibition on behavioural
  monitoring.** Our design therefore **admits only participants aged 18 or over.**

Exact section and rule numbers are to be verified before the consent notice is finalised.

### 10.2 Roles

| Role | Who |
|---|---|
| Data Fiduciary | the project under VIT, via the faculty guide **[OPEN: confirm]** |
| Data Principals | participants |
| Processors | none: self-hosted, with no third-party analytics, CDNs or cloud APIs on the data path |

### 10.3 Notice and consent

The consent screen and a downloadable notice state:

- **Purposes.** Research evaluation of an integrity-scoring prototype. Not used for any grade or
  academic decision.
- **Data categories:** §10.4. This includes that recorded timing may be used to **simulate
  automated-typing attacks** against the system (A3b).
- **Retention period.** **[OPEN]**
- **How to withdraw.** A withdraw button in the app, plus a contact address. Effect: collection
  stops and data is erased (§10.7).
- **Contacts and grievance route**, including the Data Protection Board complaint route.
- **Known false-flag causes** (§10.8).

Consent is split into separate choices:

1. Participation and data collection (required).
2. Simulated-misconduct tasks (optional).
3. Use of anonymised aggregates in reports, the paper and patent-support documents (optional).
4. Retention for future research (optional, **default off**).

Further requirements:

- The participant confirms they are 18 or older.
- Recruitment must not be done by anyone who grades the participant.
- Taking part or refusing has no academic effect.

### 10.4 Data inventory

| Collected | Not collected |
|---|---|
| Keystroke timing, `code` and category **inside the editor only** | `KeyboardEvent.key` values; anything typed outside the editor |
| Code content: deltas and snapshots | Mouse movement, webcam, microphone, screen |
| Clipboard *events*; pasted text (it becomes editor content); a SHA-256 of copied text | Copied text itself; the clipboard outside paste events |
| Focus and visibility events | Browsing history, other tabs' content |
| Device covariates (§4.9) | Full UA string, IP address in the event log, fingerprinting |
| Run and test outcomes | Grades |
| Pseudonym, consent record | Name, email, registration number (identity map only, §10.5) |

The keystroke log together with the code deltas shows what was typed *in the editor*. That is the
same information as the code itself, and it is disclosed in the notice.

### 10.5 Pseudonymisation

- Pseudonyms are random: `P-` + 8 base32 characters.
- The identity map (identity ↔ pseudonym) is held **offline** by one named custodian, never one
  of the three students **[OPEN Q4: faculty guide to name]**. It is never in the app database,
  repository or reviewer tools.
- Reviewers see pseudonyms only.
- The participant keeps their pseudonym on the consent receipt, for withdrawal and appeals.

### 10.6 Security

- **At rest [DECIDED Q1].** Application-level AES-256-GCM on `events.data` (P1), and later on
  snapshots, review notes and appeal notes. The associated data is `session_id‖server_seq`, so a
  ciphertext cannot be moved to another row undetected. The database lives in a Docker named
  volume, not in the repository.
- **Where the field key is today [OPEN, D-028].** `data_key.bin` (32 random bytes from
  `scripts/make_secrets.py`) sits in `C:\dev\integrity-exam\secrets\`. That is **inside the
  repository folder**. It is git-ignored and has never been committed (only `secrets/README.md` is
  tracked). The folder is not under OneDrive (`C:\Users\…\OneDrive`), but it is still in the repo.
  **There is no backup.** If the file is lost, every encrypted event payload becomes unreadable.
  Today that affects only DEV and SYN data. The requirement is that the key is in neither the repo
  nor a synced folder. The proposed fix: move `secrets/` to a folder outside the repo and outside
  sync; point `INTEGRITY_SECRETS_DIR` at it (the backend already reads this variable); make the
  backend refuse a secrets folder inside the repo or a sync root, as it already does for the data
  root; and keep one offline encrypted backup held by a named person. This waits for the lead's
  decision.
- **Data root [DECIDED Q1].** Exported datasets and files live under `INTEGRITY_DATA_ROOT`, outside
  the repository, and are written encrypted. The disk should also be encrypted (BitLocker or Device
  Encryption). As of P0 this machine's disk-encryption status is **unknown**: the check needs admin
  rights.
- **In transit.** TLS (`wss://`, `https://`) outside localhost development.
- **Roles.** `participant`, `reviewer`, `researcher` (pseudonymised aggregates only), `admin`.
- **Least privilege.** The app database role cannot UPDATE or DELETE `events`.
- **Access log.** Every read of a session's events, replay, scores or notes is written to
  `access_log` (actor, role, action, target, time). Admins can view it.
- **Cloud sync.** Data directories MUST NOT be inside a cloud-synced folder or inside the repository.
  The backend refuses to start if the data root is under a known sync root (OneDrive, Dropbox,
  Google Drive, iCloud) or inside the repository.

### 10.7 Retention and erasure

- **Retention job.** Raw logs are deleted N days after project end, with N set by the faculty guide
  **[OPEN Q4]**. A job purges them on that date. Derived pseudonymised features follow the second
  retention answer in the governance one-pager.
- **Erasure endpoint.** `DELETE /api/participants/{pseudonym}`, callable by the participant (with
  their token) or by an admin (with a request id). It deletes events, snapshots, features, scores,
  cases, notes, appeals and consent choices, and writes an `erasure_log` tombstone with no personal
  data. The custodian then deletes the identity-map entry.
- **Trained models.** Models trained before a withdrawal may keep statistical influence. Results
  for publication are recomputed after withdrawals, and the notice says so.

### 10.8 False-flag disclosure

Shown on the consent screen, the dashboard and in every report:

> Accessibility needs and assistive technology, injury, fatigue, mood and stress, a different
> keyboard or device, input methods and simple unfamiliarity can all change how someone types and
> cause false flags. A flag only means "a human should look". It is not evidence of misconduct.

### 10.9 Accommodation path

- **Request.** Requests go through a human channel outside the system: the faculty guide or the
  disability office. The system never records the reason.
- **What the system stores.** Only `modality_exclusions`, for example `["keystroke"]`. The same flag
  is used for non-disability reasons (device failure, injury, participant preference), so the flag
  reveals nothing about disability.
- **Model behaviour.** An excluded modality is treated as unavailable. The model never tries to
  infer health, disability or emotion.
- **Dashboard.** Shows "keystroke modality excluded (reason not recorded)".

### 10.10 Reviewers and appeals

- Reviewers must record a decision (`confirm`, `dismiss`, `inconclusive`) with notes.
- Reviewers see the §10.8 text on every case.
- Participants can view their own case evidence and attach appeal notes.
- In this research prototype, decisions have **no academic consequence**.

### 10.11 Synthetic data rules [BRIEF]

- Synthetic participants use the `SYN-` prefix and have `is_synthetic = true`. Synthetic segments
  have `segment_start.synthetic = true`.
- Synthetic files have `synthetic` in the filename.
- Report code refuses to mix synthetic and real data, and every figure from synthetic data is
  watermarked **SYNTHETIC**.
- Synthetic data is used only for pipeline tests and is never reported as a result.

---

## 11. Reviewer dashboard (P4)

- **Session timeline.** $\tilde S(t)$ with the threshold. Markers for pastes (coloured by
  provenance), large inserts, AST jumps, pauses > 2 s, focus losses, runs, `replay_mismatch` and
  `unclean_end`. Also markers for `unknown` and `find_replace` insertions, and for the server's
  **unexplained insertions** and client/server cause disagreements (§4.7), each with a
  per-session count.
- **Per-tick evidence.** Clicking a tick shows each modality's contribution ($w_j x_j$), so the
  reviewer sees *why*.
- **Replay scrubber.** Code state at any `server_seq`, replayed from deltas and checked against
  snapshots.
- **Decision panel.** Confirm, dismiss or inconclusive, with required notes. The appeal thread.
  The chain verification status.
- **Audit log view** (admin).
- Every dashboard read is access-logged.

---

## 12. Evaluation plan

### 12.1 Datasets

| ID | Data | Use |
|---|---|---|
| D1 | Aalto 136M keystrokes, desktop (Dhakal et al.): 15 memorised sentences per subject, typed in a browser with ms timing (TypeNet §3). **[Licence requested by the lead; redistribution and patent-relevant terms to be checked by the lead]** | encoder pretraining; P2 TypeNet reproduction ([p2_protocol.md](p2_protocol.md)) |
| D1b | *Optional:* TypeNet Benchmark, the authors' triplet embeddings (M = 50) for the 100,000 desktop test subjects, under a separate BiDA Lab licence. Not requested. | checks our EER code against the authors' own embeddings (P2 question 4) |
| D2 | Our collection: recruit 50+ consenting adult students so that 30–50 complete both sittings; code-typing, with study conditions | fine-tuning, fusion, calibration, evaluation |
| D3 | **Synthetic**, labelled | pipeline tests only; never reported as results |

### 12.2 Study protocol [DECIDED Q3, with changes]

- **Ethics gate.** No real collection before institutional ethics approval and the P5 ethics and
  consent checklist.
- **Recruitment.** 50+ participants, allowing for 20–30% dropout between sittings.
- **Browsers [DECIDED D-025].** Chromium-based (Chrome or Edge) or Firefox. Safari is out of
  scope. Each participant uses **the same browser in both sittings**. Browser brand and version are
  logged as covariates; `browser_family`/`browser_major` are logged today, and brand, which tells
  Edge from Chrome, is added in P5.
- **Cross-origin isolation [DECIDED D-021].** The same setting (isolated) for every enrollment and
  exam session.
- **Sitting 1 (~40 min).**
  1. Consent, then the device questionnaire.
  2. Three practice modules. Each has (a) about 2 min of transcribing given code, which gives
     digraph coverage **and the student's own transcription-mode profile**, and (b) about 8 min of
     free coding.
  3. Expected yield: about 1000+ keystrokes per module, so 5–10 baseline windows are easy to reach.
- **Sitting 2 (≥ 1 day later, ~60 min).** Short exam tasks, each under one condition. Order is
  counterbalanced (Latin square). Conditions: genuine ×2, A1, A4, A5, A7. A subset of participants
  does one genuine task on a different keyboard (A8).
  - Separate sittings matter: enrollment and exam in the same sitting would overstate keystroke
    identity performance, because typing varies across sessions.
- **Scripted attacks.** A2 and A3a/b are generated by scripts in `eval/`, driving real browser input
  on the participants' exam task texts. A3b uses the participant's own enrollment timing, as
  consented in §10.3.
- **LLM code.** A4 and A5 use LLM solutions **generated before collection and frozen**, stored with
  model name, version, date and prompt, and labelled `llm_generated`.
- **Live-LLM subset.** 8–10 participants additionally do A5 with a live LLM of their choice. They
  record the model, prompts and outputs. Their sessions are labelled `A5_live` and reported
  separately from frozen-output A5. This subset is small, so its results are descriptive only.
- **Onset.** Condition labels and attack onset times are recorded by the study tooling and never
  reach the scoring path.
- **Role-play.** Participants are told that attack conditions are role-play with no consequences.

The transcription-mode profile is a hypothesis: it may help separate *this student's*
composition from *this student's* transcription (A4). It is tested, not assumed.

### 12.3 Splits and leakage rules [DECIDED Q5]

- **Scheme.** User-disjoint nested cross-validation: 5 outer folds, and inside each training fold an
  inner split into train and validation users.
- **Order of work per outer fold.**
  1. Fine-tune the encoder on inner-train users.
  2. Fit fusion on inner-train users.
  3. Pick $C$ and $\tau$ on inner-validation users.
  4. Apply once to the outer-test users.
- **Pooling.** Outer-test predictions are pooled, so every participant is scored by a model that
  never saw them.
- **Frozen before test.** Per-problem AST references and process scales come from training users
  only. Hyperparameters, features and the fusion form are frozen in this spec and `config/` before
  any test run.
- **Test-access ledger.** Every computation on outer-test users appends a line to
  `eval/ledger/test_access.jsonl` (time, git commit, config hash, purpose). Reports print the ledger.
  More than one "final" entry has to be explained.

With 30–50 users, a single fixed 60/20/20 split would leave 6–10 test users. Nested CV uses every
user for testing without leakage.

### 12.4 Metrics [BRIEF]

| Metric | Definition |
|---|---|
| Detection rate per attack | Session-level TPR at the threshold that gives a 5% false-flag rate on validation genuine sessions. The realised test false-flag rate is always reported next to it. |
| Per-user results | Table of participant × condition: detected (y/n), $S_{session}$, time-to-detection |
| Time-to-detection | From attack onset to the first crossing of $\tilde S < \tau$, in seconds and in keystrokes. Missed attacks are censored and reported as "not detected", never dropped. |
| Keystroke EER | Against $G \in \{1,3,5,10\}$, encoder vs digraph baseline, on D1 and D2, with DET curves |
| Ablations | Each modality alone; leave-one-modality-out; fused; LR vs MLP |
| Calibration | Reliability diagram, ECE, Brier (§8.5) |
| False flags by covariate | Keyboard type, OS, self-reported touch typing, session length. Descriptive only: N is small. |

### 12.5 Statistics

- **Bootstrap [DECIDED Q5].** 95% CIs by cluster bootstrap over **users**. Each resample draws
  users with replacement and brings all of that user's sessions and windows with them; sessions
  are never resampled independently. 10,000 resamples, seeded, percentile method.
- **What the CIs mean.** They cover sampling of test users for a fixed trained model. Training
  variance is shown separately by repeating nested CV with 3 seeds.
- **Pre-registered primary endpoints.**
  1. Fused detection rate per attack at 5% false-flag rate.
  2. Fused vs best single modality, as a paired bootstrap difference.
- Everything else is secondary.
- **Expected precision.** With about 40 users, a detection-rate CI is roughly ±15 percentage points,
  and a 5% false-flag rate on about 80 genuine sessions means about 4 sessions. Reports state this
  plainly.

### 12.6 Reporting rules

- Report every attack, including the ones we fail on (expected: A4, A5, A3b).
- No tuning after the test ledger's first "final" entry, unless the change is logged and the result
  labelled post hoc.
- Every result table names its dataset, fold scheme, git commit and config hash.

### 12.7 P2 reproduction protocol

- **Before any training [DECIDED Q5].** Write `docs/p2_protocol.md` with the exact protocol, each
  item quoted from the paper with its section or table number. Anything the paper does not state
  is marked "not stated" and our choice is recorded. Required items:
  1. Dataset subset (desktop), filtering of users and sessions, and the train/test user counts and
     how test users were selected.
  2. Sequence length $M$, sequences per user, handling of shorter sequences, and padding or
     masking.
  3. Per-keystroke features, their units, normalisation and clipping.
  4. Architecture: layers, units, dropout, batch norm, embedding size.
  5. Loss (triplet), margin, triplet selection, optimiser, learning rate, batch size, epochs and
     stopping rule.
  6. Enrollment: $G$ values, the scoring rule (distance to each enrollment sample averaged, or to a
     prototype), and the impostor set used for EER.
  7. EER computation: per-user thresholds or a global threshold, and how results are averaged.
  8. The published EER table we compare against.
- **Our deviations.** Listed item by item (for example a smaller training set on a 6 GB GPU),
  each with its expected effect.
- **Acceptance [DECIDED Q5].** Our EER at each $G$ is within max(1 percentage point absolute, 50%
  relative) of the published value under the same protocol, or a written gap analysis explains the
  difference.
- **Status.** Written: [p2_protocol.md](p2_protocol.md) v0.1 (all 8 items, the deviations and the
  acceptance bands). It awaits the lead's review. No training has started.

---

## 13. Phases and acceptance

| Phase | Deliverable | Acceptance |
|---|---|---|
| P0 | Repo skeleton, this spec, decisions log | Lead approves the spec; skeleton tests pass |
| P1 | Capture app, server log, replay | All §4.5 events captured. Ordering tests: duplicate, out-of-order and reconnect/resend give gapless `server_seq` in `client_seq` order. Hash-chain tests (plain chain, no signatures): every single-field edit, insert, delete and reorder is detected, and close returns the head hash. Data-root guard and field encryption tested. Replay equals every snapshot (non-BMP text, undo/redo, multi-cursor). Playwright end-to-end: consent → practice → type → paste → submit → replay matches. §4.11 measurements reported. |
| P2 | Protocol write-up (approved before training); keystroke features; non-deep baseline (first on labelled synthetic data, then on D1); TypeNet-style encoder on D1; real-keyboard check | EER reproduced per §12.7, or the gap explained. The baseline is reported under the same protocol. The real-keyboard check report is reviewed (development data only). |
| P3 | Enrollment, process, AST and clipboard features, fusion, thresholds, **server-side cause reconciliation** [D-026] | Every feature unit-tested; weight-sign guard passes; ticks under 50 ms; calibration curves on synthetic (labelled) and, once available, validation data. Reconciliation tests: a forged batch whose large insert is labelled `typed` with no keydowns is flagged as unexplained insertion; a `paste` label with no paste event is flagged; genuine typing, auto-indent, line commands and pastes produce no flags; client/server disagreements are counted. |
| P4 | Dashboard and reviewer workflow | Timeline, replay, decisions, appeals, access log. Playwright tests. Every read is logged. |
| P5 | Ethics checklist (approved **before** any real collection), collection tooling, evaluation harness, attack report | §12 complete. Report per attack with CIs and time-to-detection. Ablations. The collection tooling serves the app cross-origin isolated and refuses a real session that isn't; it logs browser brand and version, refuses a second sitting in a different browser (D-021, D-025), and refuses any file labelled `dataset: development`. |
| P6 | Paper and patent-support documents | Honest claims, novelty statement, limitations, and every citation verified or flagged |

Every phase ends with: what works, what is weak, and what the lead should decide next.

---

## 14. Configuration and reproducibility

- All tunables are in `config/*.yaml`. Code reads config and never hard-codes thresholds.
- Seeds: `config/global.yaml: seed`, applied to `random`, `numpy` and `torch`, with CUDA
  determinism flags where available.
- Every trained artifact and every report embeds a **run manifest**: git commit, dirty flag, config
  SHA-256, seed, dataset IDs and the synthetic flag.
- Python 3.11, type hints everywhere, `pytest` per package, `ruff` and `mypy --strict` [PROPOSED].
  The frontend uses TypeScript strict mode and Playwright.

---

## 15. Open decisions

See [DECISIONS.md](DECISIONS.md) for the full log.

| Question | Status |
|---|---|
| Q1: repo and data location, Python | **Decided.** Repo in `C:\dev\integrity-exam`; data root outside the repo and encrypted; Python 3.11 pinned. |
| Q2: where Run/Test executes | **Decided.** Pyodide in a Web Worker, Python only; results are client-reported and forgeable (§1.4). |
| Q3: study protocol | **Decided with changes.** 50+ recruited; live-LLM A5 subset of 8–10; role-play and transcription-awareness limitations (§1.4); ethics approval before collection. |
| Q4: data governance | **Open.** With the faculty guide via the governance one-pager: retention N, identity-map custodian, named responsible party, reviewers outside the team. |
| Q5: evaluation | **Decided with changes.** Nested user-level CV; cluster bootstrap over users; exact TypeNet protocol documented before P2 training (§12.7). |
| P1 review | **Decided.** COOP/COEP by default, the same for all sessions, no accuracy claim (D-021). Chromium and Firefox only, same browser both sittings (D-025). Threat-model additions and mandatory P3 reconciliation (D-026). Replace disabled, `unknown` is a flag (D-027). Aalto licence requested by the lead. |
| Field-key location and backup | **Open (D-028).** The key is inside the repo folder with no backup (§10.6). |
| P2 modelling questions | **Open.** Four questions in [p2_protocol.md](p2_protocol.md) §12. |

---

## 16. References [VERIFY in P6 unless marked checked]

Reference 1 was checked against its arXiv text in P2. The others have not been checked against
the source yet; numbers attributed to them come from the project brief.

1. A. Acien, A. Morales, J. V. Monaco, R. Vera-Rodriguez, J. Fierrez. "TypeNet: Deep Learning
   Keystroke Biometrics." *IEEE Transactions on Biometrics, Behavior, and Identity Science*.
   **Checked (2026-09-26) against arXiv:2101.05570v3**: the EERs (Table 2), the M = 70 plateau
   (§6.1), the architecture (§4.2) and the training and evaluation protocol (§4.4, §5.1); details
   in [p2_protocol.md](p2_protocol.md). **[VERIFY]** the published version: arXiv says "T-BIOM,
   2021"; the authors' README says vol. 4, pp. 57–70, 2022. The IJCB 2020 preliminary version is
   arXiv:2004.03627.
2. V. Dhakal, A. M. Feit, P. O. Kristensson, A. Oulasvirta. "Observations on Typing from 136
   Million Keystrokes." *CHI 2018.* **[VERIFY; dataset licence requested by the lead]** Check
   especially whether each subject's 15 sentences were typed in one sitting
   ([p2_protocol.md](p2_protocol.md) §0.1).
3. Digital Personal Data Protection Act, 2023 (India). **[VERIFY sections]**
4. Digital Personal Data Protection Rules, 2025 (India). **[VERIFY rule numbers and dates]**
5. Tree-sitter and tree-sitter-python (software). Monaco Editor (software). Versions pinned in the
   lockfiles.
6. **[NEEDS SOURCE]** The claim that population AI-code detectors fail across domains and under
   humanising. P6 must find verified sources or drop the claim.
