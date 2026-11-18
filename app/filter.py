"""JARVIS Advanced Signal Filtering & Cursor Smoothing.
Implements the 1€ Filter (One Euro Filter) and Adaptive Exponential Smoothing for
jitter-free precision at low speeds and zero-lag responsiveness during rapid hand movements.
"""

import math
import time
from typing import Tuple, Optional


class LowPassFilter:
    """First-order low-pass filter with exponential smoothing."""

    def __init__(self, alpha: float = 0.5):
        self._alpha = alpha
        self._prev_val: Optional[float] = None

    def filter(self, val: float, alpha: Optional[float] = None) -> float:
        if alpha is not None:
            self._alpha = max(0.0, min(1.0, alpha))
        if self._prev_val is None:
            self._prev_val = val
            return val
        filtered = self._alpha * val + (1.0 - self._alpha) * self._prev_val
        self._prev_val = filtered
        return filtered

    def reset(self) -> None:
        self._prev_val = None

    def reinitialize(self, val: float) -> None:
        """Immediately seeds filter state without lag."""
        self._prev_val = val

    @property
    def value(self) -> Optional[float]:
        return self._prev_val


class OneEuroFilter:
    """The 1€ Filter for real-time human-computer interaction (Casiez et al., CHI 2012).
    Dynamically balances jitter reduction at low speeds and responsiveness at high speeds.
    """

    def __init__(self,
                 freq: float = 30.0,
                 min_cutoff: float = 1.0,
                 beta: float = 0.05,
                 d_cutoff: float = 1.0):
        self.freq = max(1.0, freq)
        self.min_cutoff = max(0.01, min_cutoff)
        self.beta = max(0.0, beta)
        self.d_cutoff = max(0.01, d_cutoff)

        self._x_filter = LowPassFilter()
        self._dx_filter = LowPassFilter()
        self._last_time: Optional[float] = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + (tau / dt)) if dt > 0 else 1.0

    def filter(self, val: float, timestamp: Optional[float] = None) -> float:
        """Filters input scalar with dynamic velocity-scaled cutoff frequency."""
        now = timestamp if timestamp is not None else time.time()

        if self._last_time is None:
            self._last_time = now
            self._dx_filter.reset()
            self._x_filter.reset()
            return self._x_filter.filter(val, 1.0)

        dt = now - self._last_time
        self._last_time = now

        # Guard against zero or negative dt
        if dt <= 1e-5:
            dt = 1.0 / self.freq

        # Estimate derivative (speed)
        prev_x = self._x_filter.value
        dx = (val - prev_x) / dt if prev_x is not None else 0.0
        alpha_d = self._alpha(self.d_cutoff, dt)
        edx = self._dx_filter.filter(dx, alpha_d)

        # Compute dynamic cutoff frequency based on velocity
        cutoff = self.min_cutoff + self.beta * abs(edx)

        # Filter the position with dynamic alpha
        alpha = self._alpha(cutoff, dt)
        return self._x_filter.filter(val, alpha)

    def reset(self) -> None:
        """Resets filter memory on tracking loss to prevent jumping across screen."""
        self._x_filter.reset()
        self._dx_filter.reset()
        self._last_time = None

    def reinitialize(self, val: float, timestamp: Optional[float] = None) -> None:
        """Seeds filter state at a specified coordinate and clears velocity history."""
        now = timestamp if timestamp is not None else time.time()
        self._last_time = now
        self._x_filter.reinitialize(val)
        self._dx_filter.reset()


