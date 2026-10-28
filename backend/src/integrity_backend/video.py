"""Webcam video during exam tasks (D-048): a DEMO feature, not analysed.

Chunks arrive from the browser's MediaRecorder (webm, no audio), one every few seconds. Each is
encrypted with the field key (AES-256-GCM, bound to its session and position) and written under the
data root; the database keeps only an index (session_videos). An admin can view the video; erasure
and retention delete the files with the session.

simulated_head_movement() makes the head-movement panel shown with a dev/synthetic session's video.
It is SIMULATED: random numbers seeded by the session id, NOT computed from the video, and never
used in a finding, flag or decision.
"""

from __future__ import annotations

import hashlib
import random
import shutil
from pathlib import Path
from typing import Any, Iterable

from .crypto import FieldCipher

SIMULATED_LABEL = "SIMULATED for the demo: not computed from the video, not used in any finding or decision"


class VideoFiles:
    """Encrypted chunk files: <root>/<session_id>/<index>.bin."""

    def __init__(self, root: Path, cipher: FieldCipher) -> None:
        self.root = root
        self.cipher = cipher

    @staticmethod
    def _aad(session_id: str, index: int) -> bytes:
        return f"video:{session_id}:{index}".encode("ascii")

    def _path(self, session_id: str, index: int) -> Path:
        return self.root / session_id / f"{index:06d}.bin"

    def write(self, session_id: str, index: int, data: bytes) -> None:
        path = self._path(session_id, index)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(self.cipher.encrypt(data, self._aad(session_id, index)))
        tmp.replace(path)

    def read(self, session_id: str, chunks: int) -> bytes:
        return b"".join(self.cipher.decrypt(self._path(session_id, i).read_bytes(), self._aad(session_id, i)) for i in range(chunks))

    def remove(self, session_id: str, index: int) -> None:
        self._path(session_id, index).unlink(missing_ok=True)

    def delete(self, session_ids: Iterable[str]) -> None:
        for sid in session_ids:
            shutil.rmtree(self.root / sid, ignore_errors=True)


def simulated_head_movement(session_id: str, duration_s: float, max_samples: int = 600) -> dict[str, Any]:
    """A SIMULATED head-yaw timeline and look-away summary, the same for the same session (seeded)."""
    rng = random.Random(hashlib.sha256(f"head-demo:{session_id}".encode()).hexdigest())
    step = max(2.0, duration_s / max_samples)
    samples, yaw, burst = [], 0.0, 0
    t = 0.0
    while t <= max(duration_s, step):
        if burst > 0:
            burst -= 1
        elif rng.random() < 0.025:                                  # an occasional look to one side
            burst = rng.randint(1, 3)
            yaw = rng.choice((-1, 1)) * rng.uniform(35, 60)
        else:
            yaw = 0.8 * yaw + rng.gauss(0, 5)
        samples.append({"t": round(t, 1), "yaw": round(yaw, 1)})
        t += step
    away, start = [], None
    for s in samples:
        if abs(s["yaw"]) > 30 and start is None:
            start = s
        elif abs(s["yaw"]) <= 30 and start is not None:
            away.append({"start": start["t"], "end": s["t"], "direction": "left" if start["yaw"] < 0 else "right"})
            start = None
    if start is not None:
        away.append({"start": start["t"], "end": samples[-1]["t"], "direction": "left" if start["yaw"] < 0 else "right"})
    facing = sum(1 for s in samples if abs(s["yaw"]) <= 30) / len(samples)
    return {
        "simulated": True, "label": SIMULATED_LABEL, "step_s": round(step, 1), "samples": samples,
        "look_aways": away, "facing_screen_share": round(facing, 3),
        "longest_look_away_s": round(max((a["end"] - a["start"] for a in away), default=0.0), 1),
    }
