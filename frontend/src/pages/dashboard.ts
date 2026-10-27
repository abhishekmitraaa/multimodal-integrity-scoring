// Reviewer dashboard (D-036, D-039): every participant, their progress, their evidence report, and
// the reviewer's decision. Staff token required; every read and decision is access-logged on the server.

import { api, type DecisionKind, type ExamReport, type ParticipantSummary } from "../api";
import { h } from "../dom";
import { DECISION_TEXT, renderReport } from "../report/render";
import { store } from "../state";

function progress(p: ParticipantSummary): string {
  const done = (stage: string) => p.sessions.filter((s) => s.stage === stage && s.closed).length;
  return `${done("baseline")} practice · ${done("check") ? "check ✓" : "no check"} · ${done("exam")} exam`;
}

/** The current decision on the participant's submitted exams, or what is still open. */
function decisionCell(p: ParticipantSummary): string {
  const exams = p.sessions.filter((s) => s.stage === "exam" && s.closed);
  if (!exams.length) return "–";
  const decided = exams.filter((s) => s.decision);
  if (!decided.length) return "Not reviewed";
  const text = decided.map((s) => DECISION_TEXT[s.decision as DecisionKind]).join(", ");
  return decided.length < exams.length ? `${text} (+${exams.length - decided.length} not reviewed)` : text;
}

/** The exam's hash-chain check (SPEC 11 decision panel). It shows tampering after the server
 *  received the events, not forgery in the browser before sending (D-026). */
function chainStatus(ex: ExamReport, token: string): HTMLElement {
  const el = h("p", { class: "chain muted", id: `chain-${ex.session_id.slice(0, 8)}` }, "Checking the event log's hash chain…");
  void api.staff.verify(ex.session_id, token).then(
    (v) => {
      el.className = v.ok ? "chain chain-ok" : "chain chain-broken";
      el.textContent = v.ok
        ? `Event log intact: hash chain verified over ${v.n_events} events. (This shows changes after the server received them, not what the browser sent.)`
        : `Event log BROKEN at event ${v.first_bad_index}: ${v.reason}. Do not rely on this exam's evidence; tell the admin.`;
    },
    (err) => { el.className = "chain error"; el.textContent = `Could not check the hash chain: ${String(err)}`; },
  );
  return el;
}

/** Decision form under a submitted exam. Notes are required; a new decision supersedes, never edits. */
function decisionForm(ex: ExamReport, token: () => string, reopen: () => Promise<void>): HTMLElement {
  const short = ex.session_id.slice(0, 8);
  const choice = h("select", { id: `decision-${short}` },
    h("option", { value: "" }, "Choose a decision…"),
    ...(["dismiss", "inconclusive", "confirm"] as const).map((d) => h("option", { value: d }, DECISION_TEXT[d]))) as HTMLSelectElement;
  const notes = h("textarea", { id: `decision-notes-${short}`, rows: 3, cols: 60, maxlength: 4000,
    placeholder: "What you looked at and why you decided this (at least 10 characters)." }) as HTMLTextAreaElement;
  const error = h("p", { class: "error" });
  const save = async () => {
    error.textContent = "";
    if (!choice.value) { error.textContent = "Choose a decision."; return; }
    if (notes.value.trim().length < 10) { error.textContent = "Write at least 10 characters of notes."; return; }
    try {
      await api.staff.decide(ex.session_id, choice.value as DecisionKind, notes.value.trim(), token());
      await reopen();
    } catch (err) {
      error.textContent = String(err);
    }
  };
  return h("div", { class: "review-form" },
    h("label", { for: `decision-${short}` }, (ex.decisions?.length ? "Record a new decision" : "Record a decision")),
    h("div", { class: "row" }, choice),
    notes,
    h("p", { class: "muted" }, "Decisions are kept permanently with your name and notes; a later decision supersedes but does not erase an earlier one. "
      + "The participant sees the outcome and date, not your notes."),
    h("button", { class: "primary", id: `decision-save-${short}`, onclick: () => void save() }, "Save decision"),
    error,
  );
}

