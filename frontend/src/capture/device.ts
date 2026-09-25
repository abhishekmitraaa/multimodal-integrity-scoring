// Device covariates and timer probe (SPEC 4.9). Only parsed families are kept, never the UA string.

export type KeyboardType = "laptop_builtin" | "external" | "other" | "unknown";

export interface DeviceInfo {
  os_family: "windows" | "macos" | "linux" | "chromeos" | "other";
  browser_family: "chromium" | "firefox" | "webkit" | "other";
  browser_major: number;
  layout: string;
  layout_source: "api" | "self_report" | "unknown";
  keyboard_type: KeyboardType;
  screen_w: number;
  screen_h: number;
  dpr_x100: number;
}

export function parseUserAgent(ua: string): Pick<DeviceInfo, "os_family" | "browser_family" | "browser_major"> {
  const os_family = /CrOS/.test(ua)
    ? "chromeos"
    : /Windows/.test(ua)
      ? "windows"
      : /Mac OS X|Macintosh/.test(ua)
        ? "macos"
        : /Linux|X11/.test(ua)
          ? "linux"
          : "other";
  let browser_family: DeviceInfo["browser_family"] = "other";
  let major = 0;
  const firefox = ua.match(/Firefox\/(\d+)/);
  const chromium = ua.match(/(?:Chrome|Chromium|Edg)\/(\d+)/);
  const safari = ua.match(/Version\/(\d+).*Safari/);
  if (firefox) {
    browser_family = "firefox";
    major = Number(firefox[1]);
  } else if (chromium) {
    browser_family = "chromium";
    major = Number(chromium[1]);
  } else if (safari || /AppleWebKit/.test(ua)) {
    browser_family = "webkit";
    major = safari ? Number(safari[1]) : 0;
  }
  return { os_family, browser_family, browser_major: major };
}

export interface BrowserVersion {
  brand: "chrome" | "edge" | "chromium" | "firefox" | "safari" | "other";
  version: string;
}

/**
 * Browser brand and full version. Chromium reports brands through User-Agent Client Hints
 * (fullVersionList), which tells Edge from Chrome; other browsers fall back to the UA string.
 */
export function browserVersion(brands: Array<{ brand: string; version: string }> | undefined, ua: string): BrowserVersion {
  for (const [name, brand] of [["Microsoft Edge", "edge"], ["Google Chrome", "chrome"], ["Chromium", "chromium"]] as const) {
    const hit = brands?.find((b) => b.brand === name);
    if (hit) return { brand, version: hit.version };
  }
  const firefox = ua.match(/Firefox\/([\d.]+)/);
  if (firefox) return { brand: "firefox", version: firefox[1] };
  const edge = ua.match(/Edg\/([\d.]+)/);
  if (edge) return { brand: "edge", version: edge[1] };
  const chrome = ua.match(/Chrome\/([\d.]+)/);
  if (chrome) return { brand: "chrome", version: chrome[1] };
  const safari = ua.match(/Version\/([\d.]+).*Safari/);
  if (safari) return { brand: "safari", version: safari[1] };
  return { brand: "other", version: "" };
}

export async function detectBrowserVersion(): Promise<BrowserVersion> {
  const uaData = (navigator as unknown as {
    userAgentData?: { getHighEntropyValues(hints: string[]): Promise<{ fullVersionList?: Array<{ brand: string; version: string }> }> };
  }).userAgentData;
  let brands: Array<{ brand: string; version: string }> | undefined;
  try {
    brands = (await uaData?.getHighEntropyValues(["fullVersionList"]))?.fullVersionList;
  } catch {
    brands = undefined;
  }
  return browserVersion(brands, navigator.userAgent);
}

interface KeyboardLayoutMap {
  get(code: string): string | undefined;
}

/** Layout family from the Keyboard Map API (Chromium only); undefined elsewhere. */
export async function detectLayout(): Promise<string | undefined> {
  const kb = (navigator as unknown as { keyboard?: { getLayoutMap?: () => Promise<KeyboardLayoutMap> } }).keyboard;
  if (!kb?.getLayoutMap) return undefined;
  try {
    const map = await kb.getLayoutMap();
    const q = map.get("KeyQ");
    const z = map.get("KeyZ");
    if (q === "a") return "azerty";
    if (z === "y") return "qwertz";
    if (q === "q") return "qwerty";
    return "other";
  } catch {
    return undefined;
  }
}

/** Smallest positive step of performance.now() seen in a 50 ms busy loop, in microseconds. */
export function probeTimerResolutionUs(durationMs = 50): number {
  const end = performance.now() + durationMs;
  let last = performance.now();
  let min = Number.POSITIVE_INFINITY;
  for (;;) {
    const t = performance.now();
    if (t > end) break;
    const d = t - last;
    if (d > 0 && d < min) min = d;
    last = t;
  }
  return Number.isFinite(min) ? Math.round(min * 1000) : 0;
}

export async function collectDevice(keyboardType: KeyboardType, selfReportedLayout: string | undefined): Promise<DeviceInfo> {
  const detected = await detectLayout();
  return {
    ...parseUserAgent(navigator.userAgent),
    layout: (detected ?? selfReportedLayout ?? "unknown").slice(0, 32),
    layout_source: detected ? "api" : selfReportedLayout ? "self_report" : "unknown",
    keyboard_type: keyboardType,
    screen_w: screen.width,
    screen_h: screen.height,
    dpr_x100: Math.round(devicePixelRatio * 100),
  };
}
