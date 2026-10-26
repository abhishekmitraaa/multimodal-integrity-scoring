// Evidence report view (D-036), shared by the reviewer dashboard and the participant's own page.
// It shows evidence with plain verdicts. There is no single integrity score: that needs a fusion
// model fitted on labelled study data (P3, after data collection).

import type { ExamReport, Finding, HabitValues, Report, ReportState } from "../api";
import { h } from "../dom";

const STATE_TEXT: Record<ReportState, [string, string]> = {
  review: ["Review recommended", "At least one piece of evidence needs a person to look at it. This is not a finding of misconduct."],
  insufficient_data: ["Not enough data", "The typing check could not run, and nothing else needs review."],
  no_review_flags: ["No review flags", "Nothing in the evidence needs review. This does not certify the work."],
  no_exam_yet: ["No exam yet", "The baseline is being built from practice tasks. The exam is checked against it once it is submitted."],
};
const STATUS_ICON: Record<Finding["status"], string> = { flag: "⚠", ok: "✓", info: "ℹ", unavailable: "–" };
const SVG = "http://www.w3.org/2000/svg";

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>, text?: string): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (text !== undefined) el.textContent = text;
  return el;
}

function fmt(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? "–" : v.toFixed(digits);
}

function verdict(state: ReportState, reasons: string[], id: string): HTMLElement {
  const [title, sub] = STATE_TEXT[state];
  return h("section", { class: `verdict verdict-${state}`, id },
    h("strong", { class: "verdict-title" }, title),
    h("p", {}, sub),
    reasons.length ? h("ul", { class: "reasons" }, ...reasons.map((r) => h("li", {}, r))) : null,
  );
}

/** Keystroke distance per exam window against the same-person 95% line, with paste markers. */
function keystrokeChart(ex: ExamReport): Element | null {
  if (!ex.keystroke.available || ex.keystroke.windows.length === 0) return null;
  const k = ex.keystroke;
  const W = 640, H = 190, L = 44, R = 12, T = 12, B = 26;
  const tMax = Math.max(ex.duration_s, ...k.windows.map((w) => w.t), 1);
  const dMax = Math.max(k.threshold * 1.25, k.eer_threshold * 1.1, ...k.windows.map((w) => w.distance)) * 1.05;
  const x = (t: number) => L + (t / tMax) * (W - L - R);
  const y = (d: number) => T + (1 - d / dMax) * (H - T - B);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "ks-chart", role: "img",
    "aria-label": `Typing distance from baseline over ${k.windows.length} windows` });
  root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "axis" }));
  for (let t = 0; t <= tMax; t += tMax > 180 ? 60 : 30) {
    root.append(svg("text", { x: x(t), y: H - 8, class: "tick", "text-anchor": "middle" }, `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}`));
  }
  for (const p of ex.pastes) {
    root.append(svg("line", { x1: x(p.t), x2: x(p.t), y1: T, y2: H - B, class: p.provenance === "external" ? "mark-external" : "mark-internal" }));
  }
  root.append(svg("line", { x1: L, x2: W - R, y1: y(k.threshold), y2: y(k.threshold), class: "line-threshold" }));
  root.append(svg("text", { x: L + 4, y: y(k.threshold) - 4, class: "tick" }, "same-person 95%"));
  root.append(svg("text", { x: 4, y: y(0) - 2, class: "tick" }, "0"));
  root.append(svg("text", { x: 4, y: y(k.threshold) + 4, class: "tick" }, k.threshold.toFixed(2)));
  const pts = k.windows.map((w) => `${x(w.t)},${y(w.distance)}`).join(" ");
  root.append(svg("polyline", { points: pts, class: "ks-line" }));
  for (const w of k.windows) {
    root.append(svg("circle", { cx: x(w.t), cy: y(w.distance), r: 4, class: w.distance > k.threshold ? "pt-above" : "pt-below" }));
  }
  return root;
}

