// The scripted-attack runner (D-046): an admin-created A2 session typed through real browser input and
// submitted; the stored keystrokes have the auto-typer's near-constant rhythm. SYNTHETIC (dev tester).
import { createRequire } from "node:module";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { ADMIN_TOKEN, REVIEWER_TOKEN } from "./helpers";

const { runScripted } = createRequire(import.meta.url)(join(process.cwd(), "..", "eval", "tools", "attack_runner", "attack_runner.cjs"));
const CONSENT = { notice_version: "draft-2", notice_sha256: "a".repeat(64), choices: { participation: true } };

test("the A2 runner types the frozen material with a near-constant rhythm and submits", async ({ page, request, baseURL, browserName }) => {
  test.skip(browserName !== "chromium", "one browser is enough for the runner");
  test.setTimeout(240_000);
  const p = await (await request.post("/api/participants", { data: { kind: "dev", age_confirmed: true, consent: CONSENT, study: true } })).json();
  const out = await runScripted({ page, apiBase: baseURL, appBase: baseURL, adminToken: ADMIN_TOKEN, pseudonym: p.pseudonym,
    problem: "exam_second_largest", condition: "A2", seed: 3 });
  expect(out.keys).toBeGreaterThan(80);

  const ev = await (await request.get(`/api/sessions/${out.session_id}/events`, { headers: { Authorization: `Bearer ${REVIEWER_TOKEN}` } })).json();
  const downs = ev.events.filter((e: { type: string; data: { target?: string; cat?: string } }) =>
    e.type === "keydown" && e.data.target === "editor" && e.data.cat !== "modifier").map((e: { t_client_us: number }) => e.t_client_us / 1e3);
  const gaps = downs.slice(1).map((t: number, i: number) => t - downs[i]).filter((g: number) => g < 1000);
  const mean = gaps.reduce((a: number, b: number) => a + b, 0) / gaps.length;
  const sd = Math.sqrt(gaps.reduce((a: number, b: number) => a + (b - mean) ** 2, 0) / gaps.length);
  expect(sd / mean).toBeLessThan(0.25);                                  // people are far less even (habits: ~0.5+)
  expect(ev.events.some((e: { type: string }) => e.type === "submit")).toBe(true);
});
