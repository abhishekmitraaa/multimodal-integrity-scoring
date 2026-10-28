// The participant's own report (SPEC 10.10: participants can see their own evidence and add a note
// to any submitted exam, which the reviewer sees next to the evidence; D-039).

import { api, type ExamReport } from "../api";
import { h } from "../dom";
import { renderReport } from "../report/render";
import { store } from "../state";
import { withdrawPanel } from "./withdraw";

function appealForm(ex: ExamReport, token: string, reload: () => Promise<void>): HTMLElement {
  const short = ex.session_id.slice(0, 8);
  const note = h("textarea", { id: `appeal-note-${short}`, rows: 3, cols: 60, maxlength: 4000,
    placeholder: "Anything the reviewer should know: what you pasted and where it came from, a setup problem, an accommodation…" }) as HTMLTextAreaElement;
  const error = h("p", { class: "error" });
  const send = async () => {
    error.textContent = "";
    if (note.value.trim().length < 10) { error.textContent = "Write at least 10 characters."; return; }
    try {
      await api.appeal(ex.session_id, note.value.trim(), token);
      await reload();
    } catch (err) {
      error.textContent = String(err);
    }
  };
  return h("div", { class: "review-form" },
    h("label", { for: `appeal-note-${short}` }, ex.appeals?.length ? "Add another note for the reviewer" : "Add a note for the reviewer"),
    note,
    h("p", { class: "muted" }, "A person reads every note before deciding. Your note is kept with the exam and cannot be edited later."),
    h("button", { class: "primary", id: `appeal-send-${short}`, onclick: () => void send() }, "Send note"),
    error,
  );
}

export async function myReportPage(root: HTMLElement): Promise<void> {
  const participant = store.participant();
  const main = h("main", { class: "dashboard" });
  root.replaceChildren(main);
  if (!participant) {
    main.replaceChildren(h("p", {}, "No participant in this tab. Start from the consent page."));
    return;
  }
  main.replaceChildren(h("p", { class: "muted" }, "Building your report…"));
  const load = async (): Promise<void> => {
    try {
      const report = await api.myReport(participant.token);
      main.replaceChildren(
        renderReport(report, { reviewExtra: (ex) => appealForm(ex, participant.token, load) }),
        h("p", {}, h("a", { href: "#/setup" }, "Back to the tasks")),
        withdrawPanel(participant),
      );
    } catch (err) {
      main.replaceChildren(String(err).includes(": 404 ")
        ? h("p", { id: "no-report" }, "Reports are shown to the reviewers only. You can close this window.")
        : h("p", { class: "error" }, String(err)));
    }
  };
  await load();
}
