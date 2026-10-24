// Consent screen. DRAFT: the final notice needs the faculty guide's answers (Q4) and ethics approval.
// Until then the backend refuses real participants; this page creates "dev" or "synthetic" ones.

import { api, SERVER_DOWN_MESSAGE, ServerUnavailableError } from "../api";
import { sha256Hex } from "../capture/hash";
import { h } from "../dom";
import { store } from "../state";

export const NOTICE_VERSION = "draft-p1";

export const NOTICE = `DRAFT NOTICE (not for real data collection)

Purpose: research evaluation of a prototype that scores coding-exam sessions for human review. It is never used for grades or any academic decision.

What is recorded, inside the code editor only: which keys you press and when (not the characters themselves, except as they appear in your code), your code and its edits, paste/copy events (copied text is stored only as a fingerprint), when the editor or window loses focus, Run/Test results, and basic device facts (operating system, browser, keyboard type, screen size). Nothing typed outside the editor, no mouse movement, no camera, microphone or screen recording.

Your data is stored under a random pseudonym, encrypted, on a machine outside any cloud-sync folder. Retention period: [to be set by the faculty guide].

False flags: accessibility needs and assistive technology, injury, fatigue, mood and stress, a different keyboard or device, and input methods can all change how someone types. A flag only means a person should look; it is never evidence of misconduct.

You can withdraw at any time. Withdrawal deletes your data. Contact: [named responsible party, to be set].`;

export function consentPage(root: HTMLElement): void {
  const kind = new URLSearchParams(location.search).get("kind") === "synthetic" ? "synthetic" : "dev";
  const age = h("input", { type: "checkbox", id: "age" });
  const agree = h("input", { type: "checkbox", id: "agree" });
  const error = h("p", { class: "error", id: "consent-error" });
  const start = h("button", {
    id: "consent-continue",
    onclick: async () => {
      if (!(age as HTMLInputElement).checked || !(agree as HTMLInputElement).checked) {
        error.textContent = "Please confirm both boxes to continue.";
        return;
      }
      try {
        const res = await api.createParticipant({
          kind,
          age_confirmed: true,
          consent: { notice_version: NOTICE_VERSION, notice_sha256: await sha256Hex(NOTICE), choices: { participation: true } },
        });
        store.setParticipant({ pseudonym: res.pseudonym, token: res.participant_token, kind });
        location.hash = "#/setup";
      } catch (err) {
        error.textContent = String(err);
      }
    },
  }, "Continue");

  // Check the server before anyone fills in the form, so a missing backend is obvious at once.
  const serverDown = h("p", { class: "banner error", id: "server-down", role: "alert", hidden: true });
  api.health().catch((err: unknown) => {
    serverDown.textContent = err instanceof ServerUnavailableError ? SERVER_DOWN_MESSAGE : `Server check failed: ${String(err)}`;
    serverDown.hidden = false;
    start.setAttribute("disabled", "");
  });

  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Coding practice study"),
      serverDown,
      h("p", { class: "banner" }, `Development build. Participant kind: ${kind}. Real data collection is disabled until ethics approval.`),
      h("pre", { class: "notice", id: "notice" }, NOTICE),
      h("label", {}, age, " I am 18 or older."),
      h("label", {}, agree, " I have read the notice and agree to take part."),
      start,
      error,
    ),
  );
}