function habitsTable(base: HabitValues | null, exam: HabitValues | null): HTMLElement {
  const rows: Array<[string, keyof HabitValues, number, string]> = [
    ["Typing speed (characters per active minute)", "chars_per_minute", 0, ""],
    ["Key-interval spread (0 = machine-even)", "interval_cv", 2, ""],
    ["Share of pauses over 2 s", "pause_share_2s", 2, ""],
    ["Corrections per 100 characters", "revisions_per_100", 1, ""],
  ];
  return h("table", { class: "habits" },
    h("thead", {}, h("tr", {}, h("th", {}, "Typing habit"), h("th", {}, "Practice (baseline)"), h("th", {}, "Exam"))),
    h("tbody", {}, ...rows.map(([label, key, d]) => h("tr", {},
      h("td", {}, label), h("td", {}, fmt(base?.[key] as number | null, d)), h("td", {}, fmt(exam?.[key] as number | null, d))))),
  );
}

function examSection(ex: ExamReport, replayLink?: (sessionId: string) => string): HTMLElement {
  const chart = keystrokeChart(ex);
  return h("section", { class: "exam-report", "data-session": ex.session_id },
    h("h2", {}, `Exam: ${ex.problem_id}`, h("span", { class: "muted" },
      ` · ${Math.floor(ex.duration_s / 60)}:${String(ex.duration_s % 60).padStart(2, "0")}${ex.closed ? "" : " · not submitted yet"}`)),
    verdict(ex.state, [], `exam-verdict-${ex.session_id.slice(0, 8)}`),
    h("ul", { class: "findings" }, ...ex.findings.map((f) =>
      h("li", { class: `finding finding-${f.status}`, "data-finding": f.id },
        h("span", { class: "finding-icon", "aria-hidden": "true" }, STATUS_ICON[f.status]),
        h("div", {}, h("strong", {}, f.title), h("p", {}, f.detail))))),
    chart ? h("figure", { class: "chart-figure" }, chart,
      h("figcaption", { class: "muted" },
        "Each dot is a window of 70 key presses: its distance from this person's practice typing (lower = more alike). ",
        "Above the dashed line is further than 95% of same-person comparisons in the reference data. ",
        "Red lines: pastes from outside the editor; blue: pastes from inside it.")) : null,
    h("h3", {}, "Typing habits"),
    habitsTable(ex.habits.baseline, ex.habits.exam),
    replayLink ? h("p", {}, h("a", { href: replayLink(ex.session_id) }, "Replay this exam keystroke by keystroke")) : null,
  );
}

export function renderReport(r: Report, opts: { replayLink?: (sessionId: string) => string } = {}): HTMLElement {
  const b = r.baseline;
  const baselineText = b.status === "ready"
    ? `Ready: ${b.windows} windows of typing from ${b.practice_sessions.length} practice task(s).`
    : b.status === "insufficient"
      ? `Not enough yet: ${b.windows} of ${b.windows_needed} windows of typing. Finish more practice tasks.`
      : "No practice task submitted yet.";
  return h("article", { class: "report", id: "report" },
    h("header", {}, h("h1", {}, `Report: ${r.pseudonym}`), h("p", { class: "muted" }, `Generated ${new Date(r.generated_at).toLocaleString()}`)),
    verdict(r.overall.state, r.overall.reasons, "overall-verdict"),
    h("section", { class: "baseline", id: "baseline" },
      h("h2", {}, "Baseline (practice)"),
      h("p", { id: "baseline-status" }, baselineText),
      b.practice_sessions.length ? h("ul", {}, ...b.practice_sessions.map((p) =>
        h("li", {}, `${p.problem_id}: ${p.keystrokes} key presses, ${p.windows} window(s)`))) : null,
      h("p", { class: "muted" }, b.note),
    ),
    ...r.exams.map((ex) => examSection(ex, opts.replayLink)),
    h("section", { class: "report-notes" },
      h("p", {}, h("strong", {}, "No single score. "), r.no_score_note),
      h("p", {}, h("strong", {}, "False flags. "), r.false_flag_note),
      r.model.available ? h("p", { class: "muted" }, r.model.note) : h("p", { class: "error" }, `Keystroke model: ${r.model.note}`),
    ),
  );
}
