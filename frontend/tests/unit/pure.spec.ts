// Unit tests for pure modules, run by the Playwright Test runner (D-009). Inputs are SYNTHETIC.
import { expect, test } from "@playwright/test";
import { parseUserAgent } from "../../src/capture/device";
import { keyCategory, modifierMask, safeCode } from "../../src/capture/keys";
import { EventLog } from "../../src/capture/log";
import { replayText } from "../../src/replay";

test.describe("key categories (SPEC 4.6)", () => {
  const cases: Array<[string, string]> = [
    ["a", "letter"], ["Z", "letter"], ["é", "letter"], ["5", "digit"], ["(", "bracket"], ["}", "bracket"],
    ["<", "symbol"], ["=", "symbol"], [" ", "whitespace"], ["Tab", "whitespace"], ["Enter", "whitespace"],
    ["Backspace", "backspace"], ["Delete", "backspace"], ["ArrowLeft", "navigation"], ["Home", "navigation"],
    ["Shift", "modifier"], ["Control", "modifier"], ["AltGraph", "modifier"], ["Escape", "other"], ["F5", "other"],
    ["Dead", "other"], ["Unidentified", "other"],
  ];
  for (const [key, cat] of cases) test(`${JSON.stringify(key)} → ${cat}`, () => expect(keyCategory(key)).toBe(cat));

  test("modifier mask", () => {
    expect(modifierMask({ shiftKey: true, ctrlKey: false, altKey: true, metaKey: false })).toBe(5);
  });
  test("code sanitised to schema alphabet", () => {
    expect(safeCode("KeyA")).toBe("KeyA");
    expect(safeCode("Weird-Key!")).toBe("WeirdKey");
  });
});

test.describe("event log (SPEC 4.2)", () => {
  test("seq assigned at creation; async slot blocks later events until ready", async () => {
    const log = new EventLog();
    log.start(10);
    log.push("keydown", {});
    let resolve!: (v: Record<string, unknown>) => void;
    log.pushAsync("copy", new Promise((r) => (resolve = r)));
    log.push("keyup", {});
    expect(log.takeUnsent().map((e) => e.client_seq)).toEqual([10]);
    resolve({ source: "editor" });
    await Promise.resolve();
    await Promise.resolve();
    expect(log.takeUnsent().map((e) => e.client_seq)).toEqual([11, 12]);
  });

  test("ack drops, resendFrom rewinds", () => {
    const log = new EventLog();
    log.start(0);
    for (let i = 0; i < 5; i++) log.push("keydown", {});
    expect(log.takeUnsent()).toHaveLength(5);
    log.ack(3);
    expect(log.firstUnacked()).toBe(3);
    log.resendFrom(3);
    expect(log.takeUnsent().map((e) => e.client_seq)).toEqual([3, 4]);
  });

  test("flush due after 15 keydowns", () => {
    const log = new EventLog();
    log.start(0);
    for (let i = 0; i < 14; i++) log.push("keydown", {});
    expect(log.flushDue(15, 5000)).toBe(false);
    log.push("keydown", {});
    expect(log.flushDue(15, 5000)).toBe(true);
  });

  test("timestamps are integer microseconds", () => {
    const log = new EventLog();
    log.start(0);
    const e = log.push("keydown", {}, 1234.5678);
    expect(e.t_client_us).toBe(1234568);
  });
});

test.describe("replay (SPEC 4.10)", () => {
  const change = (offset: number, del: number, text: string, idx = 0, n = 1) =>
    ({ version_id: 1, idx, n, offset, del_len: del, text, flush: false });
  test("UTF-16 offsets with non-BMP characters", () => {
    const events = [
      { server_seq: 0, type: "content_change", data: change(0, 0, "a😀b") },
      { server_seq: 1, type: "content_change", data: change(3, 1, "c") },
    ];
    expect(replayText(events)).toBe("a😀c");
  });
  test("multi-change group applied against the pre-event document", () => {
    const events = [
      { server_seq: 0, type: "snapshot", data: { reason: "segment_start", text: "ab\ncd" } },
      { server_seq: 1, type: "content_change", data: change(3, 0, "#", 0, 2) },
      { server_seq: 2, type: "content_change", data: change(0, 0, "#", 1, 2) },
    ];
    expect(replayText(events)).toBe("#ab\n#cd");
  });
});

test("user agent parsing keeps only families", () => {
  expect(parseUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"))
    .toEqual({ os_family: "windows", browser_family: "chromium", browser_major: 140 });
  expect(parseUserAgent("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"))
    .toEqual({ os_family: "linux", browser_family: "firefox", browser_major: 140 });
});
