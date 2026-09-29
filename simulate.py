"""Run the subtitle pipeline on a recorded audio file (no GUI) and write a session log.

    uv run python simulate.py lecture.wav [--start 1800] [--duration 300] [--realtime]

Audio must be 16 kHz mono 16-bit WAV (ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 out.wav).
Without --realtime the file is fed as fast as possible (quality check);
with --realtime it is paced like a live microphone (latency check).
"""
import argparse
import time
import wave

import numpy as np

from config import config
from main import Pipeline


class FileAudio:
    def __init__(self, path, start=0.0, duration=None, realtime=False):
        self.wav = wave.open(path, "rb")
        assert self.wav.getnchannels() == 1 and self.wav.getsampwidth() == 2
        self.sample_rate = self.wav.getframerate()
        assert self.sample_rate == config.sample_rate, f"expected {config.sample_rate} Hz"
        self.silence_threshold = config.silence_threshold
        self.max_phrase_duration = config.max_phrase_duration
        self.wav.setpos(int(start * self.sample_rate))
        self.remaining = int(duration * self.sample_rate) if duration else None
        self.realtime = realtime
        self.running = True

    def generator(self):
        step = int(self.sample_rate * config.streaming_step_size)
        t0 = time.time()
        sent = 0
        while self.running:
            n = step if self.remaining is None else min(step, self.remaining)
            frames = self.wav.readframes(n) if n > 0 else b""
            if not frames:
                break
            chunk = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768
            sent += len(chunk)
            if self.remaining is not None:
                self.remaining -= len(chunk)
            if self.realtime:
                time.sleep(max(0.0, sent / self.sample_rate - (time.time() - t0)))
            yield chunk

    def stop(self):
        self.running = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--start", type=float, default=0.0, help="start offset in seconds")
    ap.add_argument("--duration", type=float, default=None, help="seconds to process")
    ap.add_argument("--realtime", action="store_true", help="pace input like a live microphone")
    args = ap.parse_args()

    pipeline = Pipeline(audio=FileAudio(args.wav, args.start, args.duration, args.realtime))
    pipeline.signals.update_text.connect(lambda cid, ja, en: None)
    t0 = time.time()
    pipeline.start()
    pipeline.thread.join()
    pipeline.logger.close()
    print(f"[Simulate] Done in {time.time() - t0:.1f}s -> {pipeline.logger.dir}")


if __name__ == "__main__":
    main()
