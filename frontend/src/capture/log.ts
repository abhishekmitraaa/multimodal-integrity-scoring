// Client event log: assigns client_seq at creation and keeps every event until the server acks it
// (SPEC 4.2). Some events need an async hash; their slot is reserved so order is preserved and
// only the ready prefix is ever sent.

export interface WireEvent {
  client_seq: number;
  type: string;
  t_client_us: number;
  data: Record<string, unknown>;
}

interface Slot {
  event: WireEvent;
  ready: boolean;
}

export function toMicros(ms: number): number {
  return Math.max(0, Math.round(ms * 1000));
}

export class EventLog {
  private slots: Slot[] = [];
  private nextSeq = 0;
  private sentUpTo = 0; // first client_seq not yet sent on the current connection
  private keydownsSinceFlush = 0;
  private oldestUnsentAt: number | null = null;
  started = false;
  onPriority: () => void = () => {};

  /** Called once the server's welcome says where this page's sequence starts. */
  start(firstSeq: number): void {
    this.nextSeq = firstSeq;
    this.sentUpTo = firstSeq;
    this.started = true;
  }

  push(type: string, data: Record<string, unknown>, tMs: number = performance.now(), priority = false): WireEvent {
    const event = { client_seq: this.nextSeq++, type, t_client_us: toMicros(tMs), data };
    this.slots.push({ event, ready: true });
    this.noteNew(type, priority);
    return event;
  }

  /** Reserve the next seq now; the data arrives later (e.g. after crypto.subtle hashing). */
  pushAsync(type: string, data: Promise<Record<string, unknown>>, tMs: number = performance.now(), priority = false): void {
    const slot: Slot = { event: { client_seq: this.nextSeq++, type, t_client_us: toMicros(tMs), data: {} }, ready: false };
    this.slots.push(slot);
    this.noteNew(type, priority);
    void data.then((d) => {
      slot.event.data = d;
      slot.ready = true;
      if (priority) this.onPriority();
    });
  }

  private noteNew(type: string, priority: boolean): void {
    if (type === "keydown") this.keydownsSinceFlush++;
    this.oldestUnsentAt ??= performance.now();
    if (priority) this.onPriority();
  }

  /** Ready, unsent events in seq order, stopping at the first pending slot. */
  takeUnsent(max = 500): WireEvent[] {
    const out: WireEvent[] = [];
    for (const slot of this.slots) {
      if (slot.event.client_seq < this.sentUpTo) continue;
      if (!slot.ready || out.length >= max) break;
      out.push(slot.event);
    }
    if (out.length) {
      this.sentUpTo = out[out.length - 1].client_seq + 1;
      this.keydownsSinceFlush = 0;
      this.oldestUnsentAt = this.hasUnsent() ? performance.now() : null;
    }
    return out;
  }

  hasUnsent(): boolean {
    return this.slots.some((s) => s.event.client_seq >= this.sentUpTo);
  }

  /** All unacked events that are ready, from the oldest (for beacons). */
  readyUnacked(max = 500): WireEvent[] {
    const out: WireEvent[] = [];
    for (const slot of this.slots) {
      if (!slot.ready || out.length >= max) break;
      out.push(slot.event);
    }
    return out;
  }

  ack(nextClientSeq: number): void {
    this.slots = this.slots.filter((s) => s.event.client_seq >= nextClientSeq);
    if (this.sentUpTo < nextClientSeq) this.sentUpTo = nextClientSeq;
  }

  resendFrom(seq: number): void {
    this.sentUpTo = Math.min(this.sentUpTo, seq);
  }

  /** Oldest unacked seq, or undefined if everything is acked. */
  firstUnacked(): number | undefined {
    return this.slots[0]?.event.client_seq;
  }

  get unackedCount(): number {
    return this.slots.length;
  }

  flushDue(maxKeydowns: number, maxAgeMs: number, now = performance.now()): boolean {
    if (!this.hasUnsent()) return false;
    return this.keydownsSinceFlush >= maxKeydowns || (this.oldestUnsentAt !== null && now - this.oldestUnsentAt >= maxAgeMs);
  }
}
