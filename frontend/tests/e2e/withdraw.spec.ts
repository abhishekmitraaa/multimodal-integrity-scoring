// Withdrawal (SPEC 10.3, 10.7): the participant withdraws in the app and all their data is erased.
// The notice shows the governance values from config, or "[to be set]" while they are blank. SYNTHETIC.
import { expect, test } from "@playwright/test";
import { REVIEWER_TOKEN } from "./helpers";

test("the notice shows the governance fields and a participant can withdraw and erase their data", async ({ page, request }) => {
  await page.goto("/?kind=synthetic#/");
  await expect(page.locator("#notice")).toContainText("Contact for withdrawal, questions and complaints: [to be set].");
  await expect(page.locator("#notice")).toContainText("Responsible for your data: [to be set].");
  await page.check("#age");
  await page.check("#agree");
  await page.click("#consent-continue");
  await page.waitForURL(/#\/setup/);
  const pseudonym = (await page.textContent("#pseudonym"))!;

  await page.click("#withdraw summary");
  await page.click("#withdraw-start");
  await expect(page.locator("#withdraw-result")).toContainText("cannot be undone");
  await page.click("#withdraw-confirm");
  await expect(page.locator("#withdrawn")).toContainText("All your data has been deleted");

  const listed = await request.get("/api/participants", { headers: { Authorization: `Bearer ${REVIEWER_TOKEN}` } });
  expect((await listed.json() as Array<{ pseudonym: string }>).map((p) => p.pseudonym)).not.toContain(pseudonym);
  await page.goto("/#/setup");
  await expect(page.locator("#pseudonym")).toHaveCount(0);          // this tab forgot the participant
});
