// Find/replace policy (D-027): find works, replace is not offered, and a replace that still happens
// (for example after someone edits the page in devtools) is logged with cause "find_replace".
// All sessions are SYNTHETIC (automated input, kind=synthetic).
import { expect, test, type Page } from "@playwright/test";
import { drain, editorValue, mod, serverEvents, startSession } from "./helpers";

const TEXT = "abc abc";

async function typeText(page: Page): Promise<void> {
  await page.keyboard.press(`${await mod(page)}+A`);
  await page.keyboard.press("Delete");
  await page.keyboard.type(TEXT, { delay: 10 });
}

async function openFind(page: Page, query: string): Promise<void> {
  await page.keyboard.press(`${await mod(page)}+F`);
  await expect(page.locator(".monaco-editor .find-widget")).toBeVisible();
  await page.keyboard.type(query, { delay: 10 });
}

/** Monaco's replace shortcuts for the platform Monaco believes it is on. */
async function replaceChords(page: Page): Promise<string[]> {
  const m = await mod(page);
  return [m === "Meta" ? "Meta+Alt+F" : "Control+H", `${m}+Shift+Digit1`, `${m}+Alt+Enter`];
}

test("replace UI is hidden and replace shortcuts change nothing", async ({ page, request }) => {
  const sessionId = await startSession(page);
  await typeText(page);
  await openFind(page, "abc");

  const widget = page.locator(".monaco-editor .find-widget");
  await expect(widget.locator(".button.toggle")).toBeHidden();
  await expect(widget.locator(".replace-part")).toBeHidden();

  // From the find input, then from the editor text, with the find widget still open.
  for (const chord of await replaceChords(page)) await page.keyboard.press(chord);
  await expect(widget.locator(".replace-part")).toBeHidden();
  await page.locator(".monaco-editor .view-lines").click();
  for (const chord of await replaceChords(page)) await page.keyboard.press(chord);
  await expect(widget.locator(".replace-part")).toBeHidden();
  expect(await editorValue(page)).toBe(TEXT);

  expect(await drain(page)).toBe(true);
  const events = await serverEvents(request, sessionId);
  const causes = new Set(events.filter((e) => e.type === "content_change").map((e) => e.data.cause));
  expect([...causes].every((c) => c === "typed" || c === "command")).toBe(true);
  // The blocked keydowns are still in the log (Digit1 with Shift + Ctrl or Cmd).
  const blocked = events.filter((e) => e.type === "keydown" && e.data.code === "Digit1" && ((e.data.mods as number) & 1));
  expect(blocked.length).toBe(2);
});

test("a replace that bypasses the policy is labelled find_replace", async ({ page, request }) => {
  const sessionId = await startSession(page);
  await typeText(page);
  await openFind(page, "abc");

  // Simulate tampering: drive the find controller directly while focus is in the find widget.
  await page.evaluate(() => {
    const { editor } = (window as any).__integrity;
    const controller = editor.getContribution("editor.contrib.findController");
    controller.getState().change({ replaceString: "X" }, false);
    controller.replaceAll();
  });
  expect(await editorValue(page)).toBe("X X");

  expect(await drain(page)).toBe(true);
  const changes = (await serverEvents(request, sessionId)).filter((e) => e.type === "content_change");
  const replaced = changes.filter((e) => e.data.text === "X");
  expect(replaced.length).toBe(2);
  expect(replaced.every((e) => e.data.cause === "find_replace")).toBe(true);
});
