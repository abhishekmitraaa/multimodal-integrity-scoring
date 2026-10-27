// Scripted attacks A2, A3a, A3b (SPEC 12.2, D-046): real browser keyboard input, driven by Playwright,
// typing the frozen study material into an exam session created for a study participant.
//
//   A2   constant-rate auto-typer (config/study.yaml a2)
//   A3a  auto-typer with jitter from population-like log-normal distributions (a3a)
//   A3b  auto-typer resampling THIS participant's own practice flights and holds (consented, SPEC 10.3)
//
// The session is labelled scripted, with the onset at the session start; reviewers never see the label.
// Needs the app running (scripts\dev.ps1) and an admin token. Usage:
//   node eval\tools\attack_runner\attack_runner.cjs --pseudonym P-XXXXXXXX --problem exam_balanced --condition A3b
//   [--browser firefox|chromium] [--seed 1]
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { createRequire } = require("node:module");

const ROOT = path.join(__dirname, "..", "..", "..");
const SHIFTED = new Set([..."()_:\"+<>{}!@#$%^&*?|~ABCDEFGHIJKLMNOPQRSTUVWXYZ"]);

/** The flow-style maps of config/study.yaml (a2, a3a, a3b) as numbers; no YAML parser needed. */
function studyConfig() {
  const text = fs.readFileSync(path.join(ROOT, "config", "study.yaml"), "utf8");
  const out = {};
  for (const key of ["a2", "a3a", "a3b"]) {
    const m = text.match(new RegExp(`^${key}:\\s*\\{([^}]*)\\}`, "m"));
    if (!m) throw new Error(`config/study.yaml: ${key} not found`);
    out[key] = Object.fromEntries(m[1].split(",").map((kv) => kv.split(":").map((s) => s.trim())).map(([k, v]) => [k, Number(v)]));
  }
  return out;
}

function rng(seed) {
  let s = seed % 2147483647 || 1;
  const uniform = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const gauss = () => Math.sqrt(-2 * Math.log(uniform() + 1e-12)) * Math.cos(2 * Math.PI * uniform());
  return { uniform, gauss };
}

/** (flight seconds, hold seconds) for the next key, per condition. */
function timing(condition, cfg, own, r) {
  if (condition === "A2") {
    const j = cfg.a2.jitter;
    return [cfg.a2.flight_ms * (1 + j * (2 * r.uniform() - 1)) / 1000, cfg.a2.hold_ms * (1 + j * (2 * r.uniform() - 1)) / 1000];
  }
  if (condition === "A3a") {
    return [cfg.a3a.flight_median_ms * Math.exp(cfg.a3a.flight_log_sd * r.gauss()) / 1000,
      cfg.a3a.hold_median_ms * Math.exp(cfg.a3a.hold_log_sd * r.gauss()) / 1000];
  }
  if (condition === "A3b") {
    if (!own.flights_s.length || !own.holds_s.length) throw new Error("A3b needs the participant's practice typing");
    const pick = (xs) => xs[Math.floor(r.uniform() * xs.length)];
    return [pick(own.flights_s), pick(own.holds_s)];
  }
  throw new Error(`not a scripted condition: ${condition}`);
}

async function key(page, ch, hold) {
  const name = ch === " " ? "Space" : ch === "\n" ? "Enter" : ch;
  if (SHIFTED.has(ch)) await page.keyboard.down("Shift");
  await page.keyboard.down(name);
  await page.waitForTimeout(hold);
  await page.keyboard.up(name);
  if (SHIFTED.has(ch)) await page.keyboard.up("Shift");
}

