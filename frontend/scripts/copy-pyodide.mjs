// Copies the Pyodide runtime from node_modules to public/pyodide so it is served from our own
// origin (no CDN on the data path, and it works under COOP/COEP).
import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "pyodide");
const dst = join(root, "public", "pyodide");
mkdirSync(dst, { recursive: true });
for (const f of ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]) {
  cpSync(join(src, f), join(dst, f));
}
console.log(`copied pyodide runtime to ${dst}`);
