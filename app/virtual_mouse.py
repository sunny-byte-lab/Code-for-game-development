"""N.E.X.U.S. Single Authoritative Virtual Mouse Controller.
Neural Experience & Unified System -- Precision Desktop Mouse Automation.

Features:
- Authoritative state machine: TRACKING, PINCH_CANDIDATE, CLICK_LOCKED, DRAGGING, TRACKING_LOST, EMERGENCY_STOP.
- Pre-lock cursor freeze on PINCH_CANDIDATE detection preventing click coordinate drift.
- Zero cursor moves sent while in candidate or click lock.
- Filter reinitialization and 120ms smooth release blending on pinch release.
- Separation of single-click from dragging.
- Plug-and-play MouseBackend protocol (WindowsMouseBackend, MockMouseBackend).
- High-precision 1€ Filter (One Euro Filter), Adaptive EMA, and custom ROI bounding box.
- Structured single-line diagnostic logging.
"""

import math
import time
import ctypes
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Tuple, Optional, Any, Union, List, Protocol, runtime_checkable

import pyautogui
from app.filter import PointFilter2D

logger = logging.getLogger("NEXUS.VirtualMouse")

# Eliminate default PyAutoGUI latency and disable internal corner throw
pyautogui.PAUSE = 0.001
pyautogui.FAILSAFE = False


class MouseState(str, Enum):
    TRACKING = "TRACKING"
    IDLE = "TRACKING"                   # Canonical alias for idle tracking
    PINCH_CANDIDATE = "PINCH_CANDIDATE"
    CLICK_CANDIDATE = "PINCH_CANDIDATE" # Canonical alias for click candidate
    CLICK_LOCKED = "CLICK_LOCKED"
    CLICKED = "CLICK_LOCKED"            # Canonical alias for single click executed
    COOLDOWN = "COOLDOWN"               # Post-click debounce cooldown
    CLICK_COOLDOWN = "COOLDOWN"         # Canonical alias
    DRAGGING = "DRAGGING"
    SCROLLING = "SCROLLING"
    TRACKING_LOST = "TRACKING_LOST"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass
class MouseEventRecord:
    event_type: str  # "MOVE", "DOWN", "UP", "CLICK", "SCROLL"
    x: int
    y: int
    button: str = "left"
    delta: int = 0
    timestamp: float = field(default_factory=time.time)


from ctypes import wintypes

# WIN32 SendInput STRUCTURE DEFINITIONS (64-BIT & 32-BIT COMPATIBLE)
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_union", _INPUT_UNION),
    ]


@runtime_checkable
class MouseBackend(Protocol):
    def set_cursor_pos(self, x: int, y: int) -> bool: ...
    def mouse_down(self, button: str = "left") -> bool: ...
    def mouse_up(self, button: str = "left") -> bool: ...
    def click(self, button: str = "left") -> bool: ...
    def scroll(self, delta: int) -> bool: ...


# Synthetic N.E.X.U.S. Win32 Input Signature ('NEXU' in hex) to distinguish injected events
NEXUS_INPUT_SIGNATURE = 0x4E455855


