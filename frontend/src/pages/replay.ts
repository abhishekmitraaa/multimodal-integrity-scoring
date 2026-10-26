// Minimal reviewer replay (P1). The full dashboard is P4. Every read is access-logged server-side.

import { api, type StaffEvent } from "../api";
import { h } from "../dom";
import { replayText } from "../replay";
import { store } from "../state";

export async function replayPage(root: HTMLElement, params: URLSearchParams = new URLSearchParams()): Promise<void> {
  const tokenInput = h("input", { type: "password", id: "staff-token", placeholder: "Reviewer token" }) as HTMLInputElement;
  tokenInput.value = store.staffToken() ?? "";
  const list = h("ul", { id: "sessions" });
  const viewer = h("section", { id: "viewer" });
  const error = h("p", { class: "error" });

  const load = async () => {
    store.setStaffToken(tokenInput.value);
    try {
      const sessions = await api.staff.sessions(tokenInput.value);
      list.replaceChildren(
        ...sessions.map((s) =>
          h("li", {},
            h("button", { class: "link", onclick: () => void open(String(s.session_id)) }, String(s.session_id).slice(0, 8)),
            ` ${s.pseudonym} · ${s.problem_id} · ${s.n_events} events${s.closed ? " · closed" : ""}`,
          ),
        ),
      );
    } catch (err) {
      error.textContent = String(err);
    }
  };

  const open = async (sessionId: string) => {
    const [{ events }, verify] = await Promise.all([
      api.staff.events(sessionId, tokenInput.value),
      api.staff.verify(sessionId, tokenInput.value),
    ]);
    const slider = h("input", { type: "range", min: 0, max: Math.max(0, events.length - 1), value: events.length - 1, id: "scrub" }) as HTMLInputElement;
    const code = h("pre", { class: "replay", id: "replay-text" });
    const info = h("p", { id: "replay-info" });
    const render = () => {
      const upto = Number(slider.value);
      const e: StaffEvent | undefined = events[upto];
      code.textContent = replayText(events, upto);
      info.textContent = e ? `server_seq ${e.server_seq} · ${e.type} (${e.origin})` : "";
    };
    slider.addEventListener("input", render);
    render();
    viewer.replaceChildren(
      h("h2", {}, `Session ${sessionId}`),
      h("p", { id: "chain-status", class: verify.ok ? "ok" : "error" },
        verify.ok ? `Hash chain verified: ${verify.n_events} events, head ${verify.head_hash.slice(0, 16)}…`
          : `Hash chain BROKEN at index ${verify.first_bad_index}: ${verify.reason}`),
      slider, info, code,
    );
  };

  root.replaceChildren(
    h("main", {},
      h("h1", {}, "Replay (reviewer)"),
      h("p", { class: "muted" }, "Pseudonymous data. Every read is recorded in the access log."),
      h("div", { class: "row" }, tokenInput, h("button", { onclick: () => void load() }, "Load sessions")),
      error, list, viewer,
    ),
  );

  const wanted = params.get("session");
  if (wanted && tokenInput.value) {
    await load();
    await open(wanted);
  }
}
