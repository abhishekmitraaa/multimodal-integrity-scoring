// When the backend is not running, the app must say so plainly before anyone fills in the form,
// instead of failing later with a raw HTTP code. The API is blocked with a 502, which is what the
// Vite proxy returns when nothing listens on port 8000.
import { expect, test } from "@playwright/test";

test("consent page explains that the study server is not running", async ({ page }) => {
  await page.route("**/api/**", (route) => route.fulfill({ status: 502, body: "" }));
  await page.goto("/");
  const banner = page.locator("#server-down");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("study server is not running");
  await expect(banner).toContainText("scripts\\dev.ps1");
  await expect(page.locator("#consent-continue")).toBeDisabled();
});

test("a server failure after the page loaded gives the same plain message", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#consent-continue")).toBeEnabled();
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
  await page.check("#age");
  await page.check("#agree");
  await page.click("#consent-continue");
  await expect(page.locator("#consent-error")).toContainText("study server is not running");
});
