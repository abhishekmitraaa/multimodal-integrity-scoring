// Drives #/keycheck?synthetic=1 in real browser windows; typing comes from OS-level SendInput (inject.ps1).
// SYNTHETIC development data (Windows only). Saves to %INTEGRITY_DATA_ROOT%\dev\keycheck-os-injected\.
// Needs `npm run dev` running. Usage: node eval/tools/os_inject/os_inject_check.cjs [edge] [chrome] [firefox]
const path = require("node:path");
const { createRequire } = require("node:module");
const { execFileSync } = require("node:child_process");
const os = require("node:os");
const fs = require("node:fs");
const req = createRequire(path.join(__dirname, "..", "..", "..", "frontend", "package.json"));
const { chromium, firefox } = req("playwright");

if (!process.env.INTEGRITY_DATA_ROOT) throw new Error("set INTEGRITY_DATA_ROOT (outside the repo)");
const OUT = path.join(process.env.INTEGRITY_DATA_ROOT, "dev", "keycheck-os-injected");
const TEXT = "the quick brown fox jumps over the lazy dog pack my box with five dozen liquor jugs";
const FLIGHT = 150, HOLD = 80;   // constant-rate auto-typer (attack A2 style)
const vkOf = (ch) => (ch === " " ? 0x20 : ch.toUpperCase().charCodeAt(0));

function typingPlan(text) {
  const plan = [];
  [...text].forEach((ch, i) => {
    plan.push({ t: 300 + i * FLIGHT, vk: vkOf(ch), up: false });
    plan.push({ t: 300 + i * FLIGHT + HOLD, vk: vkOf(ch), up: true });
  });
  return plan.sort((a, b) => a.t - b.t);
}
const holdPlan = [
  { t: 300, vk: 0x41, up: false }, { t: 1800, vk: 0x41, up: true },
  { t: 2300, vk: 0x08, up: false }, { t: 3800, vk: 0x08, up: true },
];

function inject(plan, name) {
  const file = path.join(os.tmpdir(), `keycheck-plan-${name}.json`);
  fs.writeFileSync(file, JSON.stringify(plan));
  const out = execFileSync("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(__dirname, "inject.ps1"), "-PlanFile", file], { encoding: "utf8" });
  console.log(`  ${name}: ${out.trim()}`);
  if (!out.startsWith("OK")) throw new Error(out);
}

async function runOne(label, launch) {
  console.log(label);
  const browser = await launch();
  const page = await (await browser.newContext({ acceptDownloads: true, viewport: { width: 1100, height: 800 } })).newPage();
  try {
    await page.goto("http://127.0.0.1:5173/#/keycheck?synthetic=1");
    await page.locator("#kc-editor .monaco-editor").waitFor();
    await page.fill("#kc-tester", "SYN-OSINJECT");
    await page.selectOption("#kc-keyboard", "other");
    await page.fill("#kc-keyboard-label", "SendInput, OS-injected (synthetic)");
    await page.selectOption("#kc-os", "windows");
    for (const [task, plan] of [["prose", typingPlan(TEXT)], ["hold", holdPlan], ["jank", typingPlan(TEXT)]]) {
      await page.click(`#kc-start-${task}`);
      await page.bringToFront();
      inject(plan, task);
      await page.waitForTimeout(500);
      await page.click("#kc-finish");
    }
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("#kc-download")]);
    fs.mkdirSync(OUT, { recursive: true });
    const dest = path.join(OUT, download.suggestedFilename());
    await download.saveAs(dest);
    console.log(`  saved ${dest}`);
  } finally {
    await browser.close();
  }
}

(async () => {
  const which = process.argv.slice(2);
  const all = {
    edge: () => chromium.launch({ channel: "msedge", headless: false }),
    chrome: () => chromium.launch({ channel: "chrome", headless: false }),
    firefox: () => firefox.launch({ headless: false }),
  };
  for (const name of which.length ? which : Object.keys(all)) await runOne(name, all[name]);
})().catch((e) => { console.error(e); process.exit(1); });
