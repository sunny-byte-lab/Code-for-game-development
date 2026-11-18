"""N.E.X.U.S. Signal Smoothing Filters.
Pure Python implementations of One-Euro Filter and Exponential Smoothing.
"""

import math
import time
from typing import Tuple, Optional


class LowPassFilter:
    """Standard first-order low-pass filter."""

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self.y: Optional[float] = None

    def filter(self, x: float, alpha: Optional[float] = None) -> float:
        a = self.alpha if alpha is None else alpha
        if self.y is None:
            self.y = x
        else:
            self.y = a * x + (1.0 - a) * self.y
        return self.y

    def reset(self) -> None:
        self.y = None


class OneEuroFilter:
    """1€ Filter: Adaptive low-pass filter with speed-sensitive cutoff.
    Provides jitter reduction at low speeds and zero lag at high speeds.
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_filter = LowPassFilter()
        self.dx_filter = LowPassFilter()
        self.last_time: Optional[float] = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, timestamp: Optional[float] = None) -> float:
        t = timestamp if timestamp is not None else time.time()
        if self.last_time is None or t <= self.last_time:
            self.last_time = t
            return self.x_filter.filter(x, 1.0)

        dt = max(1e-4, t - self.last_time)
        self.last_time = t

        # Estimate derivative (speed)
        prev_x = self.x_filter.y if self.x_filter.y is not None else x
        dx = (x - prev_x) / dt
        edx = self.dx_filter.filter(dx, self._alpha(self.d_cutoff, dt))

        # Dynamic cutoff
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self.x_filter.filter(x, self._alpha(cutoff, dt))

    def reset(self) -> None:
        self.x_filter.reset()
        self.dx_filter.reset()
        self.last_time = None


class PointFilter2D:
    """Dual-axis One-Euro filter for 2D coordinates."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02):
        self.fx = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)
        self.fy = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)

    def filter(self, x: float, y: float, timestamp: Optional[float] = None) -> Tuple[float, float]:
        return self.fx.filter(x, timestamp), self.fy.filter(y, timestamp)

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()
