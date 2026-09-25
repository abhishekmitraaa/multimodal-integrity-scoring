// Monaco setup under the editor policy (SPEC 4.8).
// Only the editor contributions we need are imported. Suggest, snippets, inline completions,
// code actions, formatting, drop/paste-into and rename are never loaded, so they cannot insert text.

import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/editor/contrib/clipboard/browser/clipboard";
import "monaco-editor/editor/contrib/find/browser/findController";
import "monaco-editor/editor/contrib/multicursor/browser/multicursor";
import "monaco-editor/editor/contrib/linesOperations/browser/linesOperations";
import "monaco-editor/editor/contrib/comment/browser/comment";
import "monaco-editor/editor/contrib/wordOperations/browser/wordOperations";
import "monaco-editor/editor/contrib/cursorUndo/browser/cursorUndo";
import "monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching";
import "monaco-editor/languages/definitions/python/register";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import { isBlockedKey, type BlockedKey } from "./capture/keys";

export { monaco };

(self as unknown as { MonacoEnvironment: monaco.Environment }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};

export interface EditorPolicy {
  policy_id: string;
  monaco_options: Record<string, unknown>;
  blocked_keys: BlockedKey[];
  sha256: string;
}

export interface PolicyCheck {
  option: string;
  status: "ok" | "mismatch" | "not_verifiable";
  expected: unknown;
  actual?: unknown;
}

export function createEditor(host: HTMLElement, policy: EditorPolicy, initialText: string): monaco.editor.IStandaloneCodeEditor {
  const model = monaco.editor.createModel(initialText, "python");
  model.setEOL(monaco.editor.EndOfLineSequence.LF);
  const editor = monaco.editor.create(host, {
    ...(policy.monaco_options as monaco.editor.IStandaloneEditorConstructionOptions),
    model,
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 15,
    tabSize: 4,
    insertSpaces: true,
    scrollBeyondLastLine: false,
  });
  // Blocked keys (D-027): stopped in the capture phase on the editor node, before Monaco's own
  // handlers see them. The capture layer's listener on the same node still logs the keydown.
  // Replace inserts text without keystrokes; its toggle and row are also hidden in style.css.
  editor.getDomNode()!.addEventListener("keydown", (e) => {
    if (!isBlockedKey(e, policy.blocked_keys)) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  return editor;
}

// Monaco stores some options in a different shape from the one you set (measured in P1):
// quickSuggestions:false becomes {other,comments,strings:"off"}; autoIndent:"advanced" becomes 3.
const AUTO_INDENT: Record<string, number> = { none: 0, keep: 1, brackets: 2, advanced: 3, full: 4 };
const NORMALISE: Record<string, (expected: unknown) => unknown> = {
  quickSuggestions: (v) => (v === false ? { other: "off", comments: "off", strings: "off" } : v),
  autoIndent: (v) => (typeof v === "string" ? AUTO_INDENT[v] : v),
};

function subsetEqual(expected: unknown, actual: unknown): boolean {
  if (expected !== null && typeof expected === "object") {
    if (actual === null || typeof actual !== "object") return false;
    return Object.entries(expected).every(([k, v]) => subsetEqual(v, (actual as Record<string, unknown>)[k]));
  }
  return expected === actual;
}

/** Compare each policy option with the value Monaco actually computed (SPEC 4.8, 4.11). */
export function checkPolicy(editor: monaco.editor.IStandaloneCodeEditor, policy: EditorPolicy): PolicyCheck[] {
  const optionIds = monaco.editor.EditorOption as unknown as Record<string, number | undefined>;
  return Object.entries(policy.monaco_options).map(([option, expected]) => {
    const id = optionIds[option];
    if (typeof id !== "number") return { option, status: "not_verifiable", expected };
    const actual = editor.getOption(id as monaco.editor.EditorOption);
    const want = NORMALISE[option]?.(expected) ?? expected;
    return { option, status: subsetEqual(want, actual) ? "ok" : "mismatch", expected, actual };
  });
}
