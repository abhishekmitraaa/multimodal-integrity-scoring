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

export type BlockedKeyMod = "ctrl" | "meta" | "shift" | "alt";

/** A key the editor policy stops before Monaco sees it (config/editor_policy.yaml: blocked_keys). */
export interface BlockedKey {
  code: string;
  mods: BlockedKeyMod[];
}

/** True when the keydown's code matches and exactly the listed modifiers are held. */
export function isBlockedKey(
  e: { code: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean },
  blocked: readonly BlockedKey[],
): boolean {
  return blocked.some((b) =>
    b.code === e.code &&
    e.ctrlKey === b.mods.includes("ctrl") &&
    e.metaKey === b.mods.includes("meta") &&
    e.shiftKey === b.mods.includes("shift") &&
    e.altKey === b.mods.includes("alt"));
}

/** KeyboardEvent.code restricted to the schema's alphabet. */
export function safeCode(code: string): string {
  return code.replace(/[^A-Za-z0-9]/g, "").slice(0, 32);
}
