// Shared helpers for end-to-end tests. Every participant created here is kind "synthetic".
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const REVIEWER_TOKEN = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "secrets", "reviewer_token.txt"), "utf8").trim();
export const API = "http://127.0.0.1:8000";

export interface ServerEvent {
  server_seq: number;
  client_seq: number | null;
  epoch: number;
  origin: "client" | "server";
  type: string;
  t_client_us: number | null;
  data: Record<string, unknown>;
}

/**
 * The shortcut modifier Monaco expects. Playwright's WebKit reports a macOS user agent even on
 * Windows, so Monaco binds Cmd there; Playwright's "ControlOrMeta" follows the host OS instead.
 */
export async function mod(page: Page): Promise<"Meta" | "Control"> {
  return page.evaluate(() => (/Mac/.test(navigator.userAgent) ? "Meta" : "Control"));
}

export async function startSession(page: Page, problem = "practice_sum_evens", base = ""): Promise<string> {
  await page.goto(`${base}/?kind=synthetic#/`);
  await page.check("#age");
  await page.check("#agree");
  await page.click("#consent-continue");
  await page.waitForURL(/#\/setup/);
  await page.click(`button[data-problem="${problem}"]`);
  await page.waitForURL(/#\/session\//);
  await expect(page.locator("#status")).toHaveText("open", { timeout: 30_000 });
  return page.url().split("#/session/")[1];
}

export async function editorValue(page: Page): Promise<string> {
  return page.evaluate(() => (window as any).__integrity.editor.getValue());
}

/** Wait until every event created so far is acked by the server. */
export async function drain(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as any).__integrity.transport.drained(15_000));
}

export async function staffGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`${API}${path}`, { headers: { Authorization: `Bearer ${REVIEWER_TOKEN}` } });
  expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

export async function serverEvents(request: APIRequestContext, sessionId: string): Promise<ServerEvent[]> {
  return (await staffGet<{ events: ServerEvent[] }>(request, `/api/sessions/${sessionId}/events`)).events;
}

/** Replace the editor content by typing, relying on Monaco auto-indent after the colon. */
export async function typeSolution(page: Page, lines: string[]): Promise<void> {
  await page.keyboard.press(`${await mod(page)}+A`);
  await page.keyboard.press("Delete");
  for (const [i, line] of lines.entries()) {
    if (i > 0) await page.keyboard.press("Enter");
    await page.keyboard.type(line, { delay: 15 });
  }
}
