"""Adaptive silence threshold from the running level of the input.

The threshold that separates pauses from speech depends on the microphone gain and the
room, so a fixed value (e.g. 0.005) can sit right at the speaker's level and chop speech
into fragments. Instead, track the RMS of each incoming block over a sliding window:

    noise  = 10th percentile of block RMS   (pauses, room noise)
    speech = 90th percentile of block RMS   (voiced speech)
    threshold = clamp(min(noise * 2, noise**0.7 * speech**0.3), floor, ceiling)

noise * 2 keeps the threshold just above the room noise; the noise-weighted geometric
mean keeps it well below the speaker's typical level when noise and speech are close
(an equal-weight mean sat at the median speech level and still split quiet phrases).
Until warmup_sec of audio has been seen, the initial threshold is used.
"""
from collections import deque

import numpy as np


class AdaptiveThreshold:
    def __init__(self, sample_rate, initial=0.005, window_sec=60.0, warmup_sec=3.0,
                 floor=0.0005, ceiling=0.05):
        self.sample_rate = sample_rate
        self.value = initial
        self.window_sec = window_sec
        self.warmup_sec = warmup_sec
        self.floor = floor
        self.ceiling = ceiling
        self._levels = deque()   # (block_sec, rms)
        self._seconds = 0.0
        self.noise = None
        self.speech = None

    def update(self, block):
        """Feed one audio block; returns the current threshold"""
        if len(block) == 0:
            return self.value
        sec = len(block) / self.sample_rate
        self._levels.append((sec, float(np.sqrt(np.mean(block ** 2)))))
        self._seconds += sec
        while self._seconds - self._levels[0][0] > self.window_sec:
            self._seconds -= self._levels.popleft()[0]
        if self._seconds < self.warmup_sec:
            return self.value
        rms = np.fromiter((r for _, r in self._levels), dtype=np.float64)
        self.noise, self.speech = np.percentile(rms, [10, 90])
        target = min(self.noise * 2, self.noise ** 0.7 * self.speech ** 0.3)
        self.value = float(np.clip(target, self.floor, self.ceiling))
        return self.value
