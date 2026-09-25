// Runs student Python in Pyodide inside a Web Worker (decision Q2).
// Results are client-reported and forgeable; they feed only the run-cadence feature, never grading.
//
// exec/eval below are deliberate: running the student's own code is this worker's purpose. It runs
// in Pyodide's WebAssembly sandbox, in the student's own browser tab, never on the server. Test
// calls come from our problem files; expected values are parsed with ast.literal_eval.

interface RunRequest {
  id: number;
  kind: "run" | "test";
  code: string;
  tests: Array<{ call: string; expected: string }>;
}

interface Pyodide {
  globals: { set(name: string, value: unknown): void };
  runPythonAsync(code: string): Promise<unknown>;
}

const HARNESS = `
import ast, contextlib, io, json, traceback
_tests = json.loads(__tests) if __kind == "test" else []
_ns = {"__name__": "__main__"}
_out = io.StringIO()
_status, _passed, _details = "ok", 0, []
try:
    with contextlib.redirect_stdout(_out):
        exec(compile(__src, "<student>", "exec"), _ns)
except BaseException:
    _status = "error"
    _details.append(traceback.format_exc(limit=3))
if _status == "ok":
    for _t in _tests:
        try:
            with contextlib.redirect_stdout(_out):
                _got = eval(_t["call"], _ns)
            _ok = _got == ast.literal_eval(_t["expected"])
            if not _ok:
                _details.append(f"{_t['call']} returned {_got!r}, expected {_t['expected']}")
        except BaseException as _e:
            _ok = False
            _details.append(f"{_t['call']}: {type(_e).__name__}: {_e}")
        _passed += bool(_ok)
json.dumps({"status": _status, "n_tests": len(_tests), "n_passed": _passed,
            "stdout": _out.getvalue()[-4000:], "details": _details[-5:]})
`;

let pyodide: Promise<Pyodide> | null = null;

function load(): Promise<Pyodide> {
  pyodide ??= (async () => {
    const url = `${self.location.origin}/pyodide/pyodide.mjs`;
    const mod = (await import(/* @vite-ignore */ url)) as { loadPyodide(o: { indexURL: string }): Promise<Pyodide> };
    return mod.loadPyodide({ indexURL: `${self.location.origin}/pyodide/` });
  })();
  return pyodide;
}

self.onmessage = async (event: MessageEvent<RunRequest | { warmup: true }>) => {
  const req = event.data;
  if ("warmup" in req) {
    await load();
    self.postMessage({ warm: true });
    return;
  }
  try {
    const py = await load();
    py.globals.set("__src", req.code);
    py.globals.set("__tests", JSON.stringify(req.tests));
    py.globals.set("__kind", req.kind);
    const result = JSON.parse(String(await py.runPythonAsync(HARNESS)));
    self.postMessage({ id: req.id, ...result });
  } catch (err) {
    self.postMessage({ id: req.id, status: "error", n_tests: req.tests.length, n_passed: 0, stdout: "", details: [String(err)] });
  }
};
