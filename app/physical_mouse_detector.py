"""N.E.X.U.S. Hardware Physical Mouse Activity Detector.
Monitors genuine physical mouse movement and clicks on Windows without interfering
with or suppressing user input.

Key principles:
1. Frame-to-frame displacement monitoring: Compares actual OS cursor position between frames.
   Does NOT compare against theoretical target coordinates.
2. Safe priority arbitration: When physical mouse movement (>15px delta between frames) or physical
   click is detected, priority is granted to the physical mouse for a 1.5s idle period.
3. Zero lockup guarantee: Every check updates the baseline cursor position so priority cleanly expires
   when the physical mouse stops moving.
4. Air mouse is NEVER fed norm_coords=None during physical priority; rather, virtual injection simply
   yields cursor positioning to the physical hardware while tracking continues smoothly in the background.
"""

import time
import math
import ctypes
import logging
from typing import Optional, Tuple

logger = logging.getLogger("NEXUS.PhysicalMouseDetector")

# Windows Virtual-Key Codes for Mouse Buttons
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class PhysicalMouseDetector:
    """Non-intrusive detector for genuine physical mouse hardware activity."""

    def __init__(self, physical_priority_timeout: float = 1.5, movement_threshold_px: float = 15.0):
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        self.physical_priority_timeout = physical_priority_timeout
        self.movement_threshold_px = movement_threshold_px

        self._last_physical_activity_time: float = 0.0
        self._is_physical_active: bool = False
        self._last_cursor_pos: Optional[Tuple[int, int]] = None
        self._last_virtual_move_time: float = 0.0

    def notify_virtual_move(self, x: int, y: int) -> None:
        """Called immediately after VirtualMouse successfully moves the Windows cursor."""
        self._last_cursor_pos = (x, y)
        self._last_virtual_move_time = time.time()

    def check_physical_activity(self, now: Optional[float] = None, is_virtual_clicking: bool = False) -> bool:
        """Polls current OS cursor position and physical buttons to detect genuine physical input.

        Returns True if physical mouse is currently in priority/active mode.
        """
        if not self._user32:
            return False

        t = now if now is not None else time.time()

        # 1. Read real current Windows cursor position
        pt = POINT()
        if not self._user32.GetCursorPos(ctypes.byref(pt)):
            return False

        curr_pos = (pt.x, pt.y)

        # Baseline initialization
        if self._last_cursor_pos is None:
            self._last_cursor_pos = curr_pos
            dist = 0.0
        else:
            # 2. Measure displacement since last observed frame/move
            dx = curr_pos[0] - self._last_cursor_pos[0]
            dy = curr_pos[1] - self._last_cursor_pos[1]
            dist = math.hypot(dx, dy)
            # CRITICAL: Always update _last_cursor_pos to curr_pos for the next frame
            # to ensure frame-to-frame delta evaluation and prevent sticky displacement loops!
            self._last_cursor_pos = curr_pos

        if dist >= self.movement_threshold_px:
            self._last_physical_activity_time = t
            self._is_physical_active = True
            logger.debug(f"[PHYSICAL MOUSE] Motion detected: {dist:.1f}px delta")
            return True

        # 3. Check physical button states (only if virtual mouse is NOT clicking)
        if not is_virtual_clicking:
            l_down = bool(self._user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            r_down = bool(self._user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            m_down = bool(self._user32.GetAsyncKeyState(VK_MBUTTON) & 0x8000)
            if l_down or r_down or m_down:
                self._last_physical_activity_time = t
                self._is_physical_active = True
                logger.debug("[PHYSICAL MOUSE] Button click detected")
                return True

        # 4. Check priority timeout expiration
        if self._is_physical_active:
            if t - self._last_physical_activity_time >= self.physical_priority_timeout:
                self._is_physical_active = False
                logger.info("[PHYSICAL MOUSE] Priority expired. Air mouse resumed.")

        return self._is_physical_active

    @property
    def is_physical_active(self) -> bool:
        return self._is_physical_active

    def is_physical_mouse_active(self) -> bool:
        return self._is_physical_active

    def get_real_cursor_pos(self) -> Tuple[int, int]:
        if self._user32:
            pt = POINT()
            if self._user32.GetCursorPos(ctypes.byref(pt)):
                return (pt.x, pt.y)
        return self._last_cursor_pos or (0, 0)

    def record_virtual_move(self, x: int, y: int) -> None:
        self.notify_virtual_move(x, y)

    def reset(self) -> None:
        self._last_physical_activity_time = 0.0
        self._is_physical_active = False
        self._last_cursor_pos = None
