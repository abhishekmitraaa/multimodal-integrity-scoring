// Evidence report view (D-036), shared by the reviewer dashboard and the participant's own page.
// It shows evidence with plain verdicts. There is no single integrity score: that needs a fusion
// model fitted on labelled study data (P3, after data collection).

import type { DecisionKind, ExamReport, Finding, HabitValues, HeadMovementDemo, Report, ReportState } from "../api";
import { h } from "../dom";

const STATE_TEXT: Record<ReportState, [string, string]> = {
  review: ["Review recommended", "At least one piece of evidence needs a person to look at it. This is not a finding of misconduct."],
  insufficient_data: ["Not enough data", "The typing check could not run, and nothing else needs review."],
  no_review_flags: ["No review flags", "Nothing in the evidence needs review. This does not certify the work."],
  no_exam_yet: ["No exam yet", "The baseline is being built from practice tasks. The exam is checked against it once it is submitted."],
};
const CHECK_TEXT: Record<Report["baseline"]["check"]["status"], string> = {
  confirmed: "Baseline check: confirmed.",
  not_confirmed: "Baseline check: does not match.",
  not_done: "Baseline check: not done yet.",
  unavailable: "Baseline check: could not run.",
};
export const DECISION_TEXT: Record<DecisionKind, string> = {
  confirm: "Concern confirmed",
  dismiss: "Dismissed: no concern",
  inconclusive: "Inconclusive",
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
  const dMax = Math.max(k.threshold * 1.25, k.eer_threshold * 1.1, ...k.windows.map((w) => w.distance)) * 1.05;   // threshold = the line used
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
  for (const j of ex.ast_jumps ?? []) {
    root.append(svg("line", { x1: x(j.t), x2: x(j.t), y1: T, y2: H - B, class: "mark-ast" }));
  }
  root.append(svg("line", { x1: L, x2: W - R, y1: y(k.population_threshold), y2: y(k.population_threshold), class: "line-threshold" }));
  root.append(svg("text", { x: L + 4, y: y(k.population_threshold) - 4, class: "tick" }, "same-person 95% (reference data)"));
  if (k.personal_threshold !== null && k.personal_threshold > k.population_threshold) {
    root.append(svg("line", { x1: L, x2: W - R, y1: y(k.personal_threshold), y2: y(k.personal_threshold), class: "line-personal" }));
    root.append(svg("text", { x: W - R - 4, y: y(k.personal_threshold) - 4, class: "tick", "text-anchor": "end" }, "this person's normal range (baseline check)"));
  }
  root.append(svg("text", { x: 4, y: y(0) - 2, class: "tick" }, "0"));
  root.append(svg("text", { x: 4, y: y(k.threshold) + 4, class: "tick" }, k.threshold.toFixed(2)));
  const pts = k.windows.map((w) => `${x(w.t)},${y(w.distance)}`).join(" ");
  root.append(svg("polyline", { points: pts, class: "ks-line" }));
  for (const w of k.windows) {
    root.append(svg("circle", { cx: x(w.t), cy: y(w.distance), r: 4, class: w.distance > k.threshold ? "pt-above" : "pt-below" }));   // vs the line used
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

/** The webcam recording (D-048): loaded on request, with the admin token. Not analysed. */
function videoSection(ex: ExamReport, loadVideo?: (sessionId: string) => Promise<Blob>): HTMLElement | null {
  if (!ex.video?.available) return null;
  const holder = h("div", { class: "video-holder" });
  const load = h("button", { id: `video-load-${ex.session_id.slice(0, 8)}` }, "Load the video (admin)");
  load.addEventListener("click", async () => {
    load.setAttribute("disabled", "");
    try {
      const blob = await loadVideo!(ex.session_id);
      const player = h("video", { controls: true, class: "webcam-player", id: `video-${ex.session_id.slice(0, 8)}` }) as HTMLVideoElement;
      player.src = URL.createObjectURL(blob);
      holder.replaceChildren(player);
    } catch (err) {
      load.removeAttribute("disabled");
      holder.replaceChildren(h("p", { class: "error" }, String(err).replace(/^Error: /, "")));
    }
  });
  return h("section", { class: "video-section", "data-session": ex.session_id },
    h("h3", {}, "Webcam recording"),
    h("p", { class: "muted" }, `About ${ex.video.approx_seconds} s, ${ex.video.chunks} part(s). A demo feature: the video is stored encrypted, `,
      "only an admin can view it, every viewing is logged, and nothing analyses it."),
    loadVideo ? load : null, holder);
}

/** The head-movement panel (D-048): a video demonstration with example numbers, said on the panel itself. */
function headDemoPanel(d: HeadMovementDemo | undefined): HTMLElement | null {
  if (!d) return null;
  const W = 640, H = 160, L = 40, T = 10, B = 24;
  const tMax = Math.max(1, ...d.samples.map((s) => s.t));
  const x = (t: number) => L + (t / tMax) * (W - L - 8);
  const y = (yaw: number) => T + (1 - (Math.max(-70, Math.min(70, yaw)) + 70) / 140) * (H - T - B);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "head-chart", role: "img", "aria-label": "Example head turn over time (video demonstration)" });
  chart.append(svg("rect", { x: L, y: y(30), width: W - L - 8, height: y(-30) - y(30), class: "head-band" }));
  chart.append(svg("polyline", { points: d.samples.map((s) => `${x(s.t)},${y(s.yaw)}`).join(" "), class: "head-line" }));
  chart.append(svg("text", { x: 4, y: y(0) + 4, class: "tick" }, "0°"));
  chart.append(svg("text", { x: 4, y: y(45) + 4, class: "tick" }, "R"));
  chart.append(svg("text", { x: 4, y: y(-45) + 4, class: "tick" }, "L"));
  return h("section", { class: "head-demo", id: "head-demo" },
    h("h3", {}, "Head movement ", h("span", { class: "demo-tag" }, "Video demonstration")),
    h("p", { class: "muted demo-note" }, d.label),
    h("figure", { class: "chart-figure" }, chart,
      h("figcaption", { class: "muted" }, "Head turn left/right over the exam; the shaded band is facing the screen (within 30°).")),
    h("ul", {},
      h("li", {}, `Facing the screen: ${Math.round(d.facing_screen_share * 100)}% of the time`),
      h("li", {}, `Looks away: ${d.look_aways.length}, longest ${d.longest_look_away_s} s`)),
  );
}

