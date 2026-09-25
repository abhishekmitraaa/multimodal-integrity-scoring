// Thin fetch helpers for the backend REST API.

import type { EditorPolicy } from "./editor";

export interface Problem {
  id: string;
  kind: "practice" | "exam";
  title: string;
  statement: string;
  starter: string;
  tests: Array<{ call: string; expected: string }>;
}

export interface CaptureSettings {
  batch: { max_keydowns: number; max_age_ms: number; max_events: number };
  resend_timeout_ms: number;
  snapshot: { interval_ms: number; large_insert_min_chars: number; large_insert_min_lines: number };
  cursor_event_throttle_ms: number;
}

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new Error(`${init.method ?? "GET"} ${path}: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export const api = {
  clientConfig: () => call<{ policy: EditorPolicy; capture: CaptureSettings }>("/api/client-config"),
  problem: (id: string) => call<Problem>(`/api/problems/${id}`),
  createParticipant: (body: unknown) =>
    call<{ pseudonym: string; participant_token: string }>("/api/participants", { method: "POST", body: JSON.stringify(body) }),
  createSession: (body: unknown) =>
    call<{ session_id: string; session_token: string }>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  sessionState: (id: string, token: string) => call<{ text: string; n_events: number }>(`/api/sessions/${id}/state`, {}, token),
  closeSession: (id: string, token: string) =>
    call<{ n_events: number; head_hash: string; signed: boolean }>(`/api/sessions/${id}/close`, { method: "POST" }, token),
  staff: {
    sessions: (token: string) => call<Array<Record<string, unknown>>>("/api/sessions", {}, token),
    events: (id: string, token: string) => call<{ events: StaffEvent[] }>(`/api/sessions/${id}/events`, {}, token),
    verify: (id: string, token: string) =>
      call<{ ok: boolean; n_events: number; head_hash: string; first_bad_index: number | null; reason: string | null }>(
        `/api/sessions/${id}/verify`, {}, token,
      ),
  },
};

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
