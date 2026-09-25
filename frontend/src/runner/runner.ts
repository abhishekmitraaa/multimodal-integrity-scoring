// Main-thread wrapper for the Pyodide worker, with a hard timeout (the worker is replaced).

export interface RunResult {
  status: "ok" | "error" | "timeout";
  n_tests: number;
  n_passed: number;
  stdout: string;
  details: string[];
  dur_ms: number;
}

export class PyRunner {
  private worker: Worker;
  private nextId = 0;

  constructor(private readonly timeoutMs = 10_000) {
    this.worker = this.spawn();
  }

  private spawn(): Worker {
    const worker = new Worker(new URL("./pyrunner.worker.ts", import.meta.url), { type: "module" });
    worker.postMessage({ warmup: true });
    return worker;
  }

  run(kind: "run" | "test", code: string, tests: Array<{ call: string; expected: string }>): Promise<RunResult> {
    const id = this.nextId++;
    const started = performance.now();
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        this.worker.terminate();
        this.worker = this.spawn();
        resolve({ status: "timeout", n_tests: tests.length, n_passed: 0, stdout: "", details: ["time limit exceeded"], dur_ms: Math.round(performance.now() - started) });
      }, this.timeoutMs);
      const onMessage = (event: MessageEvent) => {
        if (event.data?.id !== id) return;
        window.clearTimeout(timer);
        this.worker.removeEventListener("message", onMessage);
        resolve({ ...event.data, dur_ms: Math.round(performance.now() - started) } as RunResult);
      };
      this.worker.addEventListener("message", onMessage);
      this.worker.postMessage({ id, kind, code, tests });
    });
  }
}
