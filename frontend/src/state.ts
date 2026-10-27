// Per-tab state in sessionStorage. Tokens are tab-scoped and vanish when the tab closes.

export interface ParticipantState {
  pseudonym: string;
  token: string;
  kind: "dev" | "synthetic";
}

export interface SetupState {
  keyboardType: "laptop_builtin" | "external" | "other" | "unknown";
  layout?: string;
}

export interface SessionRef {
  token: string;
  problemId: string;
  kind: "practice" | "exam";
}

function read<T>(key: string): T | undefined {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : undefined;
  } catch {
    return undefined;
  }
}

function write(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage blocked: the flow still works within this page load
  }
}

export const store = {
  participant: () => read<ParticipantState>("participant"),
  setParticipant: (p: ParticipantState) => write("participant", p),
  setup: () => read<SetupState>("setup"),
  setSetup: (s: SetupState) => write("setup", s),
  session: (id: string) => read<Record<string, SessionRef>>("sessions")?.[id],
  addSession: (id: string, ref: SessionRef) => write("sessions", { ...(read<Record<string, SessionRef>>("sessions") ?? {}), [id]: ref }),
  /** Problems this tab's participant has submitted (for the setup page's checkmarks). */
  done: () => read<string[]>("done") ?? [],
  markDone: (problemId: string) => write("done", [...new Set([...(read<string[]>("done") ?? []), problemId])]),
  /** After withdrawal: forget the participant, their sessions and progress in this tab. */
  clearParticipant: () => {
    for (const key of ["participant", "sessions", "done", "setup"]) {
      try { sessionStorage.removeItem(key); } catch { /* storage blocked */ }
    }
  },
  staffToken: () => read<string>("staffToken"),
  setStaffToken: (t: string) => write("staffToken", t),
};
