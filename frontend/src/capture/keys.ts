// Key categories (SPEC 4.6). KeyboardEvent.key is used here and then dropped; it is never sent.

export type KeyCategory =
  | "letter"
  | "digit"
  | "symbol"
  | "bracket"
  | "whitespace"
  | "backspace"
  | "navigation"
  | "modifier"
  | "other";

const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "AltGraph"]);
const NAVIGATION = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);
const BRACKETS = new Set(["(", ")", "[", "]", "{", "}"]);

export function keyCategory(key: string): KeyCategory {
  if (MODIFIERS.has(key)) return "modifier";
  if (key === "Backspace" || key === "Delete") return "backspace";
  if (key === " " || key === "Tab" || key === "Enter") return "whitespace";
  if (NAVIGATION.has(key)) return "navigation";
  if ([...key].length === 1) {
    if (BRACKETS.has(key)) return "bracket";
    if (/^\p{L}$/u.test(key)) return "letter";
    if (/^\p{Nd}$/u.test(key)) return "digit";
    return "symbol";
  }
  return "other";
}

export const MOD_SHIFT = 1;
export const MOD_CTRL = 2;
export const MOD_ALT = 4;
export const MOD_META = 8;

export function modifierMask(e: { shiftKey: boolean; ctrlKey: boolean; altKey: boolean; metaKey: boolean }): number {
  return (e.shiftKey ? MOD_SHIFT : 0) | (e.ctrlKey ? MOD_CTRL : 0) | (e.altKey ? MOD_ALT : 0) | (e.metaKey ? MOD_META : 0);
}

/** KeyboardEvent.code restricted to the schema's alphabet. */
export function safeCode(code: string): string {
  return code.replace(/[^A-Za-z0-9]/g, "").slice(0, 32);
}
