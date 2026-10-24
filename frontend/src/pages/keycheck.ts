// Real-keyboard check (the lead's P1 decision 4; docs/keycheck.md). DEVELOPMENT DATA ONLY.
// Records keydown/keyup timing while a team member types a few fixed tasks, then saves it as a file
// from this browser. Nothing is sent to the server, and the file is never part of a study dataset.

import { detectBrowserVersion, detectLayout, probeTimerResolutionUs } from "../capture/device";
import { modifierMask, safeCode } from "../capture/keys";
import { h } from "../dom";
import { createEditor, type EditorPolicy } from "../editor";

export const KEYCHECK_FORMAT = "keycheck.v1";

// During the "jank" task the page blocks its own main thread for JANK_BLOCK_MS every
// JANK_PERIOD_MS. Keys pressed during a block are dispatched after it ends. If event.timeStamp is
// the OS input time, their timeStamp falls inside the block; if it is the dispatch time, it doesn't.
const JANK_BLOCK_MS = 80;
const JANK_PERIOD_MS = 250;

// Only options that change what the typist sees. Key events do not depend on editor options.
const POLICY: EditorPolicy = {
  policy_id: "keycheck",
  monaco_options: { autoClosingBrackets: "never", autoClosingQuotes: "never", autoSurround: "never", autoIndent: "advanced" },
  blocked_keys: [],
  sha256: "",
};

const PROSE =
  "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. " +
  "Sphinx of black quartz, judge my vow. How vexingly quick daft zebras jump!";
const CODE = [
  "def count_words(text: str) -> dict[str, int]:",
  "    counts = {}",
  "    for word in text.lower().split():",
  "        counts[word] = counts.get(word, 0) + 1",
  "    return counts",
].join("\n");

type TaskId = "prose" | "code" | "hold" | "jank";

const TASKS: Array<{ id: TaskId; title: string; steps: string; text?: string }> = [
  { id: "prose", title: "1. Prose", steps: "Type this passage at your normal speed. Fix typos the way you normally would.", text: PROSE },
  {
    id: "code", title: "2. Code",
    steps: "Type this code. The editor indents after a colon, as in the study. Press Backspace to dedent before return.",
    text: CODE,
  },
  { id: "hold", title: "3. Held keys", steps: "Hold A for about two seconds, then release. Then hold Backspace for about two seconds, then release." },
  {
    id: "jank", title: "4. Typing while the page stalls",
    steps: "Type the prose passage again. The page now freezes for a moment several times a second, so text may appear in bursts. Keep typing normally.",
    text: PROSE,
  },
];

interface KeyRecord {
  task: TaskId;
  type: "keydown" | "keyup";
  code: string;
  rep: boolean;
  mods: number;
  trusted: boolean;
  composing: boolean;
  ts: number; // event.timeStamp, ms
  now: number; // performance.now() on entry to the handler, ms
}

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

function randomDevLabel(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return "DEV-" + [...bytes].map((b) => CROCKFORD[b % 32]).join("");
}

function select(id: string, options: Array<[string, string]>): HTMLSelectElement {
  return h("select", { id }, ...options.map(([value, label]) => h("option", { value }, label)));
}

