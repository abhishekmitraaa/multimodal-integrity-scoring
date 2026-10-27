// Withdrawal (SPEC 10.3, 10.7): the participant stops taking part and all their data is erased.
// Two steps, so one stray click cannot delete everything.

import { api } from "../api";
import { h } from "../dom";
import { store, type ParticipantState } from "../state";

export function withdrawPanel(participant: ParticipantState): HTMLElement {
  const result = h("p", { id: "withdraw-result" });
  const confirm = h("button", { class: "danger", id: "withdraw-confirm", hidden: true }, "Yes, delete all my data");
  const start = h("button", { id: "withdraw-start" }, "Withdraw and delete my data");
  start.addEventListener("click", () => {
    confirm.hidden = false;
    start.hidden = true;
    result.textContent = "This deletes your recordings, code, report and notes, and cannot be undone. You can still take part again later as a new participant.";
  });
  confirm.addEventListener("click", async () => {
    confirm.setAttribute("disabled", "");
    try {
      await api.withdraw(participant.token);
      store.clearParticipant();
      document.querySelector("main")?.replaceChildren(
        h("h1", {}, "You have withdrawn"),
        h("p", { id: "withdrawn" }, "All your data has been deleted. Thank you for your time."),
        h("p", {}, h("a", { href: "#/" }, "Back to the start")),
      );
    } catch (err) {
      confirm.removeAttribute("disabled");
      result.textContent = String(err);
    }
  });
  return h("details", { class: "withdraw", id: "withdraw" },
    h("summary", {}, "Withdraw from the study"),
    h("p", { class: "muted" }, "You can withdraw at any time, without giving a reason. Collection stops and everything recorded about you is deleted."),
    start, confirm, result,
  );
}
