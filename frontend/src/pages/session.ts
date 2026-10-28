// The practice/exam session: problem panel, Monaco editor, Run/Test/Submit, live capture.

import { api } from "../api";
import { Capture } from "../capture/capture";
import { collectDevice, probeTimerResolutionUs } from "../capture/device";
import { sha256Hex } from "../capture/hash";
import { EventLog } from "../capture/log";
import { Transport, type Status } from "../capture/transport";
import { h } from "../dom";
import { checkPolicy, createEditor, monaco } from "../editor";
import { PyRunner } from "../runner/runner";
import { store } from "../state";
import { WebcamRecorder } from "../capture/video";
import { roleplayCard } from "./study";

export async function sessionPage(root: HTMLElement, sessionId: string): Promise<void> {
  const ref = store.session(sessionId);
  const participant = store.participant();
  if (!ref || !participant) {
    root.replaceChildren(h("main", { class: "narrow" }, h("p", {}, "This session is not open in this tab.")));
    return;
  }
  const [config, problem, state, roleplay] = await Promise.all([
    api.clientConfig(),
    api.problem(ref.problemId),
    api.sessionState(sessionId, ref.token),
    ref.kind === "exam" ? roleplayCard(sessionId, participant.token) : Promise.resolve(null),
  ]);
  const cap = config.capture;

  const status = h("span", { id: "status", class: "status" }, "connecting");
  const output = h("pre", { id: "output", class: "output" });
  // Practice tasks show the code to type, so nobody gets stuck (D-035). The server never sends
  // one for an exam task. The block can't be selected, so it is typed, not copied.
  const reference = problem.reference_solution
    ? [
      h("h3", {}, "Code to type"),
      h("p", { class: "muted", id: "reference-help" },
        "Type this code into the editor yourself (don't copy and paste). The editor indents for you after a colon; ",
        "press Backspace to go back one level. Then click Test, and Submit when the tests pass."),
      h("pre", { class: "reference-code", id: "reference-code", oncopy: (e: Event) => e.preventDefault() }, problem.reference_solution),
    ]
    : [];
  const panel = h("section", { class: "problem", id: "problem" },
    roleplay,
    h("h2", {}, problem.title),
    h("p", { class: "statement" }, problem.statement),
    ...reference,
    h("h3", {}, "Tests"),
    h("ul", {}, ...problem.tests.map((t) => h("li", {}, h("code", {}, `${t.call} == ${t.expected}`)))),
  );
  const recordVideo = ref.kind === "exam" && participant.video === true && config.video.kinds.includes(participant.kind);
  const preview = h("video", { id: "webcam-preview", class: "webcam-preview", playsinline: true }) as HTMLVideoElement;
  const camStatus = h("span", { id: "webcam-status", class: "webcam-status" }, "Starting camera…");
  const camBox = recordVideo ? h("div", { class: "webcam", id: "webcam" }, preview, camStatus) : null;
  const host = h("div", { id: "editor", class: "editor" });
  const runBtn = h("button", { id: "run", disabled: true }, "Run");
  const testBtn = h("button", { id: "test", disabled: true }, "Test");
  const submitBtn = h("button", { id: "submit", class: "primary", disabled: true }, "Submit");
  root.replaceChildren(
    h("div", { class: "session" },
      h("header", {}, h("strong", {}, problem.title), h("span", {}, ` · ${participant.pseudonym} · `), status, camBox),
      panel,
      h("section", { class: "work" }, host, h("div", { class: "row" }, runBtn, testBtn, submitBtn), output),
    ),
  );

  // Restore the replayed document after a reload; otherwise start from the starter code.
  const editor = createEditor(host, config.policy, state.n_events > 0 ? state.text : problem.starter);
  editor.updateOptions({ readOnly: true });

  const log = new EventLog();
  const transport = new Transport({
    sessionId, token: ref.token, log, resendTimeoutMs: cap.resend_timeout_ms,
    onStatus: (s: Status) => (status.textContent = s),
    onServerError: (code, detail) => {
      status.textContent = `server error: ${code}`;
      console.warn("server error", code, detail);
    },
  });
  log.onPriority = () => transport.flush();

  const timer = { resolution_us: probeTimerResolutionUs(), cross_origin_isolated: self.crossOriginIsolated === true };
  const setup = store.setup();
  const device = await collectDevice(setup?.keyboardType ?? "unknown", setup?.layout);
  const welcome = await transport.connect(false);
  log.start(welcome.next_client_seq);
  log.push("segment_start", {
    time_origin_unix_us: Math.round(performance.timeOrigin * 1000),
    page: ref.kind, problem_id: ref.problemId,
    editor_policy_id: config.policy.policy_id, editor_policy_sha256: config.policy.sha256,
    device, timer, synthetic: participant.kind === "synthetic",
  });
  const capture = new Capture(editor, log, {
    snapshotIntervalMs: cap.snapshot.interval_ms,
    largeInsertMinChars: cap.snapshot.large_insert_min_chars,
    largeInsertMinLines: cap.snapshot.large_insert_min_lines,
    cursorThrottleMs: cap.cursor_event_throttle_ms,
  }, panel);
  capture.snapshot("segment_start", true);
  capture.start();

  // D-048: the webcam starts with the exam, after the participant ticked the separate video box.
  const webcam = recordVideo ? new WebcamRecorder(sessionId, ref.token, config.video.chunk_ms) : null;
  if (webcam) {
    void webcam.start(preview).then((ok) => {
      camStatus.textContent = ok ? "● Recording webcam" : "Camera not available: the exam continues without video.";
      camStatus.classList.toggle("recording", ok);
    });
  }

  const policyChecks = checkPolicy(editor, config.policy);
  const mismatches = policyChecks.filter((c) => c.status === "mismatch");
  if (mismatches.length) {
    log.push("client_notice", { code: "policy_mismatch", detail: mismatches.map((m) => m.option).join(",").slice(0, 256) }, performance.now(), true);
  }

  const flushTimer = window.setInterval(() => {
    if (log.flushDue(cap.batch.max_keydowns, cap.batch.max_age_ms)) transport.flush();
  }, 100);

  const runner = new PyRunner();
  const runCode = async (kind: "run" | "test") => {
    output.textContent = runner.loaded ? (kind === "run" ? "Running…" : "Testing…")
      : "Starting Python (the first time can take a minute on a slow computer)…";
    const version = editor.getModel()!.getVersionId();
    const result = await runner.run(kind, editor.getValue(), problem.tests);
    log.push("run", {
      kind, n_tests: result.n_tests, n_passed: result.n_passed, status: result.status,
      dur_ms: result.dur_ms, version_id: version,
    }, performance.now(), true);
    capture.snapshot("run", true);
    output.textContent = [
      kind === "test" ? `${result.n_passed}/${result.n_tests} tests passed` : `status: ${result.status}`,
      result.stdout,
      ...result.details,
    ].filter(Boolean).join("\n");
  };
  runBtn.addEventListener("click", () => void runCode("run"));
  testBtn.addEventListener("click", () => void runCode("test"));

  let ended = false;
  submitBtn.addEventListener("click", async () => {
    submitBtn.setAttribute("disabled", "");
    editor.updateOptions({ readOnly: true });
    const text = editor.getValue();
    const version = editor.getModel()!.getVersionId();
    capture.snapshot("submit");
    log.pushAsync("submit", sha256Hex(text).then((sha256) => ({ version_id: version, sha256 })));
    log.push("segment_end", { reason: "submit" }, performance.now(), true);
    ended = true;
    capture.stop();
    if (webcam) {
      camStatus.textContent = "Saving the video…";
      await webcam.stop();                       // the server accepts video only until the exam is submitted
    }
    const drained = await transport.drained();
    const receipt = await api.closeSession(sessionId, ref.token);
    transport.close();
    window.clearInterval(flushTimer);
    store.markDone(ref.problemId);
    location.hash = `#/done/${sessionId}?n=${receipt.n_events}&head=${receipt.head_hash}&drained=${drained ? 1 : 0}&kind=${ref.kind}`;
  });

  window.addEventListener("pagehide", () => {
    if (ended) return;
    ended = true;
    void webcam?.stop();
    log.push("segment_end", { reason: "unload" });
    transport.beacon();
  });

  editor.updateOptions({ readOnly: false });
  [runBtn, testBtn, submitBtn].forEach((b) => b.removeAttribute("disabled"));
  editor.focus();

  if (import.meta.env.DEV) {
    // Test hook for Playwright; the client is untrusted anyway (SPEC 1.2).
    (window as unknown as Record<string, unknown>).__integrity = { editor, log, transport, monaco, policyChecks, sessionId };
  }
}