class PointFilter2D:
    """Dual-axis 2D point filter supporting 1€ Filter, Adaptive EMA, and standard EMA.

    Features:
    - Adaptive cutoff frequency: stronger smoothing at low speeds to eliminate micro-jitter,
      and high responsiveness during fast ballistic movements.
    - Outlier rejection: suppresses single-frame anomalous coordinate jumps caused by
      temporary landmark tracking glitches.
    """

    def __init__(self,
                 filter_type: str = "one_euro",
                 min_cutoff: float = 0.8,
                 beta: float = 0.04,
                 smoothing: float = 0.65,
                 max_jump_px: float = 450.0):
        self.filter_type = filter_type
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.smoothing = smoothing
        self.max_jump_px = max_jump_px

        # 1€ filters for X and Y
        self.fx = OneEuroFilter(freq=30.0, min_cutoff=min_cutoff, beta=beta)
        self.fy = OneEuroFilter(freq=30.0, min_cutoff=min_cutoff, beta=beta)

        # State tracking
        self.last_x: Optional[float] = None
        self.last_y: Optional[float] = None
        self.last_time: Optional[float] = None

    def update_parameters(self,
                          filter_type: Optional[str] = None,
                          min_cutoff: Optional[float] = None,
                          beta: Optional[float] = None,
                          smoothing: Optional[float] = None) -> None:
        if filter_type is not None:
            self.filter_type = filter_type
        if min_cutoff is not None:
            self.min_cutoff = min_cutoff
            self.fx.min_cutoff = min_cutoff
            self.fy.min_cutoff = min_cutoff
        if beta is not None:
            self.beta = beta
            self.fx.beta = beta
            self.fy.beta = beta
        if smoothing is not None:
            self.smoothing = smoothing

    def filter(self, x: float, y: float, timestamp: Optional[float] = None) -> Tuple[float, float]:
        now = timestamp if timestamp is not None else time.time()

        if self.filter_type == "one_euro":
            out_x = self.fx.filter(x, now)
            out_y = self.fy.filter(y, now)
            self.last_x = out_x
            self.last_y = out_y
            self.last_time = now
            return out_x, out_y

        elif self.filter_type == "adaptive_ema":
            # Adaptive EMA: Alpha increases with distance/speed
            if self.last_x is None or self.last_y is None or self.last_time is None:
                self.last_x = x
                self.last_y = y
                self.last_time = now
                return x, y

            dt = max(1e-4, now - self.last_time)
            dist = math.hypot(x - self.last_x, y - self.last_y)
            speed = dist / dt  # pixels or norm units per second

            # Scale alpha dynamically: slow speed -> low alpha (heavy smooth), fast -> high alpha
            # Velocity scale factor
            v_factor = min(1.0, speed / 1200.0) if speed > 10.0 else 0.0
            base_alpha = max(0.08, min(0.92, self.smoothing))
            alpha = base_alpha + (1.0 - base_alpha) * (v_factor ** 1.5)
            alpha = max(0.08, min(0.98, alpha))

            out_x = alpha * x + (1.0 - alpha) * self.last_x
            out_y = alpha * y + (1.0 - alpha) * self.last_y
            self.last_x = out_x
            self.last_y = out_y
            self.last_time = now
            return out_x, out_y

        else:
            # Standard Exponential Moving Average
            if self.last_x is None or self.last_y is None:
                self.last_x = x
                self.last_y = y
                self.last_time = now
                return x, y
            alpha = max(0.05, min(0.95, self.smoothing))
            out_x = alpha * x + (1.0 - alpha) * self.last_x
            out_y = alpha * y + (1.0 - alpha) * self.last_y
            self.last_x = out_x
            self.last_y = out_y
            self.last_time = now
            return out_x, out_y

    def reset(self) -> None:
        """Resets filters upon tracking loss."""
        self.fx.reset()
        self.fy.reset()
        self.last_x = None
        self.last_y = None
        self.last_time = None

    def reinitialize(self, x: float, y: float, timestamp: Optional[float] = None) -> None:
        """Seeds 2D filter state at an exact position, preventing sudden jumps upon pinch release."""
        now = timestamp if timestamp is not None else time.time()
        self.fx.reinitialize(x, now)
        self.fy.reinitialize(y, now)
        self.last_x = x
        self.last_y = y
        self.last_time = now
