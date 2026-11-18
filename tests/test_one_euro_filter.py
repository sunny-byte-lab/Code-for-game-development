"""Unit tests for the 1€ Filter (One Euro Filter), Adaptive EMA, and reset mechanics."""

import math
import time
import pytest
from app.filter import OneEuroFilter, PointFilter2D


class TestOneEuroFilter:
    def test_low_speed_jitter_reduction(self):
        """At low speeds (near zero velocity), min_cutoff should heavily filter high-frequency noise."""
        filt = OneEuroFilter(freq=30.0, min_cutoff=0.5, beta=0.01)

        t = 0.0
        base_val = 100.0
        outputs = []
        # Simulate small noisy tremor (+/- 1.5 pixels) around 100.0
        for i in range(25):
            noise = 1.5 if i % 2 == 0 else -1.5
            noisy_input = base_val + noise
            out = filt.filter(noisy_input, timestamp=t)
            outputs.append(out)
            t += 0.033

        # After filtering, variance should be significantly reduced compared to raw 1.5 noise
        late_outputs = outputs[10:]
        deviations = [abs(v - base_val) for v in late_outputs]
        max_deviation = max(deviations)
        assert max_deviation < 0.8, f"Expected jitter to be filtered below 0.8, got {max_deviation}"

    def test_high_speed_responsiveness(self):
        """At high speeds, beta should dynamically increase cutoff frequency to eliminate lag."""
        filt = OneEuroFilter(freq=30.0, min_cutoff=1.0, beta=0.1)

        t = 0.0
        # Initialize at 100
        filt.filter(100.0, timestamp=t)
        t += 0.033

        # Sudden rapid motion from 100 to 500 (400 px displacement in 0.033s = ~12000 px/s)
        fast_out = filt.filter(500.0, timestamp=t)

        # Output should jump immediately toward 500 (over 70% of the distance) without sluggish lag
        assert fast_out > 380.0, f"Expected responsive jump > 380.0, got {fast_out}"

    def test_tracking_loss_reset_prevents_jump(self):
        """Resetting filter clears memory so hand re-entry does not rubber-band."""
        filt = PointFilter2D(filter_type="one_euro")

        # Hand tracked at (100, 100)
        filt.filter(100.0, 100.0, timestamp=1.0)
        filt.filter(102.0, 101.0, timestamp=1.033)

        # Hand lost for 2 seconds, tracking resets
        filt.reset()

        # Hand re-enters at completely different location (800, 600)
        out_x, out_y = filt.filter(800.0, 600.0, timestamp=3.0)

        # First point after reset should immediately adopt new coordinate, not average with (100, 100)
        assert out_x == 800.0
        assert out_y == 600.0

    def test_adaptive_ema_filter(self):
        """Tests adaptive EMA dynamic velocity scaling."""
        filt = PointFilter2D(filter_type="adaptive_ema", smoothing=0.3)

        # Stationary point
        filt.filter(200.0, 200.0, timestamp=0.0)
        # Slow drift
        slow_x, slow_y = filt.filter(205.0, 205.0, timestamp=0.033)
        assert slow_x < 205.0  # Heavy smooth applied

        # Fast ballistic motion
        fast_x, fast_y = filt.filter(600.0, 600.0, timestamp=0.066)
        # Should rapidly follow fast movement
        assert fast_x > 400.0