export async function keycheckPage(root: HTMLElement, params: URLSearchParams): Promise<void> {
  const synthetic = params.get("synthetic") === "1";
  const [browser, layout] = await Promise.all([detectBrowserVersion(), detectLayout()]);
  const timerResolutionUs = probeTimerResolutionUs();
  const isolated = self.crossOriginIsolated === true;

  const tester = h("input", { id: "kc-tester", value: randomDevLabel(), maxlength: 32, size: 16 });
  const keyboard = select("kc-keyboard", [["", "Choose…"], ["laptop_builtin", "Laptop's built-in keyboard"], ["external", "External keyboard"], ["other", "Other"]]);
  const keyboardLabel = h("input", { id: "kc-keyboard-label", maxlength: 64, size: 24, placeholder: "e.g. Dell KB216 (optional)" });
  const os = select("kc-os", [["", "Choose…"], ["windows", "Windows"], ["macos", "macOS"], ["linux", "Linux"], ["chromeos", "ChromeOS"], ["other", "Other"]]);
  const status = h("p", { id: "kc-status", class: "status" }, "Not recording.");
  const error = h("p", { class: "error" });
  const host = h("div", { id: "kc-editor", class: "keycheck-editor" });
  // The active task, repeated right above the typing box so both are on screen together.
  const now = h("section", { id: "kc-now", class: "keycheck-now", hidden: true });
  const finishBtn = h("button", { id: "kc-finish", disabled: true }, "Finish task");
  const downloadBtn = h("button", { id: "kc-download", class: "primary", disabled: true }, "Save file");

  const records: KeyRecord[] = [];
  const tasks: Array<{ id: TaskId; start_ms: number; end_ms: number; keydowns: number }> = [];
  const jankBlocks: Array<[number, number]> = [];
  let active: { id: TaskId; start: number; keydowns: number } | null = null;
  let jankTimer = 0;

  const startButtons = TASKS.map((t) => h("button", { id: `kc-start-${t.id}` }, "Start"));
  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Real-keyboard check"),
      h("p", { class: "banner" },
        h("strong", {}, "Development data. "),
        "For team members only. Timing is recorded in this browser and saved as a file; nothing is sent to the server. ",
        "The file is never part of a study dataset.",
      ),
      synthetic ? h("p", { class: "banner" }, h("strong", {}, "SYNTHETIC: "), "automated test input.") : null,
      h("label", {}, "Tester label (not your name): ", tester),
      h("label", {}, "Keyboard: ", keyboard, " ", keyboardLabel),
      h("label", {}, "Operating system: ", os),
      h("p", { class: "muted", id: "kc-env" },
        `Browser: ${browser.brand} ${browser.version || "(version unknown)"} · cross-origin isolated: ${isolated ? "yes" : "no"} · ` +
        `timer step: ${timerResolutionUs} µs · layout: ${layout ?? "not detectable here"}`,
      ),
      ...TASKS.map((t, i) => h("section", {},
        h("h2", {}, t.title),
        h("p", {}, t.steps),
        t.text ? h("pre", { class: "notice" }, t.text) : null,
        h("div", { class: "row" }, startButtons[i]),
      )),
      now,
      host,
      h("div", { class: "row" }, finishBtn, downloadBtn),
      status,
      error,
    ),
  );

  const editor = createEditor(host, POLICY, "");
  const onKey = (e: KeyboardEvent) => {
    const now = performance.now();
    if (!active) return;
    if (e.type === "keydown") active.keydowns += 1;
    records.push({
      task: active.id, type: e.type as KeyRecord["type"], code: safeCode(e.code), rep: e.repeat, mods: modifierMask(e),
      trusted: e.isTrusted, composing: e.isComposing, ts: e.timeStamp, now,
    });
    status.textContent = `Recording task "${active.id}": ${active.keydowns} key presses.`;
  };
  const dom = editor.getDomNode()!;
  dom.addEventListener("keydown", onKey, true);
  dom.addEventListener("keyup", onKey, true);

  const finish = () => {
    if (!active) return;
    window.clearInterval(jankTimer);
    tasks.push({ id: active.id, start_ms: active.start, end_ms: performance.now(), keydowns: active.keydowns });
    now.hidden = true;
    status.textContent = `Finished task "${active.id}" (${active.keydowns} key presses). Tasks done: ${tasks.map((t) => t.id).join(", ")}.`;
    active = null;
    finishBtn.setAttribute("disabled", "");
    downloadBtn.removeAttribute("disabled");
  };

  TASKS.forEach((t, i) => startButtons[i].addEventListener("click", () => {
    finish();
    editor.setValue("");
    active = { id: t.id, start: performance.now(), keydowns: 0 };
    if (t.id === "jank") {
      jankTimer = window.setInterval(() => {
        const start = performance.now();
        while (performance.now() - start < JANK_BLOCK_MS) { /* block the main thread */ }
        jankBlocks.push([start, performance.now()]);
      }, JANK_PERIOD_MS);
    }
    finishBtn.removeAttribute("disabled");
    status.textContent = `Recording task "${t.id}". Click "Finish task" when done.`;
    now.replaceChildren(
      h("h2", {}, `Now: ${t.title}`), h("p", {}, t.steps), ...(t.text ? [h("pre", { class: "notice" }, t.text)] : []),
    );
    now.hidden = false;
    now.scrollIntoView({ block: "start" });
    editor.focus();
  }));
  finishBtn.addEventListener("click", finish);

  downloadBtn.addEventListener("click", () => {
    finish();
    const label = (tester as HTMLInputElement).value.trim();
    const keyboardType = (keyboard as HTMLSelectElement).value;
    const osValue = (os as HTMLSelectElement).value;
    if (!/^[A-Za-z0-9-]{1,32}$/.test(label)) return void (error.textContent = "Tester label: letters, digits and hyphens only.");
    if (!keyboardType || !osValue) return void (error.textContent = "Choose the keyboard and the operating system first.");
    error.textContent = "";
    const file = {
      format: KEYCHECK_FORMAT,
      dataset: "development",
      not_for_study: true,
      synthetic,
      created_at: new Date().toISOString(),
      tester: label,
      keyboard_type: keyboardType,
      keyboard_label: (keyboardLabel as HTMLInputElement).value.trim().slice(0, 64),
      os: osValue,
      layout: layout ?? "",
      browser,
      cross_origin_isolated: isolated,
      timer_resolution_us: timerResolutionUs,
      protocol: { jank_block_ms: JANK_BLOCK_MS, jank_period_ms: JANK_PERIOD_MS },
      tasks,
      jank_blocks: jankBlocks,
      events: records,
    };
    const stamp = file.created_at.replace(/[-:]/g, "").slice(0, 15);
    const href = URL.createObjectURL(new Blob([JSON.stringify(file)], { type: "application/json" }));
    const a = h("a", { href, download: `keycheck_${label}_${browser.brand}_${keyboardType}_${stamp}.dev.json` });
    document.body.append(a); // Firefox saves only from an attached link
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 10_000);
    status.textContent = `Saved ${records.length} key events. Move the file to your data root (docs/keycheck.md).`;
  });
}
