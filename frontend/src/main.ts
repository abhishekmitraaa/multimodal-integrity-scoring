import "./style.css";
import { consentPage } from "./pages/consent";
import { donePage } from "./pages/done";
import { keycheckPage } from "./pages/keycheck";
import { replayPage } from "./pages/replay";
import { sessionPage } from "./pages/session";
import { setupPage } from "./pages/setup";

const root = document.getElementById("app")!;
let current = "";

async function route(): Promise<void> {
  const [path, query = ""] = location.hash.slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  // A session page owns a live socket and listeners. Leaving it other than by submitting
  // (which closes both) reloads the page for a clean state.
  if (current === "session" && parts[0] !== "done") {
    location.reload();
    return;
  }
  current = parts[0] ?? "";
  if (parts[0] === "setup") return setupPage(root);
  if (parts[0] === "session" && parts[1]) return sessionPage(root, parts[1]);
  if (parts[0] === "done" && parts[1]) return donePage(root, new URLSearchParams(query));
  if (parts[0] === "replay") return replayPage(root);
  if (parts[0] === "keycheck") return keycheckPage(root, new URLSearchParams(query));
  return consentPage(root);
}

window.addEventListener("hashchange", () => void route());
void route();
