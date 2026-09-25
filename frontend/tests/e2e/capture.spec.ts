// End-to-end P1 acceptance: capture → server log → replay, in Chromium, Firefox and WebKit.
// All sessions are SYNTHETIC (automated input, kind=synthetic).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { drain, editorValue, mod, serverEvents, staffGet, startSession, typeSolution, type ServerEvent } from "./helpers";

const SOLUTION = ["def sum_evens(xs):", "return sum(x for x in xs if x % 2 == 0)"];

function byType(events: ServerEvent[], type: string): ServerEvent[] {
  return events.filter((e) => e.type === type);
}

// Playwright's WebKit on Windows reports a macOS user agent but uses Windows key handling, so
// Monaco's Cmd+C/Cmd+V actions never reach the native clipboard there. That build cannot tell us
// how Safari on a Mac behaves; clipboard capture in Safari is an open item (P1 report).
const CLIPBOARD_MEASURABLE = (browser: string) => browser !== "webkit";

test("type, test, copy/paste, undo/redo, multi-cursor, non-BMP, submit; replay and chain match", async ({ page, request, browserName }) => {
  const clipboard = CLIPBOARD_MEASURABLE(browserName);
  if (!clipboard) {
    test.info().annotations.push({ type: "not measurable", description: "clipboard in Playwright WebKit on Windows; check Safari on a Mac" });
  }
  const sessionId = await startSession(page);

  await typeSolution(page, SOLUTION);
  await page.click("#test");
  await expect(page.locator("#output")).toContainText("3/3 tests passed", { timeout: 90_000 });

  // Copy a test call from the problem panel and paste it into the editor as a comment line.
  const call = page.locator("#problem li code").first();
  await call.click({ clickCount: 3 });
  await page.keyboard.press(`${await mod(page)}+C`);
  await page.locator(".monaco-editor .view-lines").click();
  await page.keyboard.press(`${await mod(page)}+End`);
  await page.keyboard.press("Enter");
  await page.keyboard.type("# ");
  await page.keyboard.press(`${await mod(page)}+V`);

  // Undo and redo the paste.
  await page.keyboard.press(`${await mod(page)}+Z`);
  await page.keyboard.press(`${await mod(page)}+Shift+Z`);

  // Non-BMP text (inserted without keydowns: cause should be "unknown").
  await page.keyboard.insertText(" π😀");

  // Multi-cursor: cursors on the last two lines, type one character on both.
  await page.evaluate(() => {
    const { editor } = (window as any).__integrity;
    const lines = editor.getModel().getLineCount();
    editor.setSelections([
      { selectionStartLineNumber: lines - 1, selectionStartColumn: 1, positionLineNumber: lines - 1, positionColumn: 1 },
      { selectionStartLineNumber: lines, selectionStartColumn: 1, positionLineNumber: lines, positionColumn: 1 },
    ]);
    editor.focus();
  });
  await page.keyboard.type("#");

  const finalText = await editorValue(page);
  expect(await drain(page)).toBe(true);
  await page.click("#submit");
  await page.waitForURL(/#\/done\//);
  const headHash = await page.locator("#head-hash").textContent();

  const events = await serverEvents(request, sessionId);
  const verify = await staffGet<{ ok: boolean; head_hash: string; n_events: number }>(request, `/api/sessions/${sessionId}/verify`);
  expect(verify.ok).toBe(true);
  expect(verify.head_hash).toBe(headHash);

  const replay = await staffGet<{ text: string; mismatches: number; errors: string[]; snapshot_checks: unknown[] }>(
    request, `/api/sessions/${sessionId}/replay`,
  );
  expect(replay.text).toBe(finalText);
  expect(replay.mismatches).toBe(0);
  expect(replay.errors).toEqual([]);

  // Ordering: client events gapless and in client_seq order.
  const seqs = events.filter((e) => e.origin === "client").map((e) => e.client_seq);
  expect(seqs).toEqual(seqs.map((_, i) => i));

  // Event coverage.
  for (const type of ["segment_start", "keydown", "keyup", "content_change", "snapshot", "run", "submit", "segment_end", "focus"]) {
    expect(byType(events, type).length, `${type} events`).toBeGreaterThan(0);
  }
  expect(byType(events, "run")[0].data).toMatchObject({ kind: "test", n_tests: 3, n_passed: 3, status: "ok" });

  // Change attribution hints.
  const causes = new Set(byType(events, "content_change").map((e) => e.data.cause));
  expect(causes).toContain("typed");
  expect(causes).toContain("undo");
  expect(causes).toContain("redo");
  expect(byType(events, "content_change").some((e) => (e.data.n as number) > 1)).toBe(true); // multi-cursor

  // Clipboard: copy from the problem panel, paste into the editor, attributed as a paste.
  if (clipboard) {
    expect(byType(events, "copy").some((e) => e.data.source === "problem_panel")).toBe(true);
    expect(byType(events, "paste").length).toBeGreaterThan(0);
    expect(causes).toContain("paste");
  }

  // Privacy: KeyboardEvent.key is never sent (schema would reject it; double-check here).
  expect(events.every((e) => !("key" in e.data))).toBe(true);
});

test("editor policy blocks untracked insertion", async ({ page }) => {
  await startSession(page);
  await page.keyboard.press(`${await mod(page)}+A`);
  await page.keyboard.press("Delete");
  await page.keyboard.type("(\"x");
  expect(await editorValue(page)).toBe("(\"x"); // no auto-closed ) or "
  await page.keyboard.type("\npri");
  await page.waitForTimeout(700);
  await expect(page.locator(".suggest-widget.visible")).toHaveCount(0);
  const checks = await page.evaluate(() => (window as any).__integrity.policyChecks as Array<{ option: string; status: string }>);
  expect(checks.filter((c) => c.status === "mismatch")).toEqual([]);
  expect(checks.filter((c) => c.status === "not_verifiable").map((c) => c.option)).toEqual(["wordBasedSuggestions"]);
});

test("reload starts a new segment; the unload batch arrives by beacon; replay continues", async ({ page, request, browserName }) => {
  const sessionId = await startSession(page);
  await typeSolution(page, ["def sum_evens(xs):", "return 0"]);
  await page.reload();
  await expect(page.locator("#status")).toHaveText("open", { timeout: 30_000 });
  expect(await editorValue(page)).toBe("def sum_evens(xs):\n    return 0");
  await page.locator(".monaco-editor .view-lines").click();
  await page.keyboard.press(`${await mod(page)}+End`);
  await page.keyboard.type("  # after reload");
  const finalText = await editorValue(page);
  expect(await drain(page)).toBe(true);
  await page.click("#submit");
  await page.waitForURL(/#\/done\//);

  const events = await serverEvents(request, sessionId);
  const starts = byType(events, "segment_start");
  expect(starts.map((e) => e.epoch)).toEqual([0, 1]);
  const ends = byType(events, "segment_end").map((e) => e.data.reason);
  // SPEC 4.11 item 7: does the pagehide beacon deliver the unload batch? Recorded, not assumed.
  const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "measurements");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${browserName}-beacon.json`), JSON.stringify({ browser: browserName, segmentEndReasons: ends }, null, 2));
  const replay = await staffGet<{ text: string; mismatches: number }>(request, `/api/sessions/${sessionId}/replay`);
  expect(replay.text).toBe(finalText);
  expect(replay.mismatches).toBe(0);
});

test("reviewer replay page verifies the chain and scrubs the code", async ({ page }) => {
  const sessionId = await startSession(page);
  await typeSolution(page, ["x = 1"]);
  expect(await drain(page)).toBe(true);
  await page.click("#submit");
  await page.waitForURL(/#\/done\//);

  const { REVIEWER_TOKEN } = await import("./helpers");
  await page.goto("/#/replay");
  await page.fill("#staff-token", REVIEWER_TOKEN);
  await page.click("text=Load sessions");
  await page.click(`button:has-text("${sessionId.slice(0, 8)}")`);
  await expect(page.locator("#chain-status")).toContainText("Hash chain verified");
  await expect(page.locator("#replay-text")).toHaveText("x = 1");
  await page.locator("#scrub").fill("0");
  await expect(page.locator("#replay-text")).not.toHaveText("x = 1");
});

test("cut, blur, visibility and a (blocked) drop are captured", async ({ page, request, browserName }) => {
  test.skip(!CLIPBOARD_MEASURABLE(browserName), "clipboard not measurable in Playwright WebKit on Windows");
  const sessionId = await startSession(page);
  await typeSolution(page, ["cut_me = 1"]);
  await page.keyboard.press("Shift+Home");
  await page.keyboard.press(`${await mod(page)}+X`);
  await page.locator("#problem h2").click(); // editor loses focus
  // Synthetic drop and visibility events (isTrusted=false): they exercise the logging path only.
  await page.evaluate(() => {
    const dom = (window as any).__integrity.editor.getDomNode();
    const dt = new DataTransfer();
    dt.setData("text/plain", "dropped text");
    dom.querySelector(".view-lines").dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const valueAfterDrop = await editorValue(page);
  expect(valueAfterDrop).toBe(""); // the drop inserted nothing
  expect(await drain(page)).toBe(true);
  const events = await serverEvents(request, sessionId);
  expect(byType(events, "cut")[0]?.data).toMatchObject({ source: "editor", len: 10 });
  expect(byType(events, "content_change").some((e) => e.data.cause === "cut")).toBe(true);
  expect(byType(events, "blur").some((e) => e.data.target === "editor")).toBe(true);
  expect(byType(events, "drop")[0]?.data).toMatchObject({ len: 12 });
  expect(byType(events, "visibility").length).toBeGreaterThan(0);
});
