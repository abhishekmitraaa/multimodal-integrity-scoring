// WebSocket transport: hello/welcome, batches, ack/nack, resend, reconnect, beacon (SPEC 4.2).

import type { EventLog, WireEvent } from "./log";

export type Status = "connecting" | "open" | "reconnecting" | "closed";

export interface TransportOptions {
  sessionId: string;
  token: string;
  log: EventLog;
  resendTimeoutMs: number;
  onStatus?: (s: Status) => void;
  onServerError?: (code: string, detail: string) => void;
}

interface Welcome {
  type: "welcome";
  epoch: number;
  next_client_seq: number;
}

export class Transport {
  epoch = -1;
  private ws: WebSocket | null = null;
  private batchSeq = 0;
  private lastSendAt = 0;
  private closedByUs = false;
  private reconnectDelayMs = 500;
  private resendTimer: number | undefined;
  private waiters: Array<() => void> = [];

  constructor(private readonly opts: TransportOptions) {}

  private url(): string {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}/ws/sessions/${this.opts.sessionId}?token=${encodeURIComponent(this.opts.token)}`;
  }

  /** Open the socket. resume=false starts a new segment (new page); true continues this page. */
  connect(resume: boolean): Promise<Welcome> {
    this.opts.onStatus?.(resume ? "reconnecting" : "connecting");
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url());
      this.ws = ws;
      let welcomed = false;
      ws.onopen = () => ws.send(JSON.stringify({ type: "hello", resume, epoch: resume ? this.epoch : null }));
      ws.onmessage = (msg) => {
        const m = JSON.parse(String(msg.data));
        if (m.type === "welcome") {
          welcomed = true;
          this.epoch = m.epoch;
          this.reconnectDelayMs = 500;
          if (this.opts.log.started) {
            this.opts.log.ack(m.next_client_seq);
            this.opts.log.resendFrom(m.next_client_seq);
          }
          this.opts.onStatus?.("open");
          resolve(m as Welcome);
          this.flush();
        } else if (m.type === "ack") {
          this.opts.log.ack(m.next_client_seq);
          this.notifyIfDrained();
        } else if (m.type === "nack") {
          this.opts.log.resendFrom(m.resend_from);
          this.flush();
        } else if (m.type === "ping") {
          const tClientUnixUs = Math.round((performance.timeOrigin + performance.now()) * 1000);
          ws.send(JSON.stringify({ type: "pong", id: m.id, t_client_unix_us: tClientUnixUs }));
        } else if (m.type === "error") {
          this.opts.onServerError?.(m.code, m.detail);
        }
      };
      ws.onclose = () => {
        if (!welcomed) reject(new Error("socket closed before welcome"));
        if (this.ws === ws && !this.closedByUs) this.scheduleReconnect();
      };
    });
  }

  private scheduleReconnect(): void {
    this.opts.onStatus?.("reconnecting");
    const delay = this.reconnectDelayMs;
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 10_000);
    window.setTimeout(() => {
      this.connect(true).catch(() => this.scheduleReconnect());
    }, delay);
  }

  /** Send every ready, unsent event (in batches of at most 500). */
  flush(): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN || !this.opts.log.started) return;
    for (;;) {
      const events = this.opts.log.takeUnsent(500);
      if (!events.length) break;
      ws.send(JSON.stringify({ type: "batch", batch: this.batch(events) }));
      this.lastSendAt = performance.now();
    }
    this.armResendTimer();
  }

  private batch(events: WireEvent[]): Record<string, unknown> {
    return { schema_version: "1.0", session_id: this.opts.sessionId, epoch: this.epoch, batch_seq: this.batchSeq++, events };
  }

  private armResendTimer(): void {
    window.clearTimeout(this.resendTimer);
    this.resendTimer = window.setTimeout(() => {
      const first = this.opts.log.firstUnacked();
      if (first !== undefined && performance.now() - this.lastSendAt >= this.opts.resendTimeoutMs) {
        this.opts.log.resendFrom(first);
        this.flush();
      }
    }, this.opts.resendTimeoutMs);
  }

  /** Resolves once every event created so far has been acked. */
  drained(timeoutMs = 10_000): Promise<boolean> {
    if (this.opts.log.unackedCount === 0) return Promise.resolve(true);
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => resolve(false), timeoutMs);
      this.waiters.push(() => {
        window.clearTimeout(timer);
        resolve(true);
      });
      this.flush();
    });
  }

  private notifyIfDrained(): void {
    if (this.opts.log.unackedCount === 0) {
      const waiters = this.waiters;
      this.waiters = [];
      waiters.forEach((w) => w());
    }
  }

  /** Last-chance delivery on pagehide. The server drops any prefix it already stored. */
  beacon(): boolean {
    const events = this.opts.log.readyUnacked(500);
    if (!events.length) return true;
    const body = JSON.stringify({ type: "batch", batch: this.batch(events) });
    const url = `/api/sessions/${this.opts.sessionId}/beacon?token=${encodeURIComponent(this.opts.token)}`;
    return navigator.sendBeacon(url, new Blob([body], { type: "text/plain" }));
  }

  close(): void {
    this.closedByUs = true;
    window.clearTimeout(this.resendTimer);
    this.ws?.close(1000);
    this.opts.onStatus?.("closed");
  }
}
