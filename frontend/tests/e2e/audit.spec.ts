// The admin access log on the dashboard (D-039): every staff read is listed; reviewers cannot open it.
import { expect, test } from "@playwright/test";
import { ADMIN_TOKEN, REVIEWER_TOKEN } from "./helpers";

test("the access log needs the admin token and lists dashboard reads", async ({ page }) => {
  await page.goto("/#/dashboard");
  await page.fill("#dash-token", REVIEWER_TOKEN);
  await page.click("#dash-audit-load");
  await expect(page.locator("#audit-error")).toHaveText("The access log needs the admin token.");

  await page.fill("#dash-token", ADMIN_TOKEN);
  await page.click("#dash-load");
  await expect(page.locator("#dash-list")).not.toBeEmpty();
  await page.click("#dash-audit-load");
  const table = page.locator("#audit-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr").first()).toContainText("read_access_log");     // newest first: this read
  await expect(table).toContainText("list_participants");
});
