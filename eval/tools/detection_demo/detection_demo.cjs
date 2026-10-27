// Detection demo (D-038), SYNTHETIC: two scripted typists with different rhythms go through the
// real app (practice x3 -> baseline check -> exam) and the real keystroke model judges the result.
// It shows the mechanism works end to end. It is not an accuracy measurement: scripted typists
// are not people, and three runs are not a sample.
//
// Needs the app running (scripts\dev.ps1) with the model installed. Usage:
//   node eval\tools\detection_demo\detection_demo.cjs
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { createRequire } = require("node:module");
const { chromium } = createRequire(path.join(__dirname, "..", "..", "..", "frontend", "package.json"))("playwright");

const BASE = process.env.APP_URL || "http://127.0.0.1:5173";
// Numbers come from the reviewer report: participants' own reports carry no distances or thresholds.
const SECRETS = process.env.INTEGRITY_SECRETS_DIR || path.join(os.homedir(), ".integrity-exam", "secrets");
const REVIEWER_TOKEN = fs.readFileSync(path.join(SECRETS, "reviewer_token.txt"), "utf8").trim();
const EXAM = "def rle(s):\n    out = []\n    i = 0\n    while i < len(s):\n        j = i\n        while j < len(s) and s[j] == s[i]:\n            j += 1\n        out.append(s[i] + str(j - i))\n        i = j\n    return ''.join(out)\n";

// Typist profiles: key hold and key-to-key gap (ms), log-normal-ish jitter, occasional pauses.
const TYPISTS = {
  A: { hold: 70, holdJitter: 20, gap: 110, gapJitter: 0.45, pauseP: 0.03, pauseMs: 700 },
  B: { hold: 165, holdJitter: 35, gap: 290, gapJitter: 0.35, pauseP: 0.08, pauseMs: 1600 },
};
let seed = 11;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
const SHIFTED = new Set([..."()_:\"+<>{}!@#$%^&*?|~ABCDEFGHIJKLMNOPQRSTUVWXYZ"]);

async function typeAs(page, typist, text) {
  const t = TYPISTS[typist];
  for (const ch of text) {
    const hold = Math.max(25, t.hold + t.holdJitter * gauss());
    if (SHIFTED.has(ch)) {
      await page.keyboard.down("Shift");
      await page.keyboard.down(ch);
      await page.waitForTimeout(hold);
      await page.keyboard.up(ch);
      await page.keyboard.up("Shift");
    } else {
      const key = ch === " " ? "Space" : ch;
      await page.keyboard.down(key);
      await page.waitForTimeout(hold);
      await page.keyboard.up(key);
    }
    const gap = t.gap * Math.exp(t.gapJitter * gauss()) + (rnd() < t.pauseP ? t.pauseMs : 0);
    await page.waitForTimeout(Math.max(0, gap - hold));
  }
}

async function typeCode(page, typist, code) {
  await page.locator(".monaco-editor .view-lines").click();
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Delete");
  const lines = code.replace(/\n$/, "").split("\n");
  const ind = (l) => l.length - l.trimStart().length;
  for (const [i, line] of lines.entries()) {
    if (i > 0) {
      await page.keyboard.press("Enter");
      const prev = lines[i - 1];
      const auto = ind(prev) + (prev.trimEnd().endsWith(":") ? 4 : 0);
      for (let k = 0; k < (auto - ind(line)) / 4; k++) await page.keyboard.press("Backspace");
    }
    await typeAs(page, typist, line.trimStart());
  }
}

async function task(page, problem, typist) {
  await page.click(`button[data-problem="${problem}"]`);
  await page.waitForURL(/#\/session\//);
  await page.waitForFunction(() => document.querySelector("#status")?.textContent === "open");
  const code = problem === "exam_run_length" ? EXAM : await page.textContent("#reference-code");
  await typeCode(page, typist, code);
  await page.click("#test");
  await page.waitForFunction(() => /\d\/3 tests passed/.test(document.querySelector("#output")?.textContent || ""), null, { timeout: 180_000 });
  await page.click("#submit");
  await page.waitForURL(/#\/done\//);
}

async function scenario(name, who) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    await page.goto(BASE + "/");
    await page.check("#age");
    await page.check("#agree");
    await page.click("#consent-continue");
    await page.waitForURL(/#\/setup/);
    const pseudonym = (await page.textContent("#pseudonym")).trim();
    for (const p of ["practice_sum_evens", "practice_word_count", "practice_letter_grade"]) {
      await task(page, p, who.practice);
      await page.click("#another-task");
    }
    await task(page, "check_count_vowels", who.check);
    await page.click("#another-task");
    await task(page, "exam_run_length", who.exam);
    const report = await page.evaluate(async ([p, tok]) =>
      (await fetch(`/api/participants/${encodeURIComponent(p)}/report`, { headers: { Authorization: `Bearer ${tok}` } })).json(),
    [pseudonym, REVIEWER_TOKEN]);
    await page.click("#see-report");
    await page.waitForSelector("#overall-verdict");
    await page.screenshot({ path: path.join(process.env.DEMO_OUT || ".", `detection-${name}.png`), fullPage: true });
    const ks = report.exams[0].keystroke;
    const kf = report.exams[0].findings.find((f) => f.id === "keystroke");
    console.log(`\n== Scenario ${name}: practice ${who.practice}, check ${who.check}, exam ${who.exam}`);
    console.log(`baseline: ${report.baseline.status}, ${report.baseline.windows} windows`);
    console.log(`check:    ${report.baseline.check.status}  distances ${JSON.stringify(report.baseline.check.windows || [])}  ` +
      `reference line ${report.baseline.check.population_threshold ?? "-"}  personal line ${report.baseline.check.personal_threshold ?? "-"}`);
    console.log(`exam:     keystroke ${kf.status}` + (ks.available ? `  distances ${JSON.stringify(ks.windows.map((w) => w.distance))}  line used ${ks.threshold}` : ""));
    console.log(`overall:  ${report.overall.state}`);
  } finally {
    await browser.close();
  }
}

(async () => {
  await scenario("A_same_typist", { practice: "A", check: "A", exam: "A" });
  await scenario("B_other_typist_in_exam", { practice: "A", check: "A", exam: "B" });
  await scenario("C_other_typist_in_check", { practice: "A", check: "B", exam: "A" });
})().catch((e) => { console.error(e); process.exit(1); });