class WindowsMouseBackend:
    """Production Windows OS mouse backend using SendInput API with Win32 mouse_event and PyAutoGUI fallback."""

    def __init__(self):
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        self.last_error: str = ""
        self.api_name: str = "SendInput (Win32)"

    def _send_input(self, dwFlags: int, data: int = 0, dx: int = 0, dy: int = 0) -> bool:
        """Sends a hardware mouse event via the Windows SendInput API with signature tagging."""
        if not self._user32:
            return False
        try:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.mi.dx = dx
            inp.mi.dy = dy
            inp.mi.mouseData = data & 0xFFFFFFFF
            inp.mi.dwFlags = dwFlags
            inp.mi.time = 0
            inp.mi.dwExtraInfo = NEXUS_INPUT_SIGNATURE
            res = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            if res == 1:
                self.api_name = "SendInput (Win32)"
                return True
            err = ctypes.GetLastError()
            self.last_error = f"SendInput failed with Win32 error code {err}"
            logger.debug(f"[SendInput] Error code: {err}")
        except Exception as e:
            self.last_error = f"SendInput exception: {e}"
            logger.debug(f"[SendInput] Exception: {e}")
        return False

    def set_cursor_pos(self, x: int, y: int) -> bool:
        """Directly positions the real Windows OS cursor at desktop screen coordinates."""
        if self._user32:
            try:
                if self._user32.SetCursorPos(x, y):
                    return True
            except Exception as e:
                self.last_error = f"SetCursorPos exception: {e}"
        try:
            pyautogui.moveTo(x, y, _pause=False)
            return True
        except Exception as e:
            self.last_error = f"pyautogui.moveTo exception: {e}"
            return False

    def mouse_down(self, button: str = "left") -> bool:
        """Sends system-level mouse down event to the active target window."""
        flag = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        # 1. Primary: Windows SendInput
        if self._send_input(flag):
            return True
        # 2. Secondary fallback: mouse_event
        if self._user32:
            try:
                self._user32.mouse_event(flag, 0, 0, 0, 0)
                self.api_name = "mouse_event (Win32)"
                return True
            except Exception:
                pass
        # 3. Tertiary fallback: PyAutoGUI
        try:
            pyautogui.mouseDown(button=button, _pause=False)
            self.api_name = "pyautogui"
            return True
        except Exception as e:
            self.last_error = f"mouseDown error: {e}"
            return False

    def mouse_up(self, button: str = "left") -> bool:
        """Sends system-level mouse up event to the active target window."""
        flag = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        # 1. Primary: Windows SendInput
        if self._send_input(flag):
            return True
        # 2. Secondary fallback: mouse_event
        if self._user32:
            try:
                self._user32.mouse_event(flag, 0, 0, 0, 0)
                self.api_name = "mouse_event (Win32)"
                return True
            except Exception:
                pass
        # 3. Tertiary fallback: PyAutoGUI
        try:
            pyautogui.mouseUp(button=button, _pause=False)
            self.api_name = "pyautogui"
            return True
        except Exception as e:
            self.last_error = f"mouseUp error: {e}"
            return False

    def click(self, button: str = "left") -> bool:
        """Sends atomic down/up click sequence via SendInput with hardware pause."""
        down_flag = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP

        # 1. Primary: Windows SendInput
        ok_down = self._send_input(down_flag)
        time.sleep(0.012)
        ok_up = self._send_input(up_flag)
        if ok_down and ok_up:
            return True

        # 2. Secondary fallback: mouse_event
        if self._user32:
            try:
                self._user32.mouse_event(down_flag, 0, 0, 0, 0)
                time.sleep(0.012)
                self._user32.mouse_event(up_flag, 0, 0, 0, 0)
                self.api_name = "mouse_event (Win32)"
                return True
            except Exception:
                pass
        # 3. Tertiary fallback: PyAutoGUI
        try:
            if button == "left":
                pyautogui.click(_pause=False)
            else:
                pyautogui.rightClick(_pause=False)
            self.api_name = "pyautogui"
            return True
        except Exception as e:
            self.last_error = f"click error: {e}"
            return False

    def scroll(self, delta: int) -> bool:
        """Dispatches actual Windows mouse-wheel scrolling (WHEEL_DELTA=120) to the application under cursor."""
        # 1. Primary: Windows SendInput with MOUSEEVENTF_WHEEL
        if self._send_input(MOUSEEVENTF_WHEEL, data=delta):
            return True
        # 2. Secondary fallback: mouse_event
        if self._user32:
            try:
                dword_delta = delta & 0xFFFFFFFF
                self._user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, dword_delta, 0)
                self.api_name = "mouse_event (Win32)"
                return True
            except Exception:
                pass
        # 3. Tertiary fallback: PyAutoGUI
        try:
            clicks = delta // 120 if abs(delta) >= 120 else (1 if delta > 0 else -1)
            pyautogui.scroll(clicks, _pause=False)
            self.api_name = "pyautogui"
            return True
        except Exception as e:
            self.last_error = f"scroll error: {e}"
            return False


class MockMouseBackend:
    """In-memory mock backend for deterministic automated testing without a physical mouse or camera."""

    def __init__(self, screen_w: int = 1920, screen_h: int = 1080):
        self.cursor_x: int = screen_w // 2
        self.cursor_y: int = screen_h // 2
        self.is_left_down: bool = False
        self.is_right_down: bool = False
        self.events: List[MouseEventRecord] = []
        self.api_name: str = "Mock"

    def set_cursor_pos(self, x: int, y: int) -> bool:
        self.cursor_x = x
        self.cursor_y = y
        self.events.append(MouseEventRecord("MOVE", x, y, timestamp=time.time()))
        return True

    def mouse_down(self, button: str = "left") -> bool:
        if button == "left":
            self.is_left_down = True
        elif button == "right":
            self.is_right_down = True
        self.events.append(MouseEventRecord("DOWN", self.cursor_x, self.cursor_y, button=button, timestamp=time.time()))
        return True

    def mouse_up(self, button: str = "left") -> bool:
        if button == "left":
            self.is_left_down = False
        elif button == "right":
            self.is_right_down = False
        self.events.append(MouseEventRecord("UP", self.cursor_x, self.cursor_y, button=button, timestamp=time.time()))
        return True

    def click(self, button: str = "left") -> bool:
        self.events.append(MouseEventRecord("CLICK", self.cursor_x, self.cursor_y, button=button, timestamp=time.time()))
        return True

    def scroll(self, delta: int) -> bool:
        self.events.append(MouseEventRecord("SCROLL", self.cursor_x, self.cursor_y, delta=delta, timestamp=time.time()))
        return True

    def clear(self) -> None:
        self.events.clear()

    @property
    def move_events(self) -> List[MouseEventRecord]:
        return [e for e in self.events if e.event_type == "MOVE"]

    @property
    def click_events(self) -> List[MouseEventRecord]:
        return [e for e in self.events if e.event_type == "CLICK"]

    @property
    def down_events(self) -> List[MouseEventRecord]:
        return [e for e in self.events if e.event_type == "DOWN"]

    @property
    def up_events(self) -> List[MouseEventRecord]:
        return [e for e in self.events if e.event_type == "UP"]


