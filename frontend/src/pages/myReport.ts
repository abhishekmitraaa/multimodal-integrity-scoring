// The participant's own report (SPEC 10.10: participants can see their own evidence).

import { api } from "../api";
import { h } from "../dom";
import { renderReport } from "../report/render";
import { store } from "../state";

export async function myReportPage(root: HTMLElement): Promise<void> {
  const participant = store.participant();
  const main = h("main", { class: "dashboard" });
  root.replaceChildren(main);
  if (!participant) {
    main.replaceChildren(h("p", {}, "No participant in this tab. Start from the consent page."));
    return;
  }
  main.replaceChildren(h("p", { class: "muted" }, "Building your report…"));
  try {
    const report = await api.myReport(participant.token);
    main.replaceChildren(renderReport(report), h("p", {}, h("a", { href: "#/setup" }, "Back to the tasks")));
  } catch (err) {
    main.replaceChildren(h("p", { class: "error" }, String(err)));
  }
}
