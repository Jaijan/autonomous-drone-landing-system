"""Recognize repeated equal ON/OFF beacon pulses from timestamped observations."""
import math


class BlinkDecoder:
    def __init__(self, config, cycles=3, max_frame_gap=.2):
        self.config = config
        self.required_cycles = cycles
        self.max_frame_gap = max_frame_gap
        self.last_time = None
        self.reset()

    def reset(self):
        self.state = None
        self.since = None
        self.on_valid = False
        self.cycles = 0
        self.quality = 1.0

    def feed(self, timestamp, state, quality=1.0):
        if not math.isfinite(timestamp) or (self.last_time is not None and timestamp <= self.last_time):
            raise ValueError('Timestamps must be finite and strictly increasing')
        interrupted = self.last_time is not None and timestamp - self.last_time > self.max_frame_gap
        self.last_time = timestamp
        if interrupted or state is None or not math.isfinite(quality) or quality < self.config.minimum_quality:
            self.reset()
            return None
        if self.state is None:
            self.state, self.since = state, timestamp
            return None
        elapsed = timestamp - self.since
        self.quality = min(self.quality, quality)
        if state == self.state:
            if elapsed > self.config.unit * (1 + self.config.tolerance):
                self.cycles, self.on_valid = 0, False
            return None
        previous = self.state
        self.state, self.since = state, timestamp
        valid = abs(elapsed / self.config.unit - 1) <= self.config.tolerance
        if previous:
            self.on_valid = valid
            if not valid:
                self.cycles = 0
            return None
        if not valid or not self.on_valid:
            self.cycles, self.on_valid, self.quality = 0, False, 1.0
            return None
        self.cycles += 1
        self.on_valid = False
        if self.cycles < self.required_cycles:
            return None
        result = self.config.message, self.quality
        self.cycles, self.quality = 0, 1.0
        return result


def simulate_blink(unit, cycles=6):
    # Sample continuously so the simulator exercises acquisition continuity too.
    step = unit / 10
    for segment in range(2 * cycles + 2):
        state = bool(segment % 2)
        for sample in range(10):
            yield segment * unit + sample * step, state, 1.0
