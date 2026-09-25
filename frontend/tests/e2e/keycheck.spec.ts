// Real-keyboard check page (docs/keycheck.md). Input here is SYNTHETIC (Playwright), so the page is
// opened with ?synthetic=1 and the saved file says so. It checks the file format and that the
// Python report accepts it; it says nothing about real keyboards.
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const PYTHON = process.platform === "win32" ? join(REPO, ".venv", "Scripts", "python.exe") : join(REPO, ".venv", "bin", "python");

test("record the check tasks, save a development-data file, and report on it", async ({ page }) => {
  await page.goto("/#/keycheck?synthetic=1");
  await expect(page.locator("#kc-editor .monaco-editor")).toBeVisible();
  await page.selectOption("#kc-keyboard", "external");
  await page.selectOption("#kc-os", "windows");

  await page.click("#kc-start-prose");
  await page.keyboard.type("The quick brown fox", { delay: 20 });
  await page.click("#kc-finish");

  // Playwright marks a keydown for an already-pressed key as a repeat.
  await page.click("#kc-start-hold");
  for (let i = 0; i < 3; i++) await page.keyboard.down("a");
  await page.keyboard.up("a");
  await page.click("#kc-finish");

  await page.click("#kc-start-jank");
  await page.keyboard.type("abc def ghi jkl", { delay: 40 });
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#kc-download")]);

  expect(download.suggestedFilename()).toMatch(/^keycheck_DEV-[0-9A-Z]{8}_[a-z]+_external_\d{8}T\d{6}\.dev\.json$/);
  const file = JSON.parse(readFileSync((await download.path())!, "utf8"));
  expect(file).toMatchObject({ format: "keycheck.v1", dataset: "development", not_for_study: true, synthetic: true, os: "windows" });
  expect(file.tasks.map((t: { id: string }) => t.id)).toEqual(["prose", "hold", "jank"]);
  expect(file.jank_blocks.length).toBeGreaterThan(0);
  expect(typeof file.browser.brand).toBe("string");
  const events: Array<Record<string, unknown>> = file.events;
  // One keydown per character: Playwright's type() sends "T" without a separate Shift press.
  expect(events.filter((e) => e.task === "prose" && e.type === "keydown")).toHaveLength("The quick brown fox".length);
  expect(events.filter((e) => e.task === "hold" && e.type === "keydown" && e.rep === true)).toHaveLength(2);
  for (const e of events) {
    expect(typeof e.ts).toBe("number");
    expect(typeof e.now).toBe("number");
    expect(e).not.toHaveProperty("key");
  }

  // The Python report reads it (from a folder outside the repository, as it requires).
  const dir = mkdtempSync(join(tmpdir(), "keycheck-e2e-"));
  try {
    copyFileSync((await download.path())!, join(dir, download.suggestedFilename()));
    const report = execFileSync(PYTHON, ["-m", "integrity_eval.keycheck", dir], { encoding: "utf8" });
    expect(report).toContain("# Real-keyboard check report");
    expect(report).toContain("**SYNTHETIC.**");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
