// SHA-256 helpers. The server computes the same values (backend/src/integrity_backend/replay.py).

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Clipboard hashes normalise line endings so copy and paste of the same text match (SPEC 4.5). */
export function normaliseClipboard(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}
