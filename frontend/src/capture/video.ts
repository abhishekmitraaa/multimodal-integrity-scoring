// Webcam recording during an exam task (D-048): a DEMO feature, only after the participant ticked the
// separate video box. Video only, no audio. MediaRecorder hands over a chunk every chunkMs; chunks are
// uploaded in order and the server stores them encrypted. Nothing analyses the video.

export class WebcamRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private seq = 0;
  private queue: Promise<void> = Promise.resolve();
  private stopped: Promise<void> | null = null;
  failures = 0;

  constructor(private sessionId: string, private token: string, private chunkMs: number) {}

  /** Starts the camera and the recorder; resolves false if the camera is unavailable or refused. */
  async start(preview: HTMLVideoElement): Promise<boolean> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 360, frameRate: 15 }, audio: false });
    } catch {
      return false;
    }
    preview.srcObject = this.stream;
    preview.muted = true;
    void preview.play().catch(() => undefined);
    const type = ["video/webm;codecs=vp8", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t));
    this.recorder = new MediaRecorder(this.stream, type ? { mimeType: type, videoBitsPerSecond: 500_000 } : undefined);
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.enqueue(e.data);
    };
    this.recorder.start(this.chunkMs);
    return true;
  }

  private enqueue(blob: Blob): void {
    const seq = this.seq++;
    this.queue = this.queue.then(() => this.upload(seq, blob));
  }

  private async upload(seq: number, blob: Blob): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const res = await fetch(`/api/sessions/${this.sessionId}/video?seq=${seq}`, {
          method: "POST", body: blob, headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/octet-stream" },
        });
        if (res.ok) return;
        if (res.status !== 409 && res.status < 500) break;        // refused for good (no consent, closed): stop retrying
      } catch {
        // network hiccup: retry
      }
    }
    this.failures++;
  }

  /** Stops recording and waits until the last chunk is uploaded (call before submitting the exam). */
  stop(): Promise<void> {
    if (this.stopped) return this.stopped;
    this.stopped = new Promise<void>((resolve) => {
      const done = () => {
        this.stream?.getTracks().forEach((t) => t.stop());
        void this.queue.then(() => resolve());
      };
      if (!this.recorder || this.recorder.state === "inactive") return done();
      this.recorder.addEventListener("stop", done, { once: true });
      this.recorder.stop();
    });
    return this.stopped;
  }
}
