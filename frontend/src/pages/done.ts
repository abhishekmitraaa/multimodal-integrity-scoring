// Submission receipt. The head hash is unsigned in P1 (D-017); keeping it still lets the
// participant detect a later rewrite of their log. After an exam the student simply leaves: reports
// are for the reviewers (D-049), unless privacy.participant_report is switched back on.

import { api } from "../api";
import { h } from "../dom";
import { store } from "../state";

export async function donePage(root: HTMLElement, query: URLSearchParams): Promise<void> {
  const participant = store.participant();
  const [config, plan] = await Promise.all([
    api.clientConfig().catch(() => null),
    participant ? api.plan(participant.token).catch(() => null) : Promise.resolve(null),
  ]);
  if (!location.hash.startsWith("#/done")) return;          // the user moved on while this loaded: don't draw over it
  const moreStudyTasks = Boolean(plan?.study && plan.slots.some((s) => !s.done));
  const exam = query.get("kind") === "exam";
  let next: HTMLElement;
  if (!exam) {
    next = h("p", { class: "row" }, h("a", { href: "#/setup", class: "button primary", id: "another-task" }, "Next task"));
  } else if (config?.participant_report) {
    next = h("p", { class: "row" },
      h("a", { href: "#/my-report", class: "button primary", id: "see-report" }, "See your report"),
      h("a", { href: "#/setup", id: "another-task" }, "Back to the tasks"));
  } else {
    next = h("div", {},
      h("p", { class: "banner", id: "done-exit" }, "Thank you, your exam is submitted. You can close this window now."),
      moreStudyTasks ? h("p", { class: "row" }, h("a", { href: "#/setup", class: "button primary", id: "another-task" }, "Next task")) : null);
  }
  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Submitted"),
      h("p", {}, "Your session is closed. This is your receipt:"),
      h("dl", { class: "receipt" },
        h("dt", {}, "Events recorded"), h("dd", { id: "n-events" }, query.get("n") ?? "?"),
        h("dt", {}, "Log fingerprint (head hash)"), h("dd", {}, h("code", { id: "head-hash" }, query.get("head") ?? "?")),
      ),
      h("p", { class: "muted" }, "Keep this fingerprint: it changes if anyone later alters your log. It is not yet signed by the server."),
      query.get("drained") === "0" ? h("p", { class: "error", id: "undelivered" }, "Some events may not have been delivered before closing.") : null,
      next,
    ),
  );
}
