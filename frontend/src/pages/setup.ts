// Device questionnaire (covariates, SPEC 4.9) and task choice.

import { api } from "../api";
import { detectLayout } from "../capture/device";
import { h } from "../dom";
import { store, type SetupState } from "../state";
import { ROLEPLAY, sessionEnv } from "./study";
import { withdrawPanel } from "./withdraw";

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
  // Study participants (D-046) get their own sitting-2 plan: six tasks, each with a role-play condition.
  const [plan, config] = await Promise.all([api.plan(participant.token).catch(() => null), api.clientConfig().catch(() => null)]);
  if (!location.hash.startsWith("#/setup")) return;         // the user moved on while this loaded: don't draw over it
  const slots = plan?.study ? plan.slots : [];
  const tasks = slots.length
    ? [...PROBLEMS.filter((p) => p.stage !== "exam"),
      ...slots.map((s) => ({ id: s.problem_id, kind: "exam" as const, stage: "exam" as const, label: `Exam ${s.slot + 1}: ${s.title}` }))]
    : PROBLEMS;
  const slotOf = new Map(slots.map((s) => [s.problem_id, s]));
  const buttons = tasks.map((p) => {
    const s = slotOf.get(p.id);
    const finished = s ? s.done : done.has(p.id);
    const b = h("button", {
      "data-problem": p.id,
      class: finished ? "task-done" : undefined,
      disabled: (p.stage === "check" && done.has(p.id)) || Boolean(s?.session_id),   // one check (D-038); one session per study task
      onclick: async () => {
        const setup: SetupState = {
          keyboardType: (keyboard as HTMLSelectElement).value as SetupState["keyboardType"],
          layout: detected ? undefined : (layout as HTMLSelectElement).value,
        };
        store.setSetup(setup);
        try {
          const created = await api.createSession({ participant_token: participant.token, kind: p.kind, problem_id: p.id, env: await sessionEnv() });
          store.addSession(created.session_id, { token: created.session_token, problemId: p.id, kind: p.kind });
          location.hash = `#/session/${created.session_id}`;
        } catch (err) {
          error.textContent = String(err);
        }
      },
    }, finished ? `✓ ${p.label}` : p.label);
    return s ? h("div", { class: "slot", "data-slot": String(s.slot), "data-condition": s.condition },
      b, h("span", { class: "muted" }, ` ${ROLEPLAY[s.condition].title}`)) : b;
  });
  const byStage = (stage: string) => buttons.filter((_, i) => tasks[i].stage === stage);
  const practiceButtons = byStage("baseline");
  const checkButtons = byStage("check");
  const examButtons = byStage("exam");
  const practiceDone = tasks.filter((p) => p.stage === "baseline" && done.has(p.id)).length;
  const checkDone = tasks.some((p) => p.stage === "check" && done.has(p.id));
  const examDone = slots.length ? slots.some((s) => s.done) : done.has("exam_run_length");
  const opens = plan?.sitting2_opens_at ? new Date(plan.sitting2_opens_at) : null;
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
      h("h2", {}, slots.length ? "Step 3: exam tasks (sitting 2)" : "Step 3: exam"),
      h("p", { class: "muted" }, slots.length
        ? "Each task has its own instructions on its page. Some are role-play for the study, with no consequences."
        : "Solve it yourself. Afterwards it is checked against your baseline and you can see the report.",
      !checkDone ? " Do the baseline check first." : ""),
      opens && opens > new Date() ? h("p", { class: "banner", id: "sitting2-opens" }, `Sitting 2 opens on ${opens.toLocaleString()}.`) : null,
      h("div", { class: slots.length ? "slots" : "row", id: "exam-tasks" }, ...examButtons),
      examDone && config?.participant_report ? h("p", {}, h("a", { href: "#/my-report", id: "setup-report" }, "See your report")) : null,
      error,
      withdrawPanel(participant),
    ),
  );
}
