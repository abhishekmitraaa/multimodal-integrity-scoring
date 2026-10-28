// Thin fetch helpers for the backend REST API.

import type { EditorPolicy } from "./editor";

export interface Problem {
  id: string;
  kind: "practice" | "exam";
  title: string;
  statement: string;
  starter: string;
  /** Practice tasks only: the code shown for the student to type (D-035). */
  reference_solution?: string;
  tests: Array<{ call: string; expected: string }>;
}

export interface CaptureSettings {
  batch: { max_keydowns: number; max_age_ms: number; max_events: number };
  resend_timeout_ms: number;
  snapshot: { interval_ms: number; large_insert_min_chars: number; large_insert_min_lines: number };
  cursor_event_throttle_ms: number;
}

export const SERVER_DOWN_MESSAGE =
  "The study server is not running or cannot be reached. Start everything with scripts\\dev.ps1 " +
  "(see README, \"Running the app locally\"), then reload this page.";

/** The backend is not reachable: nothing listens on :8000 (the Vite proxy answers 502/503/504). */
export class ServerUnavailableError extends Error {
  constructor() {
    super(SERVER_DOWN_MESSAGE);
    this.name = "ServerUnavailableError";
  }
  override toString(): string {
    return this.message;
  }
}

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ServerUnavailableError();   // connection refused, network down
  }
  if ([502, 503, 504].includes(res.status)) throw new ServerUnavailableError();
  if (!res.ok) throw new Error(`${init.method ?? "GET"} ${path}: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export const api = {
  health: () => call<{ status: string }>("/api/health"),
  clientConfig: () => call<{ policy: EditorPolicy; capture: CaptureSettings; notice: NoticeFields; participant_report: boolean; video: { kinds: string[]; chunk_ms: number } }>("/api/client-config"),
  problem: (id: string) => call<Problem>(`/api/problems/${id}`),
  createParticipant: (body: unknown) =>
    call<{ pseudonym: string; participant_token: string }>("/api/participants", { method: "POST", body: JSON.stringify(body) }),
  createSession: (body: { participant_token: string; kind: string; problem_id: string; env?: SessionEnv }) =>
    call<{ session_id: string; session_token: string }>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  sessionState: (id: string, token: string) => call<{ text: string; n_events: number }>(`/api/sessions/${id}/state`, {}, token),
  closeSession: (id: string, token: string) =>
    call<{ n_events: number; head_hash: string; signed: boolean }>(`/api/sessions/${id}/close`, { method: "POST" }, token),
  myReport: (participantToken: string) => call<Report>("/api/me/report", {}, participantToken),
  plan: (participantToken: string) => call<StudyPlan>("/api/me/plan", {}, participantToken),
  material: (sessionId: string, participantToken: string) =>
    call<{ problem_id: string; condition: StudyCondition; text: string; label: string; model: string; generated_at: string }>(
      `/api/me/material/${sessionId}`, {}, participantToken),
  onset: (sessionId: string, tClientUs: number, participantToken: string) =>
    call<{ marked: boolean }>("/api/me/onset", { method: "POST", body: JSON.stringify({ session_id: sessionId, t_client_us: tClientUs }) },
      participantToken),
  withdraw: (participantToken: string) =>
    call<{ erased: boolean; n_sessions: number; n_events: number }>("/api/me/withdraw", { method: "POST" }, participantToken),
  appeal: (sessionId: string, note: string, participantToken: string) =>
    call<{ id: number; at: string }>("/api/me/appeals", { method: "POST", body: JSON.stringify({ session_id: sessionId, note }) }, participantToken),
  staff: {
    me: (token: string) => call<{ handle: string; role: string; shared: "true" | "false" }>("/api/staff/me", {}, token),
    participants: (token: string) => call<ParticipantSummary[]>("/api/participants", {}, token),
    report: (pseudonym: string, token: string) => call<Report>(`/api/participants/${encodeURIComponent(pseudonym)}/report`, {}, token),
    sessions: (token: string) => call<Array<Record<string, unknown>>>("/api/sessions", {}, token),
    decide: (sessionId: string, decision: DecisionKind, notes: string, token: string) =>
      call<{ id: number; at: string; decision: DecisionKind; report_state: string }>(
        `/api/sessions/${sessionId}/decision`, { method: "POST", body: JSON.stringify({ decision, notes }) }, token,
      ),
    accessLog: (token: string) => call<AccessLogEntry[]>("/api/access-log", {}, token),
    /** The session's webcam recording (D-048); reviewer or admin token (D-049). */
    video: async (sessionId: string, token: string): Promise<Blob> => {
      const res = await fetch(`/api/admin/sessions/${sessionId}/video`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 403) throw new Error("Viewing the video needs a reviewer or admin token.");
      if (!res.ok) throw new Error(`video: ${res.status}`);
      return res.blob();
    },
    events: (id: string, token: string) => call<{ events: StaffEvent[] }>(`/api/sessions/${id}/events`, {}, token),
    verify: (id: string, token: string) =>
      call<{ ok: boolean; n_events: number; head_hash: string; first_bad_index: number | null; reason: string | null }>(
        `/api/sessions/${id}/verify`, {}, token,
      ),
  },
};

// ---- study protocol (D-046)

export type StudyCondition = "genuine" | "A1" | "A2" | "A3a" | "A3b" | "A4" | "A5" | "A7" | "A8";

export interface SessionEnv {
  browser_brand: "chrome" | "edge" | "chromium" | "firefox" | "safari" | "other";
  browser_version: string;
  cross_origin_isolated: boolean;
}

export interface StudyPlan {
  study: boolean;
  slots: Array<{ slot: number; problem_id: string; title: string; condition: StudyCondition; material: boolean;
    session_id: string | null; done: boolean }>;
  sitting2_opens_at?: string | null;
}

/** Governance text for the consent notice (Q4), from config/privacy.yaml; "[to be set]" while blank. */
export interface NoticeFields {
  data_fiduciary: string;
  contact: string;
  retention: string;
}

export interface StaffEvent {
  server_seq: number;
  client_seq: number | null;
  epoch: number;
  origin: "client" | "server";
  type: string;
  t_client_us: number | null;
  t_server_us: number;
  data: Record<string, unknown>;
}

// ---- evidence report (D-036); built on the server by backend/report.py

export type ReportState = "review" | "insufficient_data" | "no_review_flags" | "no_exam_yet";

export interface Finding {
  id: string;
  status: "flag" | "ok" | "info" | "unavailable";
  title: string;
  detail: string;
}

export interface HabitValues {
  interval_cv: number | null;
  pause_share_2s: number | null;
  revisions_per_100: number | null;
  chars_per_minute: number | null;
  keystrokes: number;
  typed_chars: number;
}

export interface ExamReport {
  session_id: string;
  problem_id: string;
  closed: boolean;
  duration_s: number;
  state: Exclude<ReportState, "no_exam_yet">;
  reasons: string[];
  findings: Finding[];
  keystroke: { available: false; redacted?: boolean } | {
    available: true; g: number; threshold: number; population_threshold: number; personal_threshold: number | null;
    eer_threshold: number; share_above: number;
    windows: Array<{ t: number; distance: number }>;
  };
  habits: { exam: HabitValues | null; baseline: HabitValues | null };
  pastes: Array<{ t: number; chars: number; provenance: string }>;
  ast_jumps?: Array<{ t: number; added_nodes: number; keydowns: number }>;
  /** SPEC 6.2, reviewers only: the whole exam next to the practice mean (null = not enough input). */
  process?: { exam: Record<string, number | null>; baseline: Record<string, number | null> | null };
  decisions?: Decision[];
  appeals?: Appeal[];
  /** D-048, staff only: the webcam recording (a demo feature, not analysed). */
  video?: { available: boolean; chunks: number; bytes: number; approx_seconds: number };
  /** D-048, staff only: SIMULATED for the demo, never computed from the video. */
  head_movement_demo?: HeadMovementDemo;
}

export interface HeadMovementDemo {
  simulated: true;
  label: string;
  step_s: number;
  samples: Array<{ t: number; yaw: number }>;
  look_aways: Array<{ start: number; end: number; direction: "left" | "right" }>;
  facing_screen_share: number;
  longest_look_away_s: number;
}

// ---- reviewer workflow (D-039)

export type DecisionKind = "confirm" | "dismiss" | "inconclusive";

/** A reviewer decision. Participants get the outcome and date only; reviewers also see who and why. */
export interface Decision {
  decision: DecisionKind;
  at: string;
  reviewer?: string;
  report_state?: string;
  notes?: string;
}

export interface Appeal {
  at: string;
  note: string;
}

export interface AccessLogEntry {
  at: string;
  actor: string;
  role: string;
  action: string;
  target: string;
}

export interface Report {
  pseudonym: string;
  generated_at: string;
  model: { available: boolean; note: string };
  baseline: {
    status: "ready" | "insufficient" | "none";
    practice_sessions: Array<{ session_id: string; problem_id: string; keystrokes: number; windows: number }>;
    windows: number;
    windows_needed: number;
    habits: HabitValues | null;
    note: string;
    check: BaselineCheck;
  };
  exams: ExamReport[];
  overall: { state: ReportState; reasons: string[] };
  no_score_note: string;
  false_flag_note: string;
}

export interface ParticipantSummary {
  pseudonym: string;
  kind: string;
  created_at: string;
  sessions: Array<{ session_id: string; kind: "practice" | "exam"; stage: Stage; problem_id: string; created_at: string; closed: boolean;
    decision?: DecisionKind | null }>;
}

export type Stage = "baseline" | "check" | "exam";

/** The baseline check (D-038): typing held out from the baseline and compared with it. */
export interface BaselineCheck {
  status: "confirmed" | "not_confirmed" | "not_done" | "unavailable";
  detail: string;
  windows?: number[];
  population_threshold?: number;
  personal_threshold?: number | null;
}
