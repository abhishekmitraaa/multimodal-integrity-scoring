// Wires Monaco and DOM events into the event log (SPEC 4.5–4.7, 4.10).

import type { monaco } from "../editor";
import { normaliseClipboard, sha256Hex } from "./hash";
import { keyCategory, modifierMask, MOD_ALT, MOD_CTRL, MOD_META, safeCode, type KeyCategory } from "./keys";
import type { EventLog } from "./log";

type Editor = monaco.editor.IStandaloneCodeEditor;

export interface CaptureConfig {
  snapshotIntervalMs: number;
  largeInsertMinChars: number;
  largeInsertMinLines: number;
  cursorThrottleMs: number;
}

export type SnapshotReason = "timer" | "large_insert" | "run" | "submit" | "segment_start" | "resync";

export class Capture {
  private lastKey: { cat: KeyCategory; mods: number; t: number } | null = null;
  private pasteInfo: { len: number; newlines: number; trusted: boolean; mimes: string[] } | null = null;
  private pasteCauseUntil = 0;
  private cutCauseUntil = 0;
  private dropCauseUntil = 0;
  private compositionEndedAt = -1;
  private lastSnapshotVersion = -1;
  private lastCursorAt = 0;
  private disposers: Array<() => void> = [];

  constructor(
    private readonly editor: Editor,
    private readonly log: EventLog,
    private readonly cfg: CaptureConfig,
    private readonly problemPanel: HTMLElement,
  ) {}

  private get model(): monaco.editor.ITextModel {
    return this.editor.getModel()!;
  }

  private position(): { line: number; col: number } {
    const p = this.editor.getPosition();
    return { line: p?.lineNumber ?? 1, col: p?.column ?? 1 };
  }

  snapshot(reason: SnapshotReason, priority = false): void {
    const text = this.model.getValue();
    const version = this.model.getVersionId();
    this.lastSnapshotVersion = version;
    this.log.pushAsync(
      "snapshot",
      sha256Hex(text).then((sha256) => ({ version_id: version, reason, len: text.length, sha256, text })),
      performance.now(),
      priority,
    );
  }

