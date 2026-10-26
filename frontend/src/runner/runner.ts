// Main-thread wrapper for the Pyodide worker, with a hard timeout (the worker is replaced).
//
// The execution limit covers running the student's code only. Loading the Python runtime is
// waited for separately (it can take well over 10 s on a slow machine or the first visit), so a
// student who clicks Test early is not told "time limit exceeded" for a runtime that was loading.

export interface RunResult {
  status: "ok" | "error" | "timeout";
  n_tests: number;
  n_passed: number;
  stdout: string;
  details: string[];
  dur_ms: number;
}

export class PyRunner {
  private worker!: Worker;
  private ready!: Promise<boolean>;
  private isReady = false;
  private nextId = 0;

  constructor(private readonly timeoutMs = 10_000, private readonly loadTimeoutMs = 180_000) {
    this.spawn();
  }

  /** True once the Python runtime in the current worker has loaded. */
  get loaded(): boolean {
    return this.isReady;
  }

  private spawn(): void {
    this.isReady = false;
    const worker = new Worker(new URL("./pyrunner.worker.ts", import.meta.url), { type: "module" });
    this.ready = new Promise<boolean>((resolve) => {
      const timer = window.setTimeout(() => resolve(false), this.loadTimeoutMs);
      const onWarm = (event: MessageEvent) => {
        if (!event.data?.warm) return;
        window.clearTimeout(timer);
        worker.removeEventListener("message", onWarm);
        this.isReady = true;
        resolve(true);
      };
      worker.addEventListener("message", onWarm);
    });
    worker.postMessage({ warmup: true });
    this.worker = worker;
  }

  async run(kind: "run" | "test", code: string, tests: Array<{ call: string; expected: string }>): Promise<RunResult> {
    const id = this.nextId++;
    const started = performance.now();
    if (!(await this.ready)) {
      this.worker.terminate();
      this.spawn();
      return { status: "error", n_tests: tests.length, n_passed: 0, stdout: "", dur_ms: Math.round(performance.now() - started),
        details: ["Python could not start in this browser. Reload the page and try again."] };
    }
    const runStarted = performance.now();
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        this.worker.terminate();
        this.spawn();
        resolve({ status: "timeout", n_tests: tests.length, n_passed: 0, stdout: "", details: ["time limit exceeded"], dur_ms: Math.round(performance.now() - runStarted) });
      }, this.timeoutMs);
      const onMessage = (event: MessageEvent) => {
        if (event.data?.id !== id) return;
        window.clearTimeout(timer);
        this.worker.removeEventListener("message", onMessage);
        resolve({ ...event.data, dur_ms: Math.round(performance.now() - runStarted) } as RunResult);
      };
      this.worker.addEventListener("message", onMessage);
      this.worker.postMessage({ id, kind, code, tests });
    });
  }
}
