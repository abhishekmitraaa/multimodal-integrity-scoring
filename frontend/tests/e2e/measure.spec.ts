// SPEC 4.11: measure browser and Monaco behaviour instead of assuming it. SYNTHETIC input only.
// Writes one JSON file per browser and origin under test-results/measurements/.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { drain, mod, serverEvents, startSession } from "./helpers";

const ORIGINS = [
  { label: "plain", base: "http://127.0.0.1:5174" },
  { label: "coop_coep", base: "http://127.0.0.1:5173" },
];

/** Coarsest candidate grid (µs) that every value sits on. */
function gridUs(valuesMs: number[]): number {
  const candidates = [100_000, 16_667, 1_000, 100, 20, 5, 1];
  for (const c of candidates) {
    if (valuesMs.every((v) => {
      const q = (v * 1000) / c;
      return Math.abs(q - Math.round(q)) < 1e-3;
    })) return c;
  }
  return 0;
}

for (const origin of ORIGINS) {
  test(`measure browser behaviour (${origin.label})`, async ({ page, request, browserName }) => {
    const sessionId = await startSession(page, "practice_sum_evens", origin.base);
    await page.evaluate(() => {
      const w = window as any;
      w.__probe = [];
      const dom = w.__integrity.editor.getDomNode();
      dom.addEventListener("keydown", (e: KeyboardEvent) => w.__probe.push({ ts: e.timeStamp, now: performance.now(), trusted: e.isTrusted }), true);
    });
    await page.keyboard.press(`${await mod(page)}+A`);
    await page.keyboard.press("Delete");
    await page.keyboard.type("abcdefghij klmnopqrst uvwxyz 0123456789 abcdefghij", { delay: 23 });
    const probe: Array<{ ts: number; now: number; trusted: boolean }> = await page.evaluate(() => (window as any).__probe);

    // Paste and multi-cursor ordering.
    await page.evaluate(() => {
      const { editor } = (window as any).__integrity;
      editor.setValue("aa\nbb\ncc");
    });
    await page.keyboard.press(`${await mod(page)}+A`);
    await page.keyboard.press(`${await mod(page)}+C`);
    await page.keyboard.press(`${await mod(page)}+End`);
    await page.keyboard.press(`${await mod(page)}+V`);
    await page.evaluate(() => {
      const { editor } = (window as any).__integrity;
      editor.setSelections([
        { selectionStartLineNumber: 1, selectionStartColumn: 1, positionLineNumber: 1, positionColumn: 1 },
        { selectionStartLineNumber: 3, selectionStartColumn: 1, positionLineNumber: 3, positionColumn: 1 },
      ]);
      editor.focus();
    });
    await page.keyboard.type("#");
    await page.locator(".monaco-editor .view-lines").click({ position: { x: 40, y: 5 } });
    expect(await drain(page)).toBe(true);

    const env = await page.evaluate(async () => ({
      crossOriginIsolated: self.crossOriginIsolated === true,
      layoutMapApi: typeof (navigator as any).keyboard?.getLayoutMap === "function",
      userAgent: navigator.userAgent,
    }));
    const events = await serverEvents(request, sessionId);
    const start = events.find((e) => e.type === "segment_start")!;
    const client = events.filter((e) => e.origin === "client");
    const types = client.map((e) => e.type);
    // Event order around the first single typed character (keydown → change → keyup expected).
    const firstTyped = client.findIndex((e) => e.type === "content_change" && e.data.cause === "typed" && e.data.ins_len === 1);
    const pasteIdx = types.indexOf("paste");
    const pasteChangeIdx = events.filter((e) => e.origin === "client").findIndex((e) => e.type === "content_change" && e.data.cause === "paste");
    const multi = events.filter((e) => e.type === "content_change" && (e.data.n as number) > 1).map((e) => e.data.offset as number);
    const deltas = probe.slice(1).map((p, i) => p.ts - probe[i].ts);

    const result = {
      browser: browserName,
      origin: origin.label,
      userAgent: env.userAgent,
      crossOriginIsolated: env.crossOriginIsolated,
      performanceNowProbeUs: (start.data.timer as { resolution_us: number }).resolution_us,
      keydownTimeStampGridUs: gridUs(probe.map((p) => p.ts)),
      keydownTimeStampMinDeltaMs: Math.min(...deltas.filter((d) => d > 0)),
      dispatchLagMsMean: probe.reduce((s, p) => s + (p.now - p.ts), 0) / probe.length,
      dispatchLagMsMax: Math.max(...probe.map((p) => p.now - p.ts)),
      playwrightKeysIsTrusted: [...new Set(probe.map((p) => p.trusted))],
      layoutMapApi: env.layoutMapApi,
      layoutRecorded: (start.data.device as { layout: string; layout_source: string }),
      typedCharEventOrder: firstTyped > 0 ? types.slice(firstTyped - 1, firstTyped + 2) : [],
      osFamilyRecorded: (start.data.device as { os_family: string }).os_family,
      pasteEventCaptured: pasteIdx >= 0,
      pasteEventBeforeItsContentChange: pasteIdx >= 0 && pasteChangeIdx >= 0 ? pasteIdx < pasteChangeIdx : null,
      multiChangeOffsetsInOrderSent: multi,
      cursorSourcesSeen: [...new Set(events.filter((e) => e.type === "cursor").map((e) => e.data.source))],
      causesSeen: [...new Set(events.filter((e) => e.type === "content_change").map((e) => e.data.cause))],
    };
    // Not test-results/: Playwright wipes that folder on every run.
    const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "measurements");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, `${browserName}-${origin.label}.json`), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
    expect(result.typedCharEventOrder).toEqual(["keydown", "content_change", "keyup"]);
  });
}
