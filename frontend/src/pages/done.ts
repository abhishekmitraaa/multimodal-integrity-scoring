// Submission receipt. The head hash is unsigned in P1 (D-017); keeping it still lets the
// participant detect a later rewrite of their log.

import { h } from "../dom";

export function donePage(root: HTMLElement, query: URLSearchParams): void {
  root.replaceChildren(
    h("main", { class: "narrow" },
      h("h1", {}, "Submitted"),
      h("p", {}, "Your session is closed. This is your receipt:"),
      h("dl", { class: "receipt" },
        h("dt", {}, "Events recorded"), h("dd", { id: "n-events" }, query.get("n") ?? "?"),
        h("dt", {}, "Log fingerprint (head hash)"), h("dd", {}, h("code", { id: "head-hash" }, query.get("head") ?? "?")),
      ),
      h("p", { class: "muted" }, "Keep this fingerprint if you might appeal: it changes if anyone later alters your log. It is not yet signed by the server."),
      query.get("drained") === "0" ? h("p", { class: "error", id: "undelivered" }, "Some events may not have been delivered before closing.") : null,
      h("a", { href: "#/setup" }, "Another task"),
    ),
  );
}