class VirtualMouse:
    """Controls the OS cursor using mathematically stabilized camera landmarks."""

    def __init__(self,
                 backend: Optional[MouseBackend] = None,
                 sensitivity: float = 1.0,
                 sensitivity_x: Optional[float] = None,
                 sensitivity_y: Optional[float] = None,
                 fine_control_mode: bool = False,
                 fine_control_scale: float = 0.40,
                 smoothing: float = 0.65,
                 smoothing_type: str = "one_euro",
                 one_euro_min_cutoff: float = 1.0,
                 one_euro_beta: float = 0.02,
                 deadzone_radius: float = 8.0,
                 active_margin_x: float = 0.16,
                 active_margin_y: float = 0.16,
                 roi_bounds: Optional[Tuple[float, float, float, float]] = None,
                 scroll_speed: float = 35.0,
                 invert_x: bool = False,
                 cursor_mode: str = "absolute",
                 relative_speed: float = 4.0,
                 relative_deadzone: float = 0.03,
                 click_stabilization: bool = True,
                 click_stabilization_ms: int = 160,
                 pinch_threshold: float = 0.28,
                 candidate_delta: float = 0.08,
                 pinch_release_threshold: float = 0.40,
                 drag_hold_duration: float = 0.40,
                 click_cooldown: float = 0.20,
                 tracking_loss_grace_s: float = 0.30):

        # Backend selection
        self.backend: MouseBackend = backend or WindowsMouseBackend()

        # Sensitivities & Precision Dampening
        self.sensitivity_x = sensitivity_x if sensitivity_x is not None else sensitivity
        self.sensitivity_y = sensitivity_y if sensitivity_y is not None else sensitivity
        self.sensitivity = sensitivity
        self.fine_control_mode: bool = fine_control_mode
        self.fine_control_scale: float = fine_control_scale
        self.click_cooldown: float = click_cooldown
        self.cooldown_until: float = 0.0

        # Smoothing and Filtering
        self.smoothing = smoothing
        self.smoothing_type = smoothing_type
        self.one_euro_min_cutoff = one_euro_min_cutoff
        self.one_euro_beta = one_euro_beta
        self.deadzone_radius = deadzone_radius

        self.point_filter = PointFilter2D(
            filter_type=smoothing_type,
            min_cutoff=one_euro_min_cutoff,
            beta=one_euro_beta,
            smoothing=smoothing
        )

        # Tracking Loss Grace Period
        self.tracking_loss_grace_s: float = tracking_loss_grace_s
        self.last_valid_tracking_time: Optional[float] = None
        self.in_tracking_loss_grace: bool = False

        # Region of Interest (ROI) mapping
        if roi_bounds is not None:
            self.roi_left, self.roi_top, self.roi_right, self.roi_bottom = roi_bounds
        else:
            self.roi_left = active_margin_x
            self.roi_top = active_margin_y
            self.roi_right = 1.0 - active_margin_x
            self.roi_bottom = 1.0 - active_margin_y

        self.active_margin_x = active_margin_x
        self.active_margin_y = active_margin_y
        self.scroll_speed = scroll_speed
        self.invert_x = invert_x

        # Control Mode: "absolute" or "relative"
        self.cursor_mode = cursor_mode
        self.relative_speed = relative_speed
        self.relative_deadzone = relative_deadzone
        self.relative_anchor: Optional[Tuple[float, float]] = None
        self.last_relative_time: Optional[float] = None

        # Authoritative State Machine & Thresholds
        self.state: MouseState = MouseState.TRACKING
        self.pinch_threshold = pinch_threshold
        self.candidate_delta = candidate_delta
        self.candidate_threshold = pinch_threshold + candidate_delta
        self.pinch_release_threshold = max(pinch_release_threshold, pinch_threshold + 0.05)
        self.drag_hold_duration = drag_hold_duration

        # Candidate Pre-Lock and Click Stabilization Mechanics
        self.click_stabilization = click_stabilization
        self.click_stabilization_ms = click_stabilization_ms
        self.stabilization_until: float = 0.0
        self.frozen_position: Optional[Tuple[float, float]] = None

        self.locked_position: Optional[Tuple[int, int]] = None
        self.candidate_start_time: Optional[float] = None
        self.candidate_timeout_s: float = 0.35
        self.pinch_confirmed_time: Optional[float] = None

        # Release blending parameters (120ms ramp from locked position to live tracking)
        self.release_blend_start: Optional[float] = None
        self.release_blend_from: Optional[Tuple[float, float]] = None
        self.release_blend_duration: float = 0.120

        # Query screen dimensions
        self.screen_w, self.screen_h = 1920, 1080
        self.update_screen_size()

        # Internal smoothed cursor positions
        self.curr_x: float = self.screen_w / 2.0
        self.curr_y: float = self.screen_h / 2.0
        self.is_dragging: bool = False

        # Hardware safety guards
        self.conflict_resolver = None
        self.button_guard = None

        # Live telemetry and diagnostics
        self.last_action_message: str = "INITIALIZED"
        self.last_action_success: bool = True
        self.last_error: str = ""

    def update_screen_size(self) -> None:
        """Refreshes primary display size from Windows OS with DPI scaling awareness."""
        try:
            user32 = ctypes.windll.user32
            try:
                from PySide6.QtWidgets import QApplication
                if QApplication.instance() is None:
                    user32.SetProcessDPIAware()
            except Exception:
                pass
            w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            if w > 0 and h > 0:
                self.screen_w = w
                self.screen_h = h
                return
        except Exception:
            pass

        try:
            w, h = pyautogui.size()
            if w > 0 and h > 0:
                self.screen_w = w
                self.screen_h = h
        except Exception as e:
            logger.debug(f"Screen size query fallback: {e}. Using ({self.screen_w}, {self.screen_h}).")

    def set_roi_bounds(self, left: float, top: float, right: float, bottom: float) -> None:
        """Configures the active normalized hand movement bounding box."""
        self.roi_left = max(0.0, min(0.45, left))
        self.roi_top = max(0.0, min(0.45, top))
        self.roi_right = max(self.roi_left + 0.1, min(1.0, right))
        self.roi_bottom = max(self.roi_top + 0.1, min(1.0, bottom))
        self.active_margin_x = self.roi_left
        self.active_margin_y = self.roi_top

    def get_roi_bounds(self) -> Tuple[float, float, float, float]:
        return self.roi_left, self.roi_top, self.roi_right, self.roi_bottom

    @property
    def is_stabilized(self) -> bool:
        """Returns True if cursor is currently stabilized or locked to prevent drift."""
        return (
            self.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED)
            or time.time() < self.stabilization_until
            or self.locked_position is not None
        )

    @property
    def click_state_name(self) -> str:
        """Human-readable state string for telemetry and HUD overlays."""
        if self.state == MouseState.TRACKING:
            if time.time() < self.cooldown_until:
                return "COOLDOWN"
            return "IDLE"
        elif self.state == MouseState.PINCH_CANDIDATE:
            return "CANDIDATE (LOCKED)"
        elif self.state == MouseState.CLICK_LOCKED:
            return "CLICK CONFIRMED"
        elif self.state == MouseState.DRAGGING:
            return "DRAGGING"
        elif self.state == MouseState.SCROLLING:
            return "SCROLLING"
        return self.state.value

    @property
    def input_api(self) -> str:
        """Returns the active Windows input API name (e.g. 'SendInput (Win32)')."""
        return getattr(self.backend, "api_name", "SendInput (Win32)")

    def release_all_buttons(self) -> None:
        """Ensures all physical/virtual mouse buttons are safely released on Windows."""
        try:
            self.backend.mouse_up("left")
            self.backend.mouse_up("right")
        except Exception:
            pass
        self.is_dragging = False

    @property
    def effective_sensitivity(self) -> float:
        """Calculates live sensitivity taking Fine Control Mode into account."""
        scale = self.fine_control_scale if self.fine_control_mode else 1.0
        return self.sensitivity * scale

    def set_fine_control(self, enabled: bool) -> None:
        """Enables or disables Fine Control precision mode."""
        self.fine_control_mode = enabled
        logger.info(f"FINE_CONTROL_MODE({'ENABLED' if enabled else 'DISABLED'})")

    def toggle_fine_control(self) -> bool:
        """Toggles Fine Control Mode on/off, returning new active state."""
        self.fine_control_mode = not self.fine_control_mode
        logger.info(f"FINE_CONTROL_MODE_TOGGLED({'ENABLED' if self.fine_control_mode else 'DISABLED'})")
        return self.fine_control_mode

    def set_sensitivity_preset(self, preset: str) -> None:
        """Applies sensitivity presets: 'low' (0.8), 'medium' (1.2), 'high' (1.8)."""
        presets = {"low": 0.8, "medium": 1.2, "high": 1.8}
        val = presets.get(preset.lower(), 1.2)
        self.sensitivity = val
        self.sensitivity_x = val
        self.sensitivity_y = val
        logger.info(f"SENSITIVITY_PRESET_APPLIED({preset.upper()} -> {val}x)")

    def set_deadzone(self, radius: float) -> None:
        """Updates cursor dead zone radius in screen pixels."""
        self.deadzone_radius = max(0.0, float(radius))

    def set_smoothing_parameters(self, min_cutoff: float, beta: float) -> None:
        """Updates One Euro filter parameters dynamically."""
        self.one_euro_min_cutoff = float(min_cutoff)
        self.one_euro_beta = float(beta)
        if hasattr(self.point_filter, "filter_obj") and hasattr(self.point_filter.filter_obj, "min_cutoff"):
            self.point_filter.filter_obj.min_cutoff = float(min_cutoff)
            self.point_filter.filter_obj.beta = float(beta)

    def recalibrate_position(self, norm_x: Optional[float] = None, norm_y: Optional[float] = None) -> None:
        """Recalibrates hand resting position and recenters cursor to screen center."""
        # 1. If hand coordinate is provided, center ROI bounding box around hand resting location
        if norm_x is not None and norm_y is not None:
            span_x = (self.roi_right - self.roi_left) / 2.0
            span_y = (self.roi_bottom - self.roi_top) / 2.0
            new_left = max(0.0, norm_x - span_x)
            new_top = max(0.0, norm_y - span_y)
            new_right = min(1.0, norm_x + span_x)
            new_bottom = min(1.0, norm_y + span_y)
            if new_right - new_left > 0.1 and new_bottom - new_top > 0.1:
                self.roi_left, self.roi_top = new_left, new_top
                self.roi_right, self.roi_bottom = new_right, new_bottom

        # 2. Re-center cursor to screen center
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        self.curr_x = float(cx)
        self.curr_y = float(cy)
        self.point_filter.reinitialize(self.curr_x, self.curr_y, time.time())
        self._dispatch_raw_move(cx, cy)
        logger.info(f"HAND_POSITION_RECALIBRATED(centered_at=({cx}, {cy}), roi=({self.roi_left:.2f}, {self.roi_top:.2f}, {self.roi_right:.2f}, {self.roi_bottom:.2f}))")

    def map_to_screen(self, norm_x: float, norm_y: float) -> Tuple[float, float]:
        """Maps normalized camera coordinates [0..1] to physical screen pixels with custom ROI & sensitivity."""
        input_x = (1.0 - norm_x) if self.invert_x else norm_x
        input_y = norm_y

        clamped_x = max(self.roi_left, min(self.roi_right, input_x))
        clamped_y = max(self.roi_top, min(self.roi_bottom, input_y))

        active_w = max(0.05, self.roi_right - self.roi_left)
        active_h = max(0.05, self.roi_bottom - self.roi_top)

        norm_box_x = (clamped_x - self.roi_left) / active_w
        norm_box_y = (clamped_y - self.roi_top) / active_h

        # Apply Fine Control scaling if active (~40% velocity for surgical accuracy)
        scale = self.fine_control_scale if self.fine_control_mode else 1.0
        eff_sens_x = self.sensitivity_x * scale
        eff_sens_y = self.sensitivity_y * scale

        centered_x = (norm_box_x - 0.5) * eff_sens_x + 0.5
        centered_y = (norm_box_y - 0.5) * eff_sens_y + 0.5

        final_norm_x = max(0.0, min(1.0, centered_x))
        final_norm_y = max(0.0, min(1.0, centered_y))

        target_px_x = final_norm_x * (self.screen_w - 1)
        target_px_y = final_norm_y * (self.screen_h - 1)

        return target_px_x, target_px_y

    def trigger_click_stabilization(self, duration_ms: Optional[int] = None) -> None:
        """Locks cursor movement briefly to prevent hand wobble during pinch click."""
        if not self.click_stabilization:
            return
        ms = duration_ms if duration_ms is not None else self.click_stabilization_ms
        self.stabilization_until = time.time() + (ms / 1000.0)
        self.frozen_position = (self.curr_x, self.curr_y)

    def _clamp_screen_coords(self, x: float, y: float) -> Tuple[int, int]:
        """Clamps coordinate safely inside screen boundaries (prevents failsafe & 1px window border snapping)."""
        cx = max(3, min(self.screen_w - 4, int(round(x))))
        cy = max(3, min(self.screen_h - 4, int(round(y))))
        return cx, cy

    def _dispatch_raw_move(self, px_x: int, px_y: int) -> bool:
        """Dispatches hardware cursor move via authoritative backend with conflict check."""
        if self.conflict_resolver and hasattr(self.conflict_resolver, "is_physical_mouse_active"):
            if self.conflict_resolver.is_physical_mouse_active():
                real_x, real_y = self.conflict_resolver.get_real_cursor_pos()
                self.curr_x = float(real_x)
                self.curr_y = float(real_y)
                return False

        if self.backend.set_cursor_pos(px_x, px_y):
            if self.conflict_resolver and hasattr(self.conflict_resolver, "record_virtual_move"):
                self.conflict_resolver.record_virtual_move(px_x, px_y)
            self.last_action_message = f"Moved to ({px_x}, {px_y})"
            self.last_action_success = True
            logger.info(f"CURSOR_MOVE_SENT({px_x}, {px_y})")
            return True
        else:
            err = f"Cursor move error: unable to move to ({px_x}, {px_y})"
            self.last_error = err
            self.last_action_message = err
            self.last_action_success = False
            logger.debug(err)
            return False

    def _start_release_blend(self, start_pos: Tuple[int, int], timestamp: float) -> None:
        """Seeds 120ms release blending from locked position into live tracking."""
        self.release_blend_start = timestamp
        self.release_blend_from = (float(start_pos[0]), float(start_pos[1]))

    def _unlock_cursor(self, timestamp: float) -> None:
        """Unlocks cursor, reinitializes filter at locked coordinates, and blends into tracking."""
        reinit_px = self.locked_position or self._clamp_screen_coords(self.curr_x, self.curr_y)
        self.point_filter.reinitialize(float(reinit_px[0]), float(reinit_px[1]), timestamp)
        self.curr_x, self.curr_y = float(reinit_px[0]), float(reinit_px[1])
        self._start_release_blend(reinit_px, timestamp)
        self.locked_position = None
        self.candidate_start_time = None
        self.pinch_confirmed_time = None
        self.state = MouseState.TRACKING
        logger.info(f"CURSOR_UNLOCKED(reinit_at={reinit_px})")

    def move_cursor(self, norm_x: float, norm_y: float, timestamp: Optional[float] = None) -> Tuple[int, int]:
        """Dispatches cursor position according to active mode, filter, and stabilization."""
        now = timestamp if timestamp is not None else time.time()

        # If cursor is locked in candidate or click lock state, freeze movement strictly
        if self.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED) and self.locked_position:
            return self.locked_position

        # Check anti-slip click freeze if stabilization is manually active
        if self.click_stabilization and now < self.stabilization_until and self.frozen_position:
            px_x, px_y = self._clamp_screen_coords(self.frozen_position[0], self.frozen_position[1])
            self._dispatch_raw_move(px_x, px_y)
            return px_x, px_y

        if self.cursor_mode == "relative":
            return self._move_relative(norm_x, norm_y, now)
        else:
            return self._move_absolute(norm_x, norm_y, now)

    def _move_absolute(self, norm_x: float, norm_y: float, timestamp: float) -> Tuple[int, int]:
        """Absolute mapping with 1€ / Adaptive smoothing, release ramp, and smooth deadzone."""
        target_x, target_y = self.map_to_screen(norm_x, norm_y)

        # Apply high-precision point filter
        filtered_x, filtered_y = self.point_filter.filter(target_x, target_y, timestamp)

        # Apply smooth 120ms release blending if transitioning from a locked pinch
        if self.release_blend_start is not None and self.release_blend_from is not None:
            elapsed = timestamp - self.release_blend_start
            if elapsed < self.release_blend_duration:
                t = max(0.0, min(1.0, elapsed / self.release_blend_duration))
                ease = t * t * (3.0 - 2.0 * t)  # Smooth cubic ease
                filtered_x = self.release_blend_from[0] * (1.0 - ease) + filtered_x * ease
                filtered_y = self.release_blend_from[1] * (1.0 - ease) + filtered_y * ease
            else:
                self.release_blend_start = None
                self.release_blend_from = None

        # Deadzone check to eliminate residual micro-tremors with smooth soft knee
        dist = math.hypot(filtered_x - self.curr_x, filtered_y - self.curr_y)
        if dist < self.deadzone_radius:
            px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
            return px_x, px_y
        elif dist < self.deadzone_radius * 2.5:
            # Soft transition zone: ramp smoothly into full velocity
            blend = (dist - self.deadzone_radius) / (self.deadzone_radius * 1.5)
            self.curr_x = self.curr_x * (1.0 - blend) + filtered_x * blend
            self.curr_y = self.curr_y * (1.0 - blend) + filtered_y * blend
        else:
            self.curr_x = filtered_x
            self.curr_y = filtered_y

        px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
        self._dispatch_raw_move(px_x, px_y)
        return px_x, px_y

    def _move_relative(self, norm_x: float, norm_y: float, timestamp: float) -> Tuple[int, int]:
        """Relative control mode: displacement from neutral anchor drives cursor velocity."""
        input_x = (1.0 - norm_x) if self.invert_x else norm_x
        input_y = norm_y

        if self.relative_anchor is None or self.last_relative_time is None:
            self.relative_anchor = (input_x, input_y)
            self.last_relative_time = timestamp
            px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
            return px_x, px_y

        dt = max(1e-4, timestamp - self.last_relative_time)
        self.last_relative_time = timestamp

        anc_x, anc_y = self.relative_anchor
        delta_x = input_x - anc_x
        delta_y = input_y - anc_y
        dist = math.hypot(delta_x, delta_y)

        if dist < self.relative_deadzone:
            px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
            return px_x, px_y

        # Velocity proportional to displacement from anchor, dampened by Fine Control if active
        scale = self.fine_control_scale if self.fine_control_mode else 1.0
        vx = delta_x * self.relative_speed * self.sensitivity_x * scale * 1200.0 * dt
        vy = delta_y * self.relative_speed * self.sensitivity_y * scale * 1200.0 * dt

        self.curr_x += vx
        self.curr_y += vy

        px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
        self._dispatch_raw_move(px_x, px_y)
        return px_x, px_y

    def reset_filter(self) -> None:
        """Resets filter and relative anchor on tracking loss so cursor does not jump."""
        self.point_filter.reset()
        self.relative_anchor = None
        self.last_relative_time = None
        self.frozen_position = None
        self.stabilization_until = 0.0
        self.locked_position = None
        self.candidate_start_time = None
        self.pinch_confirmed_time = None
        self.release_blend_start = None
        self.release_blend_from = None

    def left_click(self) -> Tuple[bool, str]:
        """Triggers a single left mouse click with stabilization."""
        px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
        self.trigger_click_stabilization()
        self.backend.set_cursor_pos(px_x, px_y)
        ok = self.backend.click("left")
        msg = f"Left Click at ({px_x}, {px_y})"
        self.last_action_message = msg
        self.last_action_success = ok
        logger.info(f"CLICK_SENT(button='left', x={px_x}, y={px_y})")
        return ok, msg

    def right_click(self) -> Tuple[bool, str]:
        """Triggers a single right mouse click with stabilization."""
        px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
        self.trigger_click_stabilization()
        self.backend.set_cursor_pos(px_x, px_y)
        ok = self.backend.click("right")
        msg = f"Right Click at ({px_x}, {px_y})"
        self.last_action_message = msg
        self.last_action_success = ok
        logger.info(f"CLICK_SENT(button='right', x={px_x}, y={px_y})")
        return ok, msg

    def start_drag(self) -> Tuple[bool, str]:
        """Depresses left mouse button for drag-and-drop operations."""
        if not self.is_dragging:
            px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
            self.backend.set_cursor_pos(px_x, px_y)
            ok = self.backend.mouse_down("left")
            self.is_dragging = True
            msg = f"Drag STARTED at ({px_x}, {px_y})"
            self.last_action_message = msg
            self.last_action_success = ok
            logger.info(f"[VIRTUAL MOUSE] {msg}")
            return ok, msg
        return True, "Drag already active"

    def release_drag(self) -> Tuple[bool, str]:
        """Releases all mouse buttons if currently dragging."""
        if self.is_dragging:
            px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
            self.release_all_buttons()
            msg = f"Drag RELEASED at ({px_x}, {px_y})"
            self.last_action_message = msg
            self.last_action_success = True
            logger.info(f"[VIRTUAL MOUSE] {msg}")
            return True, msg
        self.release_all_buttons()
        return True, "No active drag"

    def scroll(self, dy: float) -> Tuple[bool, str]:
        """Scrolls vertically with smooth inertia scaling."""
        if abs(dy) < 0.005:
            return True, "Scroll deadzone"

        # Standard Windows WHEEL_DELTA is 120
        direction = -1 if dy > 0 else 1
        notches = max(1, int(abs(dy) * (self.scroll_speed / 10.0)))
        wheel_delta = direction * notches * 120

        ok = self.backend.scroll(wheel_delta)
        msg = f"Scrolled {'UP' if wheel_delta > 0 else 'DOWN'} ({wheel_delta})"
        self.last_action_message = msg
        self.last_action_success = ok
        return ok, msg

    def process_frame(self,
                      norm_coords: Optional[Tuple[float, float]],
                      pinch_dist: Optional[float] = None,
                      right_click_triggered: bool = False,
                      scroll_dy: float = 0.0,
                      is_drag_mode: bool = False,
                      emergency: bool = False,
                      timestamp: Optional[float] = None,
                      is_scroll_active: bool = False) -> Tuple[MouseState, Optional[Tuple[int, int]], str]:
        """Single authoritative entry point for every camera frame.

        Enforces:
        1. Immediate freeze on PINCH_CANDIDATE detection.
        2. Strict zero cursor moves during candidate and click locked states.
        3. Single click dispatch strictly at the locked position.
        4. Smooth filter reinitialization and 120ms release blending.
        5. Dragging separated from click operations.
        6. Immediate drag release on tracking loss or emergency stop.
        """
        now = timestamp if timestamp is not None else time.time()

        # 1. EMERGENCY STOP
        if emergency:
            if self.is_dragging:
                self.release_drag()
            self.state = MouseState.EMERGENCY_STOP
            self.locked_position = None
            self.candidate_start_time = None
            return self.state, None, "EMERGENCY STOP"

        # Recover from emergency stop
        if self.state == MouseState.EMERGENCY_STOP:
            self.state = MouseState.TRACKING

        # 2. TRACKING LOSS WITH CONFIGURABLE GRACE PERIOD
        if norm_coords is None:
            # Check if within temporary loss grace period (e.g. 250-350ms)
            if self.last_valid_tracking_time is not None and (now - self.last_valid_tracking_time < self.tracking_loss_grace_s):
                self.in_tracking_loss_grace = True
                # Freeze cursor strictly at last valid clamped coordinates without resetting filters
                px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
                return self.state, (px_x, px_y), "TRACKING LOSS GRACE"

            # Grace period expired or never started
            self.in_tracking_loss_grace = False
            if self.state != MouseState.TRACKING_LOST:
                if self.is_dragging:
                    self.release_drag()
                self.state = MouseState.TRACKING_LOST
                self.point_filter.reset()
                self.locked_position = None
                self.candidate_start_time = None
                self.pinch_confirmed_time = None
                self.relative_anchor = None
                logger.info("TRACKING_LOST()")
            return self.state, None, "TRACKING LOST"

        # Valid coordinates received: update tracking timestamp
        self.last_valid_tracking_time = now
        self.in_tracking_loss_grace = False
        norm_x, norm_y = norm_coords

        # Recover from tracking loss smoothly
        if self.state == MouseState.TRACKING_LOST:
            self.state = MouseState.TRACKING
            target_x, target_y = self.map_to_screen(norm_x, norm_y)
            self.point_filter.reinitialize(target_x, target_y, now)
            self.curr_x, self.curr_y = target_x, target_y
            logger.info("TRACKING_REGAINED()")

        # 3. SCROLLING (takes priority over normal click tracking)
        if is_scroll_active:
            if self.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED):
                self._unlock_cursor(now)
            self.state = MouseState.SCROLLING
            # Cursor position is strictly locked to prevent cursor drift across windows during scroll
            return self.state, self._clamp_screen_coords(self.curr_x, self.curr_y), "SCROLLING ACTIVE"

        # Recover from scrolling
        if self.state == MouseState.SCROLLING:
            self.state = MouseState.TRACKING
            target_x, target_y = self.map_to_screen(norm_x, norm_y)
            self.point_filter.reinitialize(target_x, target_y, now)
            self.curr_x, self.curr_y = target_x, target_y

        if abs(scroll_dy) > 0.005:
            if self.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED):
                self._unlock_cursor(now)
            ok, msg = self.scroll(scroll_dy)
            return self.state, self._clamp_screen_coords(self.curr_x, self.curr_y), msg

        # 4. RIGHT CLICK
        if right_click_triggered:
            if self.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED):
                self._unlock_cursor(now)
            ok, msg = self.right_click()
            return self.state, self._clamp_screen_coords(self.curr_x, self.curr_y), msg

        # 5. CANDIDATE & CLICK STATE MACHINE
        candidate_th = self.candidate_threshold

        # --- A. STATE: PINCH_CANDIDATE ---
        if self.state == MouseState.PINCH_CANDIDATE:
            # Cursor movement is frozen strictly at locked_position
            # Check confirmation
            if pinch_dist is not None and pinch_dist <= self.pinch_threshold:
                # Confirmed!
                self.state = MouseState.CLICK_LOCKED
                self.pinch_confirmed_time = now
                logger.info(f"PINCH_CONFIRMED(dist={pinch_dist:.4f})")
                assert self.locked_position is not None
                self.backend.set_cursor_pos(self.locked_position[0], self.locked_position[1])
                self.backend.click("left")
                logger.info(f"CLICK_SENT(button='left', x={self.locked_position[0]}, y={self.locked_position[1]})")
                msg = f"Left Click at ({self.locked_position[0]}, {self.locked_position[1]})"
                self.last_action_message = msg
                return self.state, self.locked_position, msg

            # Check abort / timeout
            elapsed_candidate = now - (self.candidate_start_time or now)
            aborted = False
            if pinch_dist is not None and pinch_dist >= candidate_th + 0.04:
                aborted = True
            elif elapsed_candidate > self.candidate_timeout_s:
                aborted = True

            if aborted:
                self.cooldown_until = now + (self.click_cooldown * 0.5)
                self._unlock_cursor(now)
                return self.state, self._clamp_screen_coords(self.curr_x, self.curr_y), "CANDIDATE ABORTED"

            # Still candidate: send zero moves, maintain locked position
            return self.state, self.locked_position, "PINCH CANDIDATE PENDING"

        # --- B. STATE: CLICK_LOCKED ---
        elif self.state == MouseState.CLICK_LOCKED:
            # Check if drag should start
            if is_drag_mode and self.pinch_confirmed_time and (now - self.pinch_confirmed_time >= self.drag_hold_duration):
                self.state = MouseState.DRAGGING
                self.backend.mouse_down("left")
                self.is_dragging = True
                assert self.locked_position is not None
                logger.info(f"DRAG_STARTED({self.locked_position[0]}, {self.locked_position[1]})")
                return self.state, self.locked_position, "DRAG STARTED"

            # Check release
            if pinch_dist is not None and pinch_dist >= self.pinch_release_threshold:
                logger.info(f"PINCH_RELEASED(dist={pinch_dist:.4f})")
                self.cooldown_until = now + self.click_cooldown
                self._unlock_cursor(now)
                return self.state, self._clamp_screen_coords(self.curr_x, self.curr_y), "PINCH RELEASED"

            # While held: send ZERO moves, maintain locked position
            return self.state, self.locked_position, "CLICK LOCKED HELD"

        # --- C. STATE: DRAGGING ---
        elif self.state == MouseState.DRAGGING:
            # Check release
            if pinch_dist is not None and pinch_dist >= self.pinch_release_threshold:
                px_x, px_y = self._clamp_screen_coords(self.curr_x, self.curr_y)
                self.backend.mouse_up("left")
                self.is_dragging = False
                self.cooldown_until = now + self.click_cooldown
                logger.info(f"DRAG_RELEASED({px_x}, {px_y})")
                logger.info(f"PINCH_RELEASED(dist={pinch_dist:.4f})")
                self.state = MouseState.TRACKING
                self.locked_position = None
                return self.state, (px_x, px_y), "DRAG RELEASED"

            # In drag mode, cursor tracks hand
            px_x, px_y = self.move_cursor(norm_x, norm_y, timestamp=now)
            return self.state, (px_x, px_y), "DRAGGING"

        # --- D. STATE: TRACKING / IDLE ---
        else:
            # Check candidate trigger (suppressed during post-click cooldown debounce)
            if pinch_dist is not None and pinch_dist < candidate_th and now >= self.cooldown_until:
                # Immediately freeze desktop cursor movement!
                self.state = MouseState.PINCH_CANDIDATE
                self.candidate_start_time = now
                locked_px = self._clamp_screen_coords(self.curr_x, self.curr_y)
                self.locked_position = locked_px
                logger.info(f"PINCH_CANDIDATE_STARTED(dist={pinch_dist:.4f}, locked_at={locked_px})")
                logger.info(f"CURSOR_LOCKED({locked_px[0]}, {locked_px[1]})")
                return self.state, locked_px, "PINCH CANDIDATE STARTED"

            # Normal tracking move
            px_x, px_y = self.move_cursor(norm_x, norm_y, timestamp=now)
            return self.state, (px_x, px_y), f"Moved to ({px_x}, {px_y})"
