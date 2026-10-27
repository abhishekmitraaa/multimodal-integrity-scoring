// Device questionnaire (covariates, SPEC 4.9) and task choice.

import { api } from "../api";
import { detectLayout } from "../capture/device";
import { h } from "../dom";
import { store, type SetupState } from "../state";

const PROBLEMS: Array<{ id: string; kind: "practice" | "exam"; stage: "baseline" | "check" | "exam"; label: string }> = [
  { id: "practice_sum_evens", kind: "practice", stage: "baseline", label: "Practice 1: sum of even numbers" },
  { id: "practice_word_count", kind: "practice", stage: "baseline", label: "Practice 2: word count" },
  { id: "practice_letter_grade", kind: "practice", stage: "baseline", label: "Practice 3: letter grade" },
  { id: "check_count_vowels", kind: "practice", stage: "check", label: "Baseline check: count vowels" },
  { id: "exam_run_length", kind: "exam", stage: "exam", label: "Exam: run-length encoding" },
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
  const done = new Set(store.done());
  const buttons = PROBLEMS.map((p) =>
    h("button", {
      "data-problem": p.id,
      class: done.has(p.id) ? "task-done" : undefined,
      disabled: p.stage === "check" && done.has(p.id),     // the server allows one baseline check (D-038)
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
    }, done.has(p.id) ? `✓ ${p.label}` : p.label),
  );
  const byStage = (stage: string) => buttons.filter((_, i) => PROBLEMS[i].stage === stage);
  const practiceButtons = byStage("baseline");
  const checkButtons = byStage("check");
  const examButtons = byStage("exam");
  const practiceDone = PROBLEMS.filter((p) => p.stage === "baseline" && done.has(p.id)).length;
  const checkDone = PROBLEMS.some((p) => p.stage === "check" && done.has(p.id));
  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Before you start"),
      h("p", {}, `Your pseudonym: `, h("code", { id: "pseudonym" }, participant.pseudonym), ". Keep it if you may want to withdraw later."),
      h("label", {}, "Which keyboard are you using? ", keyboard),
      detected ? h("p", {}, `Keyboard layout detected: ${detected}.`) : h("label", {}, "Keyboard layout: ", layout),
      h("h2", {}, "Step 1: practice tasks"),
      h("p", { class: "muted" }, "Each practice task shows the code to type. Your typing here builds your personal baseline. ",
        `Done: ${practiceDone} of ${practiceButtons.length}.`),
      h("div", { class: "row" }, ...practiceButtons),
      h("h2", {}, "Step 2: baseline check"),
      h("p", { class: "muted" }, "One more short task to type. It is compared with your practice typing to confirm that your ",
        "baseline really describes you, and it sets your own normal range for the exam.",
        practiceDone < practiceButtons.length ? " Finish the practice tasks first." : ""),
      h("div", { class: "row" }, ...checkButtons),
      h("h2", {}, "Step 3: exam"),
      h("p", { class: "muted" }, "Solve it yourself. Afterwards it is checked against your baseline and you can see the report.",
        !checkDone ? " Do the baseline check first." : ""),
      h("div", { class: "row" }, ...examButtons),
      done.has("exam_run_length") ? h("p", {}, h("a", { href: "#/my-report", id: "setup-report" }, "See your report")) : null,
      error,
    ),
  );
}
