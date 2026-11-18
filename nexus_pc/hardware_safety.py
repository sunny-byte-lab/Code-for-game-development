"""N.E.X.U.S. Windows Hardware Safety & Mouse Conflict Resolver.
Guarantees mouse button release and prevents physical/virtual mouse input fighting.
"""

import time
import math
import logging
import ctypes
from typing import Tuple, Optional, Callable

logger = logging.getLogger("NEXUS.PC.Safety")


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class HardwareConflictResolver:
    """Detects physical hardware mouse movement and yields virtual control to prevent fighting."""

    def __init__(self, movement_threshold: float = 22.0, yield_duration_seconds: float = 1.0, enabled: bool = True):
        self.movement_threshold = movement_threshold
        self.yield_duration_seconds = yield_duration_seconds
        self.enabled = enabled
        self._last_virtual_pos: Optional[Tuple[int, int]] = None
        self._yield_until: float = 0.0
        self._user32 = getattr(ctypes.windll, "user32", None) if hasattr(ctypes, "windll") else None

    def get_real_cursor_pos(self) -> Tuple[int, int]:
        """Queries physical Windows desktop cursor position via GetCursorPos."""
        if not self._user32 or not hasattr(self._user32, "GetCursorPos"):
            return 0, 0
        pt = POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def record_virtual_move(self, x: int, y: int) -> None:
        """Records an intentional virtual mouse move coordinates."""
        self._last_virtual_pos = (x, y)

    def is_physical_mouse_active(self) -> bool:
        """Returns True if the physical hardware mouse was moved externally."""
        if not self.enabled or not self._user32 or not hasattr(self._user32, "GetCursorPos"):
            return False

        now = time.time()
        if now < self._yield_until:
            return True

        if self._last_virtual_pos is None:
            return False

        real_x, real_y = self.get_real_cursor_pos()
        vx, vy = self._last_virtual_pos
        dist = math.hypot(real_x - vx, real_y - vy)

        if dist > self.movement_threshold:
            # Physical mouse moved by user! Yield control
            logger.info(f"[HARDWARE CONFLICT] Physical mouse movement detected (delta: {dist:.1f}px). Yielding virtual mouse for {self.yield_duration_seconds:.1f}s.")
            self._yield_until = now + self.yield_duration_seconds
            return True

        return False

    def reset_yield(self) -> None:
        self._yield_until = 0.0
        self._last_virtual_pos = None


class GuaranteedButtonReleaseGuard:
    """Guarantees that a pressed mouse button is safely released."""

    def __init__(self, release_callback: Callable[[str], None], max_click_duration: float = 0.40):
        self.release_callback = release_callback
        self.max_click_duration = max_click_duration
        self._held_buttons: dict = {}  # button -> press_time

    def mark_down(self, button: str) -> None:
        self._held_buttons[button] = time.time()

    def mark_up(self, button: str) -> None:
        self._held_buttons.pop(button, None)

    def verify_watchdog(self) -> None:
        """Releases any button held longer than max_click_duration to prevent stuck buttons."""
        now = time.time()
        for btn, press_t in list(self._held_buttons.items()):
            if now - press_t > self.max_click_duration:
                logger.warning(f"[SAFETY WATCHDOG] Button '{btn}' held past {self.max_click_duration:.2f}s timeout! Enforcing guaranteed release.")
                try:
                    self.release_callback(btn)
                except Exception as e:
                    logger.error(f"Error during watchdog release: {e}")
                self._held_buttons.pop(btn, None)
