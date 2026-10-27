// The whole journey (D-036): three practice tasks build a baseline, the exam is checked against it,
// the participant sees their report and adds a note, and a reviewer finds it on the dashboard and
// records a decision (D-039). SYNTHETIC input.
import { expect, test, type Page } from "@playwright/test";
import { mod, REVIEWER_TOKEN } from "./helpers";

const PRACTICE = ["practice_sum_evens", "practice_word_count", "practice_letter_grade"];
const EXAM_START = ["def rle(s):", "out = []", "i = 0"];
const PASTED = "\n    while i < len(s):\n        j = i\n        while j < len(s) and s[j] == s[i]:\n            j += 1\n        out.append(s[i] + str(j - i))\n        i = j\n    return ''.join(out)\n";

async function typeCode(page: Page, code: string): Promise<void> {
  await page.locator(".monaco-editor .view-lines").click();
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
    await page.keyboard.type(line.trimStart(), { delay: 25 });
  }
}

async function openTask(page: Page, problem: string): Promise<void> {
  await page.click(`button[data-problem="${problem}"]`);
  await page.waitForURL(/#\/session\//);
  await expect(page.locator("#status")).toHaveText("open", { timeout: 30_000 });
}

async function testAndSubmit(page: Page, expected: RegExp = /3\/3 tests passed/): Promise<void> {
  await page.click("#test");
  await expect(page.locator("#output")).toContainText(expected, { timeout: 90_000 });
  await page.click("#submit");
  await page.waitForURL(/#\/done\//);
}

test("practice builds a baseline, the exam is checked, the report and dashboard show it", async ({ page, browserName }) => {
  // Playwright's WebKit on Windows: during this test's long scripted typing, the Pyodide worker
  // never finishes loading (not even in 4 min), although it loads in the shorter WebKit tests.
  // Safari is out of the study's scope (D-025); open question in docs/phase-reports/P3-P4-slice.md.
  test.skip(browserName === "webkit", "Pyodide does not finish loading in Playwright WebKit during long typing (D-025: Safari out of scope)");
  test.setTimeout(300_000);
  await page.goto("/?kind=synthetic#/");
  await page.check("#age");
  await page.check("#agree");
  await page.click("#consent-continue");
  await page.waitForURL(/#\/setup/);
  const pseudonym = (await page.textContent("#pseudonym"))!;

  for (const problem of PRACTICE) {
    await openTask(page, problem);
    await typeCode(page, (await page.textContent("#reference-code"))!);
    await testAndSubmit(page);
    await expect(page.locator("#see-report")).toHaveCount(0);           // practice: no report link yet
    await page.click("#another-task");
    await expect(page.locator(`button[data-problem="${problem}"]`)).toHaveClass(/task-done/);
  }

  // The baseline check (D-038): typed like practice, held out and compared with the baseline.
  await openTask(page, "check_count_vowels");
  await typeCode(page, (await page.textContent("#reference-code"))!);
  await testAndSubmit(page);
  await page.click("#another-task");
  await expect(page.locator('button[data-problem="check_count_vowels"]')).toHaveClass(/task-done/);
  await expect(page.locator('button[data-problem="check_count_vowels"]')).toBeDisabled();   // one check only

  // Exam: some typing, then a block of code that arrives without key presses.
  await openTask(page, "exam_run_length");
  await typeCode(page, EXAM_START.join("\n    "));
  await page.waitForTimeout(600);          // well past the 250 ms key window: labelled "unknown", not "typed"
  // Through the editor's own edit API: Playwright's insertText drops multi-line text in WebKit.
  await page.evaluate((text) => {
    const { editor } = (window as any).__integrity;
    const end = editor.getModel().getFullModelRange().getEndPosition();
    editor.executeEdits("test", [{ range: { startLineNumber: end.lineNumber, startColumn: end.column, endLineNumber: end.lineNumber, endColumn: end.column }, text }]);
  }, PASTED);
  await testAndSubmit(page, /tests passed/);

  // The participant's own report.
  await page.click("#see-report");
  await expect(page.locator("#overall-verdict")).toContainText("Review recommended", { timeout: 60_000 });
  await expect(page.locator('[data-finding="untyped"]')).toHaveClass(/finding-flag/);
  await expect(page.locator('[data-finding="reconciliation"]')).toHaveClass(/finding-flag/);
  await expect(page.locator("#baseline-status")).toContainText(/windows of typing/);
  await expect(page.locator("#baseline-check")).toContainText(/Baseline check: (confirmed|does not match|could not run)/);
  const ks = page.locator('[data-finding="keystroke"]');
  await expect(page.locator(".ks-chart")).toHaveCount(0);              // participants never see distances or thresholds
  const modelRan = (await page.locator("#distances-redacted").count()) > 0;
  if (modelRan) {
    await expect(ks).toHaveClass(/finding-(ok|flag)/);                  // model installed: compared to the baseline
  } else {
    await expect(ks).toHaveClass(/finding-unavailable/);                // no model on this machine: said plainly
  }

  // The participant adds a note for the reviewer (D-039).
  const review = page.locator(".review");
  await expect(review.locator("#no-decision")).toBeVisible();
  const note = "The pasted part is my own helper from an earlier assignment.";
  await review.locator("textarea").fill(note);
  await review.locator("button.primary").click();
  await expect(review.locator(".appeal")).toContainText(note);

  // The reviewer dashboard lists the participant and opens the same report.
  await page.goto("/#/dashboard");
  await page.fill("#dash-token", REVIEWER_TOKEN);
  await page.click("#dash-load");
  const row = page.locator(`tr[data-pseudonym="${pseudonym}"]`);
  await expect(row).toContainText("3 practice · check ✓ · 1 exam");
  await expect(row.locator(".decision-cell")).toHaveText("Not reviewed");
  await row.locator("button").click();
  await expect(page.locator("#overall-verdict")).toContainText("Review recommended", { timeout: 60_000 });
  await expect(page.locator("#report a[href^='#/replay?session=']")).toHaveCount(1);
  await expect(page.locator(".ks-chart")).toHaveCount(modelRan ? 1 : 0);   // reviewers do see the distances
  await expect(page.locator('[data-finding="ast_jump"]')).toHaveClass(/finding-info/);   // AST evidence, never a flag (SPEC 6.3)

  // The reviewer reads the participant's note and records a decision with notes (D-039).
  await expect(review.locator(".appeal")).toContainText(note);
  await expect(review.locator(".chain")).toHaveClass(/chain-ok/);        // the decision panel shows the hash-chain check
  await expect(review.locator(".chain")).toContainText(/verified over \d+ events/);
  await review.locator("select").selectOption("inconclusive");
  await review.locator("textarea").fill("short");
  await review.locator("button.primary").click();
  await expect(review.locator(".error")).toContainText("at least 10 characters");
  const notes = "Paste is visible in the replay; asked the student to walk through it.";
  await review.locator("textarea").fill(notes);
  await review.locator("button.primary").click();
  await expect(review.locator(".decision-current")).toContainText("Inconclusive");
  await expect(review.locator(".decision-current")).toContainText(notes);
  await expect(row.locator(".decision-cell")).toHaveText("Inconclusive");

  // The participant sees the outcome and date, not the reviewer's notes.
  await page.goto("/#/my-report");
  await expect(review.locator(".decision-current")).toContainText("Inconclusive", { timeout: 60_000 });
  await expect(review).not.toContainText(notes);
  await expect(review).not.toContainText("reviewer-1");
});
