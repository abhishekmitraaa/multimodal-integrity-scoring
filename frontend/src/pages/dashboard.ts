// Reviewer dashboard (D-036): every participant, their progress, and their evidence report.
// Staff token required; every read is access-logged on the server.

import { api, type ParticipantSummary } from "../api";
import { h } from "../dom";
import { renderReport } from "../report/render";
import { store } from "../state";

function progress(p: ParticipantSummary): string {
  const done = (kind: string) => p.sessions.filter((s) => s.kind === kind && s.closed).length;
  return `${done("practice")} practice · ${done("exam")} exam`;
}

export function dashboardPage(root: HTMLElement, params: URLSearchParams): void {
  const tokenInput = h("input", { type: "password", id: "dash-token", placeholder: "Reviewer token", size: 40 }) as HTMLInputElement;
  tokenInput.value = store.staffToken() ?? "";
  const error = h("p", { class: "error", id: "dash-error" });
  const list = h("section", { id: "dash-list" });
  const detail = h("section", { id: "dash-report" });

  const openReport = async (pseudonym: string) => {
    detail.replaceChildren(h("p", { class: "muted" }, "Building the report…"));
    try {
      const report = await api.staff.report(pseudonym, tokenInput.value);
      detail.replaceChildren(renderReport(report, { replayLink: (sid) => `#/replay?session=${sid}` }));
      history.replaceState(null, "", `#/dashboard?p=${encodeURIComponent(pseudonym)}`);
      detail.scrollIntoView({ block: "start" });
    } catch (err) {
      detail.replaceChildren(h("p", { class: "error" }, String(err)));
    }
  };

  const load = async () => {
    store.setStaffToken(tokenInput.value);
    error.textContent = "";
    try {
      const participants = await api.staff.participants(tokenInput.value);
      list.replaceChildren(
        h("table", { class: "participants" },
          h("thead", {}, h("tr", {}, h("th", {}, "Participant"), h("th", {}, "Kind"), h("th", {}, "Submitted"), h("th", {}, "Started"), h("th", {}, ""))),
          h("tbody", {}, ...participants.map((p) => h("tr", { "data-pseudonym": p.pseudonym },
            h("td", {}, h("code", {}, p.pseudonym)), h("td", {}, p.kind), h("td", {}, progress(p)),
            h("td", {}, new Date(p.created_at).toLocaleString()),
            h("td", {}, h("button", { class: "link", onclick: () => void openReport(p.pseudonym) }, "Open report")))))),
        ...(participants.length ? [] : [h("p", { class: "muted" }, "No participants yet.")]),
      );
      const wanted = params.get("p");
      if (wanted) await openReport(wanted);
    } catch (err) {
      error.textContent = String(err);
    }
  };

  root.replaceChildren(
    h("main", { class: "dashboard" },
      h("h1", {}, "Reviewer dashboard"),
      h("p", { class: "muted" }, "Pseudonymous data. Every read is recorded in the access log. A flag means a person should look; it is never a finding of misconduct."),
      h("div", { class: "row" }, tokenInput, h("button", { id: "dash-load", class: "primary", onclick: () => void load() }, "Load participants")),
      error, list, detail,
    ),
  );
  if (tokenInput.value) void load();
}
