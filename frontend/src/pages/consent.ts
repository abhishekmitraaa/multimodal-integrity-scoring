// Consent screen. The wording is the lead-approved draft (2026-10-27); the governance values (Q4)
// come from config/privacy.yaml via the server and show "[to be set]" while blank. Until ethics
// approval the backend refuses real participants; this page creates "dev" or "synthetic" ones.

import { api, SERVER_DOWN_MESSAGE, ServerUnavailableError, type NoticeFields } from "../api";
import { sha256Hex } from "../capture/hash";
import { h } from "../dom";
import { store } from "../state";

export const NOTICE_VERSION = "draft-2";
const UNSET: NoticeFields = { data_fiduciary: "[to be set]", contact: "[to be set]", retention: "[to be set]" };

/** The notice text; its SHA-256 is stored with the consent, so the exact wording shown is on record. */
export const noticeText = (f: NoticeFields): string => `DRAFT NOTICE (not for real data collection)

Purpose: research evaluation of a prototype that scores coding-exam sessions for human review. It is never used for grades or any academic decision.

What is recorded, inside the code editor only: which keys you press and when (not the characters themselves, except as they appear in your code), your code and its edits, paste/copy events (copied text is stored only as a fingerprint), when the editor or window loses focus, Run/Test results, and basic device facts (operating system, browser, keyboard type, screen size). Nothing typed outside the editor, no mouse movement, no camera, microphone or screen recording.

Your data is stored under a random pseudonym, encrypted, on a machine outside any cloud-sync folder. ${f.retention === "[to be set]" ? "Retention period: [to be set]." : f.retention}

Responsible for your data: ${f.data_fiduciary}.

False flags: accessibility needs and assistive technology, injury, fatigue, mood and stress, a different keyboard or device, and input methods can all change how someone types. A flag only means a person should look; it is never evidence of misconduct.

You can withdraw at any time, without giving a reason: use "Withdraw from the study" on the tasks page, or write to the contact below. Withdrawal stops collection and deletes your data. Contact for withdrawal, questions and complaints: ${f.contact}.`;

export function consentPage(root: HTMLElement): void {
  const kind = new URLSearchParams(location.search).get("kind") === "synthetic" ? "synthetic" : "dev";
  const studyOptIn = new URLSearchParams(location.search).get("study") === "1";      // dev testers try the study protocol
  let notice = noticeText(UNSET);
  const noticeEl = h("pre", { class: "notice", id: "notice" }, notice);
  api.clientConfig().then((c) => { notice = noticeText(c.notice); noticeEl.textContent = notice; }, () => undefined);
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
          study: studyOptIn,
          age_confirmed: true,
          consent: { notice_version: NOTICE_VERSION, notice_sha256: await sha256Hex(notice), choices: { participation: true } },
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
      noticeEl,
      h("label", {}, age, " I am 18 or older."),
      h("label", {}, agree, " I have read the notice and agree to take part."),
      start,
      error,
    ),
  );
}