  start(): void {
    const dom = this.editor.getDomNode()!;
    const on = <K extends keyof HTMLElementEventMap>(
      target: HTMLElement | Window | Document,
      type: K | string,
      fn: (e: never) => void,
      capture = true,
    ) => {
      target.addEventListener(type, fn as EventListener, capture);
      this.disposers.push(() => target.removeEventListener(type, fn as EventListener, capture));
    };

    // Keys: capture phase, so we see them before Monaco handles them.
    const onKey = (type: "keydown" | "keyup") => (e: KeyboardEvent) => {
      const cat = keyCategory(e.key);
      const mods = modifierMask(e);
      const target = (e.target as Element | null)?.closest(".find-widget") ? "find_widget" : "editor";
      if (type === "keydown" && target === "editor") this.lastKey = { cat, mods, t: performance.now() };
      this.log.push(type, {
        code: safeCode(e.code), cat, rep: e.repeat, mods, trusted: e.isTrusted,
        composing: e.isComposing, target, ...this.position(),
      }, e.timeStamp);
    };
    on(dom, "keydown", onKey("keydown"));
    on(dom, "keyup", onKey("keyup"));

    // Clipboard.
    on(dom, "paste", (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData("text/plain") ?? "";
      this.pasteInfo = {
        len: text.length,
        newlines: (text.match(/\n/g) ?? []).length,
        trusted: e.isTrusted,
        mimes: [...(e.clipboardData?.types ?? [])].slice(0, 16).map((m) => m.slice(0, 64)),
      };
      this.pasteCauseUntil = performance.now() + 1000;
    });
    const onCopyCut = (type: "copy" | "cut") => (e: ClipboardEvent) => {
      const eol = this.model.getEOL();
      const text = (this.editor.getSelections() ?? [])
        .filter((s) => !s.isEmpty())
        .map((s) => this.model.getValueInRange(s))
        .join(eol);
      if (type === "cut") this.cutCauseUntil = performance.now() + 1000;
      this.log.pushAsync(type, sha256Hex(normaliseClipboard(text)).then((sha256) => ({ source: "editor", len: text.length, sha256 })), e.timeStamp, true);
    };
    on(dom, "copy", onCopyCut("copy"));
    on(dom, "cut", onCopyCut("cut"));
    on(this.problemPanel, "copy", (e: ClipboardEvent) => {
      const text = document.getSelection()?.toString() ?? "";
      this.log.pushAsync("copy", sha256Hex(normaliseClipboard(text)).then((sha256) => ({ source: "problem_panel", len: text.length, sha256 })), e.timeStamp, true);
    });

    // Drop is blocked by policy; if one reaches the editor we block it here too and log it.
    on(dom, "drop", (e: DragEvent) => {
      const len = e.dataTransfer?.getData("text/plain").length ?? 0;
      e.preventDefault();
      e.stopPropagation();
      this.dropCauseUntil = performance.now() + 1000;
      this.log.push("drop", { len }, e.timeStamp, true);
    });

    // IME composition.
    for (const phase of ["start", "update", "end"] as const) {
      on(dom, `composition${phase}`, (e: CompositionEvent) => {
        if (phase === "end") this.compositionEndedAt = performance.now();
        this.log.push("composition", { phase, len: e.data?.length ?? 0 }, e.timeStamp);
      });
    }

    // Focus and visibility.
    const d1 = this.editor.onDidFocusEditorText(() => this.log.push("focus", { target: "editor" }));
    const d2 = this.editor.onDidBlurEditorText(() => this.log.push("blur", { target: "editor" }, performance.now(), true));
    this.disposers.push(() => d1.dispose(), () => d2.dispose());
    on(window, "focus", (e: FocusEvent) => this.log.push("focus", { target: "window" }, e.timeStamp), false);
    on(window, "blur", (e: FocusEvent) => this.log.push("blur", { target: "window" }, e.timeStamp, true), false);
    on(document, "visibilitychange", (e: Event) =>
      this.log.push("visibility", { state: document.visibilityState === "hidden" ? "hidden" : "visible" }, e.timeStamp, true),
    );

    // Content changes, with a cause hint (the server recomputes the canonical cause).
    const d3 = this.editor.onDidChangeModelContent((e) => {
      const cause = this.cause(e);
      let largest = 0;
      let newlines = 0;
      e.changes.forEach((c, idx) => {
        largest = Math.max(largest, c.text.length);
        newlines = Math.max(newlines, (c.text.match(/\n/g) ?? []).length);
        this.log.push("content_change", {
          version_id: e.versionId, idx, n: e.changes.length, offset: c.rangeOffset, del_len: c.rangeLength,
          ins_len: c.text.length, text: c.text,
          start_line: c.range.startLineNumber, start_col: c.range.startColumn,
          end_line: c.range.endLineNumber, end_col: c.range.endColumn,
          cause, undo: e.isUndoing, redo: e.isRedoing, flush: e.isFlush,
        });
      });
      if (largest >= this.cfg.largeInsertMinChars || newlines >= this.cfg.largeInsertMinLines || e.isFlush) {
        this.snapshot("large_insert");
      }
    });
    const d4 = this.editor.onDidPaste((e) => {
      const info = this.pasteInfo ?? {
        len: this.model.getValueLengthInRange(e.range), newlines: e.range.endLineNumber - e.range.startLineNumber,
        trusted: false, mimes: [],
      };
      this.pasteInfo = null;
      this.log.push("paste", {
        ...info, start_line: e.range.startLineNumber, start_col: e.range.startColumn,
        end_line: e.range.endLineNumber, end_col: e.range.endColumn,
      }, performance.now(), true);
    });
    const d5 = this.editor.onDidChangeCursorSelection((e) => {
      if (e.source === "keyboard") return; // typing and navigation are already in the key log
      const now = performance.now();
      if (now - this.lastCursorAt < this.cfg.cursorThrottleMs) return;
      this.lastCursorAt = now;
      const p = e.selection.getPosition();
      this.log.push("cursor", {
        line: p.lineNumber, col: p.column, sel_len: this.model.getValueLengthInRange(e.selection),
        reason: e.reason, source: String(e.source).slice(0, 32),
      });
    });
    this.disposers.push(() => d3.dispose(), () => d4.dispose(), () => d5.dispose());

    // Timer snapshots.
    const timer = window.setInterval(() => {
      if (this.model.getVersionId() !== this.lastSnapshotVersion) this.snapshot("timer");
    }, this.cfg.snapshotIntervalMs);
    this.disposers.push(() => window.clearInterval(timer));
  }

  private cause(e: monaco.editor.IModelContentChangedEvent): string {
    const now = performance.now();
    if (e.isFlush) return "flush";
    if (e.isUndoing) return "undo";
    if (e.isRedoing) return "redo";
    if (now < this.pasteCauseUntil) {
      this.pasteCauseUntil = 0;
      return "paste";
    }
    if (now < this.cutCauseUntil) {
      this.cutCauseUntil = 0;
      return "cut";
    }
    if (now < this.dropCauseUntil) return "drop";
    if (this.compositionEndedAt >= 0 && now - this.compositionEndedAt < 100) return "ime";
    const key = this.lastKey;
    if (key && key.cat !== "modifier" && now - key.t < 250) {
      const chord = key.mods & (MOD_CTRL | MOD_ALT | MOD_META);
      const altGr = (key.mods & (MOD_CTRL | MOD_ALT)) === (MOD_CTRL | MOD_ALT);
      const single = e.changes.length === 1 && e.changes[0].text.length <= 2 && e.changes[0].rangeLength === 0;
      return chord && !(altGr && single) ? "command" : "typed";
    }
    return "unknown";
  }

  stop(): void {
    this.disposers.forEach((d) => d());
    this.disposers = [];
  }
}