/** Reviewer decisions (the last one is current) and the participant's appeals (D-039). */
function reviewSection(ex: ExamReport, extra: Node | null): HTMLElement | null {
  const decisions = ex.decisions ?? [];
  const appeals = ex.appeals ?? [];
  if (!ex.closed) return null;
  return h("section", { class: "review", id: `review-${ex.session_id.slice(0, 8)}` },
    h("h3", {}, "Human review"),
    decisions.length
      ? h("ol", { class: "decisions" }, ...decisions.map((d, i) =>
        h("li", { class: `decision decision-${d.decision}${i === decisions.length - 1 ? " decision-current" : ""}`, "data-decision": d.decision },
          h("strong", {}, DECISION_TEXT[d.decision]),
          h("span", { class: "muted" }, ` · ${new Date(d.at).toLocaleString()}${d.reviewer ? ` · ${d.reviewer}` : ""}`
            + (i === decisions.length - 1 && decisions.length > 1 ? " · current" : "")),
          d.notes ? h("p", { class: "decision-notes" }, d.notes) : null)))
      : h("p", { class: "muted", id: "no-decision" }, "No reviewer decision yet."),
    appeals.length
      ? h("div", {}, h("h4", {}, "Participant's notes"),
        h("ul", { class: "appeals" }, ...appeals.map((a) =>
          h("li", { class: "appeal" }, h("span", { class: "muted" }, new Date(a.at).toLocaleString()), h("p", {}, a.note)))))
      : null,
    extra,
  );
}

const PROCESS_LABELS: Array<[string, string]> = [
  ["linearity", "Typed at the end of the previous insertion (share)"],
  ["short_survival", "Typed characters deleted again (share)"],
  ["revision_rate", "Backspace/Delete per 100 typed characters"],
  ["ins_del_ratio", "Typed characters per deleted character"],
  ["pause_frac_200ms", "Key intervals over 200 ms (share)"],
  ["pause_frac_2s", "Key intervals over 2 s (share)"],
  ["burst_len", "Key presses per burst (median)"],
  ["pre_burst_pause", "Pause before long bursts ÷ typing interval"],
  ["speed_cv", "Typing-speed spread over 10 s bins"],
  ["flight_cv", "Key-to-key interval spread"],
  ["hold_cv", "Key hold-time spread"],
  ["edit_locality", "Lines between consecutive edits (median)"],
  ["runs_per_100", "Test runs per 100 typed characters"],
  ["edits_between_runs", "Typed characters between test runs (median)"],
];

