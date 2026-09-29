"""Per-session log: raw audio (WAV) + one JSON line per finalized subtitle segment.

Layout: <log_dir>/<YYYYmmdd-HHMMSS>/{audio.wav, segments.jsonl, meta.json}
wave.writeframes() patches the header on every write and each JSON line is
flushed, so the log stays readable even if the app is force-killed.
"""
import json
import os
import threading
import time
import wave

import numpy as np


class SessionLogger:
    def __init__(self, log_dir, sample_rate, save_audio=True, meta=None):
        self.sample_rate = sample_rate
        self.dir = os.path.join(os.path.expanduser(log_dir), time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self.started_at = time.time()

        with open(os.path.join(self.dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "sample_rate": sample_rate, **(meta or {})}, f, ensure_ascii=False, indent=2)

        self._wav = None
        if save_audio:
            self._wav = wave.open(os.path.join(self.dir, "audio.wav"), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(sample_rate)
        self._jsonl = open(os.path.join(self.dir, "segments.jsonl"), "a", encoding="utf-8")
        print(f"[SessionLogger] Logging to {self.dir}")

    def write_audio(self, chunk):
        if self._wav is None:
            return
        pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        with self._lock:
            self._wav.writeframes(pcm)

    def write_segment(self, **record):
        with self._lock:
            self._jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._jsonl.flush()

    def close(self):
        with self._lock:
            if self._wav is not None:
                self._wav.close()
                self._wav = None
            if not self._jsonl.closed:
                self._jsonl.close()