export function dashboardPage(root: HTMLElement, params: URLSearchParams): void {
  const tokenInput = h("input", { type: "password", id: "dash-token", placeholder: "Reviewer token", size: 40 }) as HTMLInputElement;
  tokenInput.value = store.staffToken() ?? "";
  const error = h("p", { class: "error", id: "dash-error" });
  const list = h("section", { id: "dash-list" });
  const detail = h("section", { id: "dash-report" });
  const audit = h("section", { id: "dash-audit" });

  const openReport = async (pseudonym: string, scroll = true): Promise<void> => {
    detail.replaceChildren(h("p", { class: "muted" }, "Building the report…"));
    try {
      const report = await api.staff.report(pseudonym, tokenInput.value);
      detail.replaceChildren(renderReport(report, {
        replayLink: (sid) => `#/replay?session=${sid}`,
        reviewExtra: (ex) => h("div", {},
          chainStatus(ex, tokenInput.value),
          decisionForm(ex, () => tokenInput.value, async () => {
            await openReport(pseudonym, false);
            await loadList(false);
          })),
      }));
      history.replaceState(null, "", `#/dashboard?p=${encodeURIComponent(pseudonym)}`);
      if (scroll) detail.scrollIntoView({ block: "start" });
    } catch (err) {
      detail.replaceChildren(h("p", { class: "error" }, String(err)));
    }
  };

  const loadList = async (openWanted: boolean): Promise<void> => {
    const participants = await api.staff.participants(tokenInput.value);
    list.replaceChildren(
      h("table", { class: "participants" },
        h("thead", {}, h("tr", {}, h("th", {}, "Participant"), h("th", {}, "Kind"), h("th", {}, "Submitted"), h("th", {}, "Decision"),
          h("th", {}, "Started"), h("th", {}, ""))),
        h("tbody", {}, ...participants.map((p) => h("tr", { "data-pseudonym": p.pseudonym },
          h("td", {}, h("code", {}, p.pseudonym)), h("td", {}, p.kind), h("td", {}, progress(p)),
          h("td", { class: "decision-cell" }, decisionCell(p)),
          h("td", {}, new Date(p.created_at).toLocaleString()),
          h("td", {}, h("button", { class: "link", onclick: () => void openReport(p.pseudonym) }, "Open report")))))),
      ...(participants.length ? [] : [h("p", { class: "muted" }, "No participants yet.")]),
    );
    const wanted = params.get("p");
    if (openWanted && wanted) await openReport(wanted);
  };

  const load = async () => {
    store.setStaffToken(tokenInput.value);
    error.textContent = "";
    try {
      await loadList(true);
    } catch (err) {
      error.textContent = String(err);
    }
  };

  const loadAudit = async () => {
    audit.replaceChildren(h("p", { class: "muted" }, "Loading the access log…"));
    try {
      const entries = await api.staff.accessLog(tokenInput.value);
      audit.replaceChildren(
        h("h2", {}, "Access log"),
        h("p", { class: "muted" }, `The latest ${entries.length} entries, newest first. Reading this log is itself logged.`),
        h("table", { class: "participants", id: "audit-table" },
          h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Who"), h("th", {}, "Role"), h("th", {}, "Action"), h("th", {}, "Target"))),
          h("tbody", {}, ...entries.map((e) => h("tr", {},
            h("td", {}, new Date(e.at).toLocaleString()), h("td", {}, e.actor), h("td", {}, e.role),
            h("td", {}, h("code", {}, e.action)), h("td", {}, h("code", {}, e.target)))))),
      );
    } catch (err) {
      audit.replaceChildren(h("p", { class: "error", id: "audit-error" },
        String(err).includes(": 403 ") ? "The access log needs the admin token." : String(err)));
    }
  };

  root.replaceChildren(
    h("main", { class: "dashboard" },
      h("h1", {}, "Reviewer dashboard"),
      h("p", { class: "muted" }, "Pseudonymous data. Every read is recorded in the access log. A flag means a person should look; it is never a finding of misconduct."),
      h("div", { class: "row" }, tokenInput,
        h("button", { id: "dash-load", class: "primary", onclick: () => void load() }, "Load participants"),
        h("button", { id: "dash-audit-load", onclick: () => void loadAudit() }, "Access log (admin)")),
      error, list, detail, audit,
    ),
  );
  if (tokenInput.value) void load();
}