/** Process features (SPEC 6.2) beside the practice mean, for reviewers. No thresholds yet. */
function processTable(p: NonNullable<ExamReport["process"]>): HTMLElement {
  return h("div", { class: "process", id: "process-features" },
    h("h3", {}, "How the code was written"),
    h("table", { class: "habits" },
      h("thead", {}, h("tr", {}, h("th", {}, "Process feature"), h("th", {}, "Practice (baseline)"), h("th", {}, "Exam"))),
      h("tbody", {}, ...PROCESS_LABELS.map(([key, label]) => h("tr", { "data-feature": key },
        h("td", {}, label), h("td", {}, fmt(p.baseline?.[key], 2)), h("td", {}, fmt(p.exam[key], 2)))))),
    h("p", { class: "muted" }, "Context only, with no thresholds. Practice was copy-typing, so the exam usually has more pauses, ",
      "corrections and jumps between lines. What counts as unusual needs each feature's normal spread from study data. – means not enough input."),
  );
}

function examSection(ex: ExamReport, replayLink?: (sessionId: string) => string, reviewExtra?: (ex: ExamReport) => Node | null,
  loadVideo?: (sessionId: string) => Promise<Blob>): HTMLElement {
  const chart = keystrokeChart(ex);
  return h("section", { class: "exam-report", "data-session": ex.session_id },
    h("h2", {}, `Exam: ${ex.problem_id}`, h("span", { class: "muted" },
      ` · ${Math.floor(ex.duration_s / 60)}:${String(ex.duration_s % 60).padStart(2, "0")}${ex.closed ? "" : " · not submitted yet"}`)),
    verdict(ex.state, [], `exam-verdict-${ex.session_id.slice(0, 8)}`),
    h("ul", { class: "findings" }, ...ex.findings.map((f) =>
      h("li", { class: `finding finding-${f.status}`, "data-finding": f.id },
        h("span", { class: "finding-icon", "aria-hidden": "true" }, STATUS_ICON[f.status]),
        h("div", {}, h("strong", {}, f.title), h("p", {}, f.detail))))),
    !ex.keystroke.available && ex.keystroke.redacted
      ? h("p", { class: "muted", id: "distances-redacted" },
        "The typing distances and thresholds behind this check are shown to reviewers only.")
      : null,
    chart ? h("figure", { class: "chart-figure" }, chart,
      h("figcaption", { class: "muted" },
        "Each dot is a window of 70 key presses: its distance from this person's practice typing (lower = more alike). ",
        "Dashed line: 95% of same-person comparisons in the reference data. Dotted line, when shown: this person's own ",
        "normal range from the baseline check; the higher of the two is used. ",
        "Red lines: pastes from outside the editor; blue: pastes from inside it; ",
        "purple dashes: code structure that arrived without typing.")) : null,
    h("h3", {}, "Typing habits"),
    habitsTable(ex.habits.baseline, ex.habits.exam),
    ex.process ? processTable(ex.process) : null,
    replayLink ? h("p", {}, h("a", { href: replayLink(ex.session_id) }, "Replay this exam keystroke by keystroke")) : null,
    videoSection(ex, loadVideo),
    headDemoPanel(ex.head_movement_demo),
    reviewSection(ex, ex.closed && reviewExtra ? reviewExtra(ex) : null),
  );
}

export interface RenderOptions {
  replayLink?: (sessionId: string) => string;
  /** A form under each submitted exam's review history: the decision form or the appeal form. */
  reviewExtra?: (ex: ExamReport) => Node | null;
  /** Loads a session's webcam video (D-048); the dashboard passes one using the staff token. */
  loadVideo?: (sessionId: string) => Promise<Blob>;
}

export function renderReport(r: Report, opts: RenderOptions = {}): HTMLElement {
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
      h("p", { class: `check check-${b.check.status}`, id: "baseline-check" },
        h("strong", {}, CHECK_TEXT[b.check.status] + " "), b.check.detail),
      h("p", { class: "muted" }, b.note),
    ),
    ...r.exams.map((ex) => examSection(ex, opts.replayLink, opts.reviewExtra, opts.loadVideo)),
    h("section", { class: "report-notes" },
      h("p", {}, h("strong", {}, "No single score. "), r.no_score_note),
      h("p", {}, h("strong", {}, "False flags. "), r.false_flag_note),
      r.model.available ? h("p", { class: "muted" }, r.model.note) : h("p", { class: "error" }, `Keystroke model: ${r.model.note}`),
    ),
  );
}
