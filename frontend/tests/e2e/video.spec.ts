// Webcam recording during the exam (D-048, a demo feature): Chromium's fake camera stands in for a
// real one. The participant ticks the separate box; the exam records; an admin can play it back; the
// reviewer token cannot; the head-movement panel is labelled a video demonstration. SYNTHETIC (dev tester).
import { expect, test } from "@playwright/test";
import { ADMIN_TOKEN, REVIEWER_TOKEN } from "./helpers";

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] } });

test("the webcam records during the exam and an admin can play it back", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "the fake camera flags are Chromium's");
  test.setTimeout(180_000);
  await page.goto("/#/");
  await expect(page.locator("#video-consent-label")).toBeVisible();
  await expect(page.locator("#notice")).toContainText("Webcam video (DEMO feature, no audio)");
  await page.check("#age");
  await page.check("#agree");
  await page.check("#video-consent");
  await page.click("#consent-continue");
  await page.waitForURL(/#\/setup/);
  const pseudonym = (await page.textContent("#pseudonym"))!;

  await page.click('button[data-problem="exam_run_length"]');
  await page.waitForURL(/#\/session\//);
  await expect(page.locator("#status")).toHaveText("open", { timeout: 30_000 });
  await expect(page.locator("#webcam-status")).toHaveText("● Recording webcam", { timeout: 20_000 });
  await page.locator(".monaco-editor .view-lines").click();
  await page.keyboard.type("def rle(s):", { delay: 40 });
  await page.waitForTimeout(6_000);                        // at least one 5 s chunk
  await page.click("#submit");
  await page.waitForURL(/#\/done\//, { timeout: 60_000 });

  await page.goto("/#/dashboard");
  await page.fill("#dash-token", REVIEWER_TOKEN);
  await page.click("#dash-load");
  await page.locator(`tr[data-pseudonym="${pseudonym}"] button`).click();
  await expect(page.locator("#overall-verdict")).toBeVisible({ timeout: 60_000 });      // the first report loads the model
  await expect(page.locator(".video-section")).toContainText("only an admin can view it");
  await page.locator(".video-section button").click();
  await expect(page.locator(".video-section .error")).toHaveText("Viewing the video needs the admin token.");
  await expect(page.locator("#head-demo .demo-tag")).toHaveText("Video demonstration");
  await expect(page.locator("#head-demo")).toContainText("Head and eye movement analysis modelling: in development, example output");

  await page.fill("#dash-token", ADMIN_TOKEN);
  await page.click("#dash-load");
  await page.locator(`tr[data-pseudonym="${pseudonym}"] button`).click();
  await expect(page.locator(".video-section button")).toBeVisible({ timeout: 60_000 });
  await page.locator(".video-section button").click();
  const player = page.locator(".video-section video");
  await expect(player).toHaveAttribute("src", /^blob:/);
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 20_000 }).toBeGreaterThan(0);
});

test("without the box ticked, nothing is recorded", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "the fake camera flags are Chromium's");
  await page.goto("/#/");
  await page.check("#age");
  await page.check("#agree");
  await page.click("#consent-continue");
  await page.waitForURL(/#\/setup/);
  await page.click('button[data-problem="exam_run_length"]');
  await page.waitForURL(/#\/session\//);
  await expect(page.locator("#status")).toHaveText("open", { timeout: 30_000 });
  await expect(page.locator("#webcam")).toHaveCount(0);
});
