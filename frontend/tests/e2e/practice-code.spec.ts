// D-035: practice tasks show the code to type, so nobody gets stuck; the exam task shows none.
// All sessions are SYNTHETIC (automated input, kind=synthetic).
import { expect, test, type Page } from "@playwright/test";
import { mod, startSession } from "./helpers";

/** Type code the way a person does in Monaco: it auto-indents after ':', Backspace removes a level. */
async function typeCode(page: Page, code: string): Promise<void> {
  await page.keyboard.press(`${await mod(page)}+A`);
  await page.keyboard.press("Delete");
  const lines = code.replace(/\n$/, "").split("\n");
  const indent = (l: string) => l.length - l.trimStart().length;
  for (const [i, line] of lines.entries()) {
    if (i > 0) {
      await page.keyboard.press("Enter");
      const prev = lines[i - 1];
      const auto = indent(prev) + (prev.trimEnd().endsWith(":") ? 4 : 0);
      for (let k = 0; k < (auto - indent(line)) / 4; k++) await page.keyboard.press("Backspace");
    }
    await page.keyboard.type(line.trimStart(), { delay: 5 });
  }
}

test("a practice task shows the code to type, and typing it passes the tests", async ({ page }) => {
  await startSession(page, "practice_sum_evens");
  const ref = page.locator("#reference-code");
  await expect(ref).toBeVisible();
  await expect(ref).toContainText("total += x");
  await expect(page.locator("#reference-help")).toContainText("Type this code");
  expect(await ref.evaluate((el) => getComputedStyle(el).userSelect)).toBe("none");   // can't be selected to copy

  await page.locator(".monaco-editor .view-lines").click();
  await typeCode(page, (await ref.textContent())!);
  await page.click("#test");
  await expect(page.locator("#output")).toContainText("3/3 tests passed", { timeout: 90_000 });
});

test("the exam task shows no code", async ({ page }) => {
  await startSession(page, "exam_run_length");
  await expect(page.locator("#problem")).toContainText("Run-length encoding");
  await expect(page.locator("#reference-code")).toHaveCount(0);
});
