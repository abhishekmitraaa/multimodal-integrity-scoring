// Device questionnaire (covariates, SPEC 4.9) and task choice.

import { api } from "../api";
import { detectLayout } from "../capture/device";
import { h } from "../dom";
import { store, type SetupState } from "../state";

const PROBLEMS: Array<{ id: string; kind: "practice" | "exam"; label: string }> = [
  { id: "practice_sum_evens", kind: "practice", label: "Practice 1: sum of even numbers" },
  { id: "practice_word_count", kind: "practice", label: "Practice 2: word count" },
  { id: "exam_run_length", kind: "exam", label: "Exam task: run-length encoding" },
];

export async function setupPage(root: HTMLElement): Promise<void> {
  const participant = store.participant();
  if (!participant) {
    location.hash = "#/";
    return;
  }
  const detected = await detectLayout();
  const keyboard = h("select", { id: "keyboard-type" },
    h("option", { value: "laptop_builtin" }, "Laptop's built-in keyboard"),
    h("option", { value: "external" }, "External keyboard"),
    h("option", { value: "other" }, "Other"),
    h("option", { value: "unknown" }, "Prefer not to say"),
  );
  const layout = h("select", { id: "layout" },
    h("option", { value: "qwerty" }, "QWERTY"),
    h("option", { value: "qwertz" }, "QWERTZ"),
    h("option", { value: "azerty" }, "AZERTY"),
    h("option", { value: "other" }, "Other"),
  );
  const error = h("p", { class: "error" });
  const buttons = PROBLEMS.map((p) =>
    h("button", {
      "data-problem": p.id,
      onclick: async () => {
        const setup: SetupState = {
          keyboardType: (keyboard as HTMLSelectElement).value as SetupState["keyboardType"],
          layout: detected ? undefined : (layout as HTMLSelectElement).value,
        };
        store.setSetup(setup);
        try {
          const s = await api.createSession({ participant_token: participant.token, kind: p.kind, problem_id: p.id });
          store.addSession(s.session_id, { token: s.session_token, problemId: p.id, kind: p.kind });
          location.hash = `#/session/${s.session_id}`;
        } catch (err) {
          error.textContent = String(err);
        }
      },
    }, p.label),
  );
  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Before you start"),
      h("p", {}, `Your pseudonym: `, h("code", { id: "pseudonym" }, participant.pseudonym), ". Keep it if you may want to withdraw later."),
      h("label", {}, "Which keyboard are you using? ", keyboard),
      detected ? h("p", {}, `Keyboard layout detected: ${detected}.`) : h("label", {}, "Keyboard layout: ", layout),
      h("h2", {}, "Choose a task"),
      h("div", { class: "row" }, ...buttons),
      error,
    ),
  );
}