/** Types code as the editor expects (it auto-indents after Enter), every key timed by the condition. */
async function typeCode(page, code, next) {
  await page.locator(".monaco-editor .view-lines").click();
  const mod = await page.evaluate(() => (/Mac/.test(navigator.userAgent) ? "Meta" : "Control"));
  await page.keyboard.press(`${mod}+A`);
  await page.keyboard.press("Delete");
  const lines = code.replace(/\n$/, "").split("\n");
  const ind = (l) => l.length - l.trimStart().length;
  const press = async (ch) => {
    const [flight, hold] = next();
    await key(page, ch, Math.max(5, hold * 1000));
    await page.waitForTimeout(Math.max(0, (flight - hold) * 1000));
  };
  for (const [i, line] of lines.entries()) {
    if (i > 0) {
      await press("\n");
      const prev = lines[i - 1];
      const auto = ind(prev) + (prev.trimEnd().endsWith(":") ? 4 : 0);
      for (let k = 0; k < (auto - ind(line)) / 4; k++) await press("Backspace");
    }
    for (const ch of line.trimStart()) await press(ch);
  }
}

async function api(base, pathname, token, body) {
  const res = await fetch(base + pathname, {
    method: body ? "POST" : "GET",
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${pathname}: ${res.status} ${await res.text()}`);
  return res.json();
}

/**
 * Runs one scripted session in `page`. Returns { session_id, condition, keys }.
 * apiBase: where /api lives (the app's origin works, Vite proxies it); appBase: the web app.
 */
async function runScripted({ page, apiBase, appBase, adminToken, pseudonym, problem, condition, seed = 1 }) {
  const cfg = studyConfig();
  const own = condition === "A3b" ? await api(apiBase, `/api/admin/participants/${encodeURIComponent(pseudonym)}/timing`, adminToken) : null;
  const s = await api(apiBase, "/api/admin/scripted-session", adminToken, { pseudonym, problem_id: problem, condition });
  const r = rng(seed);
  // The session page reads its session and participant from this tab's storage; the participant token is
  // not needed (and not known to the researcher): the scripted session is not one of the participant's slots.
  await page.addInitScript(([sid, token, problemId, who]) => {
    sessionStorage.setItem("participant", JSON.stringify({ pseudonym: who, token: "", kind: "dev" }));
    sessionStorage.setItem("sessions", JSON.stringify({ [sid]: { token, problemId, kind: "exam" } }));
  }, [s.session_id, s.session_token, problem, pseudonym]);
  await page.goto(`${appBase}/#/session/${s.session_id}`);
  await page.locator("#status").filter({ hasText: "open" }).waitFor({ timeout: 60_000 });
  let keys = 0;
  await typeCode(page, s.text, () => (keys++, timing(condition, cfg, own, r)));
  await page.click("#test");
  await page.locator("#output").filter({ hasText: /tests passed/ }).waitFor({ timeout: 120_000 });
  await page.click("#submit");
  await page.waitForURL(/#\/done\//, { timeout: 60_000 });
  return { session_id: s.session_id, condition, keys };
}

module.exports = { runScripted, studyConfig, timing, rng };

if (require.main === module) {
  const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
  for (const k of ["pseudonym", "problem", "condition"]) if (!args[k]) throw new Error(`--${k} is required`);
  const secrets = process.env.INTEGRITY_SECRETS_DIR || path.join(os.homedir(), ".integrity-exam", "secrets");
  const adminToken = process.env.ADMIN_TOKEN || fs.readFileSync(path.join(secrets, "admin_token.txt"), "utf8").trim();
  const app = process.env.APP_URL || "http://127.0.0.1:5173";
  const pw = createRequire(path.join(ROOT, "frontend", "package.json"))("playwright");
  (async () => {
    const browser = await pw[args.browser || "chromium"].launch();
    try {
      const page = await (await browser.newContext()).newPage();
      const out = await runScripted({ page, apiBase: app, appBase: app, adminToken, pseudonym: args.pseudonym,
        problem: args.problem, condition: args.condition, seed: Number(args.seed || 1) });
      console.log(`scripted ${out.condition} session ${out.session_id}: ${out.keys} keys typed and submitted`);
    } finally {
      await browser.close();
    }
  })().catch((err) => { console.error(String(err)); process.exit(1); });
}
