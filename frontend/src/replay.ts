// Client-side replay for the reviewer view. JS strings are UTF-16, so Monaco offsets apply directly.
// Monaco orders multi-change events from the end of the document to the start, so applying them
// in sequence is safe; we sort by offset (descending) anyway, as the server does.

export interface ChangeData {
  version_id: number;
  idx: number;
  n: number;
  offset: number;
  del_len: number;
  text: string;
  flush: boolean;
}

export interface ReplayEvent {
  server_seq: number;
  type: string;
  data: Record<string, unknown>;
}

export function replayText(events: ReplayEvent[], uptoServerSeq = Number.POSITIVE_INFINITY): string {
  let doc = "";
  let group: ChangeData[] = [];
  const applyGroup = () => {
    for (const c of [...group].sort((a, b) => b.offset - a.offset)) {
      doc = c.flush ? c.text : doc.slice(0, c.offset) + c.text + doc.slice(c.offset + c.del_len);
    }
    group = [];
  };
  for (const e of events) {
    if (e.server_seq > uptoServerSeq) break;
    if (e.type === "content_change") {
      const c = e.data as unknown as ChangeData;
      group.push(c);
      if (c.idx === c.n - 1) applyGroup();
    } else if (e.type === "snapshot") {
      applyGroup();
      if ((e.data as { reason?: string }).reason === "segment_start") doc = String(e.data.text);
    }
  }
  applyGroup();
  return doc;
}
