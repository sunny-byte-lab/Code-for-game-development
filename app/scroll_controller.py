"""N.E.X.U.S. Hand-Gesture Scroll Controller & Windows Event Dispatcher.
Provides continuous, anchor-based vertical mouse-wheel scrolling via webcam hand gestures.

Features:
- Two-finger extended scroll gesture (Index + Middle) with anatomical tendon-coupling tolerance.
- Anchor-based reference: user establishes a stable neutral anchor upon gesture engagement.
- Proportional speed scaling: hand displacement above/below anchor scales scroll velocity.
- Stable neutral deadzone: prevents accidental scrolling during hand hovering or tremors.
- Cursor isolation: locks/freezes desktop mouse cursor during active scrolling to prevent drift.
- Rate-governed Windows mouse_event (MOUSEEVENTF_WHEEL = 0x0800) event dispatching.
- Full telemetry and real-time diagnostic reporting.
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any

from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QProgressBar, QFrame, QCheckBox
)

from app.filter import OneEuroFilter
from app.hand_tracker import INDEX_TIP, MIDDLE_TIP, RING_TIP, HandLandmarkData
from app.virtual_mouse import MouseBackend, WindowsMouseBackend
from app.theme import (
    ACCENT_CYAN, ACCENT_ICY_BLUE, ACCENT_BLUE, ACCENT_GOLD,
    ACCENT_GREEN, ACCENT_RED, BG_DARK_NAVY, BG_PANEL, TEXT_PRIMARY, TEXT_MUTED
)

logger = logging.getLogger("NEXUS.ScrollController")


class ScrollDirection(str, Enum):
    NONE = "NONE"
    UP = "UP"
    DOWN = "DOWN"


class ScrollStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ENGAGING = "ENGAGING"
    DEADZONE = "DEADZONE"
    ACTIVE = "ACTIVE"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class ScrollTelemetry:
    """Live telemetry emitted by the scroll controller on each optical frame."""
    hand_detected: bool = False
    gesture_name: str = "NONE"
    scroll_mode: bool = False             # True = ACTIVE, False = INACTIVE
    direction: str = "NONE"               # "UP", "DOWN", "NONE"
    speed: float = 0.0                    # notches / events per second
    displacement: float = 0.0             # normalized offset from anchor
    anchor_y: Optional[float] = None
    current_y: Optional[float] = None
    last_event_status: str = "NOT_SENT"   # "SUCCESS", "ERROR", "NOT_SENT", "DEADZONE"
    wheel_delta: int = 0
    total_events: int = 0
    timestamp: float = field(default_factory=time.time)


class ScrollController:
    """
    Authoritative controller for hand-gesture desktop scrolling.
    Translates continuous vertical hand displacement from an anchor into standard
    Windows mouse wheel events (WHEEL_DELTA = 120).
    """

    def __init__(self,
                 backend: Optional[MouseBackend] = None,
                 sensitivity: float = 1.2,
                 deadzone: float = 0.035,
                 min_speed: float = 2.0,
                 max_speed: float = 22.0,
                 invert_direction: bool = False,
                 engagement_required_frames: int = 2):
        self.backend: MouseBackend = backend or WindowsMouseBackend()
        self.sensitivity: float = max(0.2, min(5.0, sensitivity))
        self.deadzone: float = max(0.01, min(0.10, deadzone))
        self.min_speed: float = min_speed
        self.max_speed: float = max_speed
        self.invert_direction: bool = invert_direction
        self.max_displacement: float = 0.22

        # State tracking
        self.is_active: bool = False
        self.anchor_y: Optional[float] = None
        self.anchor_x: Optional[float] = None
        self.current_direction: ScrollDirection = ScrollDirection.NONE
        self.current_speed: float = 0.0
        self.last_event_status: str = "NOT_SENT"
        self.last_scroll_time: float = 0.0
        self.total_scroll_events: int = 0
        self.last_wheel_delta: int = 0

        # Gesture debounce & engagement
        self._engagement_frames: int = 0
        self._engagement_required_frames: int = max(1, engagement_required_frames)

        # Smoothing filter for vertical tracking point
        self._filter_y = OneEuroFilter(min_cutoff=1.2, beta=0.06)

    def reset(self) -> None:
        """Resets all active scroll state and clears anchor."""
        self.stop_scrolling()

    def stop_scrolling(self) -> None:
        """Immediately halts scrolling and resets anchor reference."""
        if self.is_active:
            logger.info("[SCROLL] Scroll Mode DEACTIVATED.")
        self.is_active = False
        self.anchor_y = None
        self.anchor_x = None
        self.current_direction = ScrollDirection.NONE
        self.current_speed = 0.0
        self._engagement_frames = 0
        self._filter_y.reset()

    def process_hand(self,
                     hand: Optional[HandLandmarkData],
                     is_scroll_gesture: bool,
                     now: Optional[float] = None) -> ScrollTelemetry:
        """
        Main per-frame processing cycle.
        Evaluates hand posture, sets/maintains anchor, applies deadzone, and dispatches real wheel events.
        """
        now = now if now is not None else time.time()

        if hand is None or not is_scroll_gesture:
            self.stop_scrolling()
            return self.get_telemetry(
                hand_detected=(hand is not None),
                gesture_name="TWO_FINGER_SCROLL" if is_scroll_gesture else "OTHER"
            )

        # Midpoint of index and middle fingertips represents scroll tracking anchor
        p_idx = hand.get_norm(INDEX_TIP)
        p_mid = hand.get_norm(MIDDLE_TIP)
        raw_x = (p_idx[0] + p_mid[0]) / 2.0
        raw_y = (p_idx[1] + p_mid[1]) / 2.0
        smooth_y = self._filter_y.filter(raw_y, now)

        # Confirm gesture over consecutive frames before locking anchor
        if not self.is_active:
            self._engagement_frames += 1
            if self._engagement_frames >= self._engagement_required_frames:
                self.is_active = True
                self.anchor_y = smooth_y
                self.anchor_x = raw_x
                self.last_scroll_time = now
                logger.info(f"[SCROLL] Scroll Mode ENGAGED at anchor Y={smooth_y:.3f}")
            return self.get_telemetry(
                hand_detected=True,
                gesture_name="TWO_FINGER_SCROLL",
                scroll_mode=False,
                last_status="ENGAGING"
            )

        # -------------------------------------------------------------
        # ACTIVE SCROLLING STATE: Evaluate displacement from anchor
        # In normalized camera space: UP is negative dy (hand moved up), DOWN is positive dy (hand moved down)
        # -------------------------------------------------------------
        assert self.anchor_y is not None
        dy = smooth_y - self.anchor_y

        # Elastic anchor: smoothly pull anchor if user moves beyond max displacement
        if abs(dy) > self.max_displacement:
            excess = abs(dy) - self.max_displacement
            if dy > 0:
                self.anchor_y += excess
            else:
                self.anchor_y -= excess
            dy = smooth_y - self.anchor_y

        abs_dy = abs(dy)

        # Check deadzone
        if abs_dy <= self.deadzone:
            self.current_direction = ScrollDirection.NONE
            self.current_speed = 0.0
            self.last_event_status = "DEADZONE"
            return self.get_telemetry(
                hand_detected=True,
                gesture_name="TWO_FINGER_SCROLL",
                scroll_mode=True,
                direction="NONE",
                speed=0.0,
                displacement=dy,
                last_status="DEADZONE"
            )

        # Determine scroll direction
        # By default: hand UP (dy < 0) scrolls page UP (positive wheel); hand DOWN (dy > 0) scrolls DOWN (negative wheel)
        if dy < -self.deadzone:
            dir_val = ScrollDirection.DOWN if self.invert_direction else ScrollDirection.UP
        else:
            dir_val = ScrollDirection.UP if self.invert_direction else ScrollDirection.DOWN

        self.current_direction = dir_val

        # Proportional speed calculation
        mag = abs_dy - self.deadzone
        span = max(0.01, self.max_displacement - self.deadzone)
        ratio = min(1.0, mag / span)
        target_speed = (self.min_speed + (ratio * (self.max_speed - self.min_speed))) * self.sensitivity
        self.current_speed = target_speed

        # Rate-governed event dispatch: interval between discrete wheel notch events
        interval = 1.0 / max(1.0, self.current_speed)
        dt = now - self.last_scroll_time

        if dt >= interval:
            notches = 2 if self.current_speed > 16.0 else 1
            sign = +1 if self.current_direction == ScrollDirection.UP else -1
            wheel_delta = notches * 120 * sign

            ok = self.backend.scroll(wheel_delta)
            self.last_scroll_time = now
            self.total_scroll_events += 1
            self.last_wheel_delta = wheel_delta
            self.last_event_status = "SUCCESS" if ok else "ERROR"
            logger.debug(f"[SCROLL EVENT] Dir={self.current_direction.value} Delta={wheel_delta} Speed={self.current_speed:.1f} (success={ok})")

        return self.get_telemetry(
            hand_detected=True,
            gesture_name="TWO_FINGER_SCROLL",
            scroll_mode=True,
            direction=self.current_direction.value,
            speed=self.current_speed,
            displacement=dy,
            last_status=self.last_event_status,
            wheel_delta=self.last_wheel_delta
        )

    def synthetic_scroll(self, direction: ScrollDirection, notches: int = 1) -> bool:
        """Direct programmatic scroll dispatch for testing without webcam."""
        sign = +1 if direction == ScrollDirection.UP else -1
        wheel_delta = notches * 120 * sign
        ok = self.backend.scroll(wheel_delta)
        self.last_event_status = "SUCCESS" if ok else "ERROR"
        self.last_wheel_delta = wheel_delta
        self.total_scroll_events += 1
        return ok

    def get_telemetry(self,
                      hand_detected: bool = False,
                      gesture_name: str = "NONE",
                      scroll_mode: Optional[bool] = None,
                      direction: Optional[str] = None,
                      speed: Optional[float] = None,
                      displacement: Optional[float] = None,
                      last_status: Optional[str] = None,
                      wheel_delta: Optional[int] = None) -> ScrollTelemetry:
        """Constructs current snapshot of scroll controller telemetry."""
        return ScrollTelemetry(
            hand_detected=hand_detected,
            gesture_name=gesture_name,
            scroll_mode=self.is_active if scroll_mode is None else scroll_mode,
            direction=self.current_direction.value if direction is None else direction,
            speed=self.current_speed if speed is None else speed,
            displacement=0.0 if displacement is None else displacement,
            anchor_y=self.anchor_y,
            current_y=(self.anchor_y + displacement) if (self.anchor_y and displacement is not None) else None,
            last_event_status=self.last_event_status if last_status is None else last_status,
            wheel_delta=self.last_wheel_delta if wheel_delta is None else wheel_delta,
            total_events=self.total_scroll_events,
            timestamp=time.time()
        )

    def set_sensitivity(self, val: float) -> None:
        self.sensitivity = max(0.2, min(5.0, val))

    def set_deadzone(self, val: float) -> None:
        self.deadzone = max(0.01, min(0.10, val))

    def set_invert(self, val: bool) -> None:
        self.invert_direction = val


class ScrollDiagnosticWidget(QWidget):
    """
    Dedicated Diagnostic & Calibration Card for the Hand-Gesture Scrolling Subsystem.
    Displays live real-time status of hand detection, gesture name, scroll mode,
    direction, speed, and Windows mouse wheel event dispatch status.
    """

    sensitivity_changed = Signal(float)
    deadzone_changed = Signal(float)
    invert_changed = Signal(bool)

    def __init__(self, controller: Optional[ScrollController] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header Title with Live Mode Pill
        header_row = QHBoxLayout()
        title = QLabel("SCROLL SUBSYSTEM")
        title.setStyleSheet(f"font-size: 10px; font-weight: 900; color: {ACCENT_CYAN}; letter-spacing: 1.5px;")
        header_row.addWidget(title)
        header_row.addStretch()

        self.pill_mode = QLabel("INACTIVE")
        self.pill_mode.setStyleSheet(
            f"background: rgba(8, 20, 44, 0.9); border: 1px solid rgba(0, 200, 255, 0.3); "
            f"color: {TEXT_MUTED}; font-family: Consolas; font-size: 8px; font-weight: 800; "
            f"padding: 2px 6px; border-radius: 3px;"
        )
        header_row.addWidget(self.pill_mode)
        layout.addLayout(header_row)

        # 6 Core Required Telemetry Fields
        grid_frame = QFrame()
        grid_frame.setStyleSheet("background: rgba(4, 12, 28, 0.7); border: 1px solid rgba(0, 200, 255, 0.15); border-radius: 4px;")
        gl = QVBoxLayout(grid_frame)
        gl.setContentsMargins(6, 6, 6, 6)
        gl.setSpacing(4)

        self._labels = {}
        for key, name in [
            ("hand",      "HAND DETECTED"),
            ("gesture",   "CURRENT GESTURE"),
            ("mode",      "SCROLL MODE"),
            ("direction", "DIRECTION"),
            ("speed",     "SCROLL SPEED"),
            ("last_evt",  "LAST SCROLL EVENT"),
        ]:
            row = QHBoxLayout()
            lbl_k = QLabel(f"{name}:")
            lbl_k.setStyleSheet(f"font-size: 8px; font-weight: 700; color: {TEXT_MUTED}; letter-spacing: 0.8px;")
            lbl_k.setFixedWidth(120)

            lbl_v = QLabel("--")
            lbl_v.setStyleSheet(f"font-family: Consolas; font-size: 8px; font-weight: 700; color: {ACCENT_CYAN};")
            row.addWidget(lbl_k)
            row.addWidget(lbl_v)
            row.addStretch()
            gl.addLayout(row)
            self._labels[key] = lbl_v

        layout.addWidget(grid_frame)

        # Displacement & Neutral Zone Meter
        layout.addWidget(QLabel("ANCHOR DISPLACEMENT:"))
        self.bar_disp = QProgressBar()
        self.bar_disp.setRange(-100, 100)
        self.bar_disp.setValue(0)
        self.bar_disp.setFixedHeight(8)
        self.bar_disp.setTextVisible(False)
        self.bar_disp.setStyleSheet(f"""
            QProgressBar {{ background: rgba(8, 18, 42, 0.8); border: 1px solid rgba(0, 200, 255, 0.2); border-radius: 4px; }}
            QProgressBar::chunk {{ background: {ACCENT_CYAN}; }}
        """)
        layout.addWidget(self.bar_disp)

        # Sensitivity Slider
        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("SENSITIVITY:"))
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(5, 30)  # 0.5x to 3.0x
        init_sens = int(self.controller.sensitivity * 10) if self.controller else 12
        self.slider_sens.setValue(init_sens)
        self.lbl_sens = QLabel(f"{init_sens / 10.0:.1f}x")
        self.lbl_sens.setStyleSheet(f"font-family: Consolas; font-size: 8px; color: {ACCENT_CYAN};")
        sens_row.addWidget(self.slider_sens)
        sens_row.addWidget(self.lbl_sens)
        layout.addLayout(sens_row)

        # Deadzone Slider
        dead_row = QHBoxLayout()
        dead_row.addWidget(QLabel("DEADZONE:"))
        self.slider_dead = QSlider(Qt.Horizontal)
        self.slider_dead.setRange(10, 80)  # 0.010 to 0.080
        init_dead = int(self.controller.deadzone * 1000) if self.controller else 35
        self.slider_dead.setValue(init_dead)
        self.lbl_dead = QLabel(f"{init_dead / 1000.0:.3f}")
        self.lbl_dead.setStyleSheet(f"font-family: Consolas; font-size: 8px; color: {ACCENT_CYAN};")
        dead_row.addWidget(self.slider_dead)
        dead_row.addWidget(self.lbl_dead)
        layout.addLayout(dead_row)

        # Invert Direction Checkbox
        self.chk_invert = QCheckBox("INVERT SCROLL DIRECTION (NATURAL)")
        self.chk_invert.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 8px;")
        if self.controller:
            self.chk_invert.setChecked(self.controller.invert_direction)
        layout.addWidget(self.chk_invert)

        # Synthetic Test Buttons (directly tests Windows mouse wheel events)
        test_btn_row = QHBoxLayout()
        self.btn_test_up = QPushButton("TEST ▲ UP")
        self.btn_test_dn = QPushButton("TEST ▼ DOWN")
        btn_style = (
            f"background: rgba(0, 180, 255, 0.15); border: 1px solid {ACCENT_CYAN}; "
            f"color: #FFFFFF; font-family: Consolas; font-size: 8px; font-weight: bold; padding: 4px;"
        )
        self.btn_test_up.setStyleSheet(btn_style)
        self.btn_test_dn.setStyleSheet(btn_style)
        test_btn_row.addWidget(self.btn_test_up)
        test_btn_row.addWidget(self.btn_test_dn)
        layout.addLayout(test_btn_row)

        # Connect signals
        self.slider_sens.valueChanged.connect(self._on_sens_changed)
        self.slider_dead.valueChanged.connect(self._on_dead_changed)
        self.chk_invert.toggled.connect(self._on_invert_toggled)
        self.btn_test_up.clicked.connect(lambda: self._test_scroll(ScrollDirection.UP))
        self.btn_test_dn.clicked.connect(lambda: self._test_scroll(ScrollDirection.DOWN))

    def _on_sens_changed(self, val: int) -> None:
        sens = val / 10.0
        self.lbl_sens.setText(f"{sens:.1f}x")
        if self.controller:
            self.controller.set_sensitivity(sens)
        self.sensitivity_changed.emit(sens)

    def _on_dead_changed(self, val: int) -> None:
        dz = val / 1000.0
        self.lbl_dead.setText(f"{dz:.3f}")
        if self.controller:
            self.controller.set_deadzone(dz)
        self.deadzone_changed.emit(dz)

    def _on_invert_toggled(self, checked: bool) -> None:
        if self.controller:
            self.controller.set_invert(checked)
        self.invert_changed.emit(checked)

    def _test_scroll(self, direction: ScrollDirection) -> None:
        if self.controller:
            ok = self.controller.synthetic_scroll(direction, notches=1)
            self.update_telemetry(self.controller.get_telemetry())
        else:
            backend = WindowsMouseBackend()
            backend.scroll(120 if direction == ScrollDirection.UP else -120)

    @Slot(object)
    def update_telemetry(self, telem: ScrollTelemetry) -> None:
        """Updates all 6 core telemetry fields and visual meters from a ScrollTelemetry packet."""
        # 1. Hand detected
        self._labels["hand"].setText("YES" if telem.hand_detected else "NO")
        self._labels["hand"].setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: 700; color: {ACCENT_GREEN if telem.hand_detected else ACCENT_RED};"
        )

        # 2. Current gesture
        self._labels["gesture"].setText(telem.gesture_name)

        # 3. Scroll mode
        is_act = telem.scroll_mode
        self._labels["mode"].setText("ACTIVE" if is_act else "INACTIVE")
        self._labels["mode"].setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: 700; color: {ACCENT_GREEN if is_act else TEXT_MUTED};"
        )

        if is_act:
            self.pill_mode.setText("● ACTIVE")
            self.pill_mode.setStyleSheet(
                f"background: rgba(6, 40, 20, 0.9); border: 1px solid {ACCENT_GREEN}; "
                f"color: {ACCENT_GREEN}; font-family: Consolas; font-size: 8px; font-weight: 800; "
                f"padding: 2px 6px; border-radius: 3px;"
            )
        else:
            self.pill_mode.setText("○ INACTIVE")
            self.pill_mode.setStyleSheet(
                f"background: rgba(8, 20, 44, 0.9); border: 1px solid rgba(0, 200, 255, 0.3); "
                f"color: {TEXT_MUTED}; font-family: Consolas; font-size: 8px; font-weight: 800; "
                f"padding: 2px 6px; border-radius: 3px;"
            )

        # 4. Direction
        dir_sym = "▲ UP" if telem.direction == "UP" else ("▼ DOWN" if telem.direction == "DOWN" else "— NONE")
        dir_color = ACCENT_CYAN if telem.direction in ("UP", "DOWN") else TEXT_MUTED
        self._labels["direction"].setText(dir_sym)
        self._labels["direction"].setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: 700; color: {dir_color};"
        )

        # 5. Scroll speed
        self._labels["speed"].setText(f"{telem.speed:.1f} notches/s" if is_act else "0.0 notches/s")

        # 6. Last scroll event
        st = telem.last_event_status
        st_color = ACCENT_GREEN if st == "SUCCESS" else (ACCENT_GOLD if st == "DEADZONE" else (ACCENT_RED if st == "ERROR" else TEXT_MUTED))
        info_txt = f"{st} ({telem.wheel_delta})" if telem.wheel_delta != 0 else st
        self._labels["last_evt"].setText(info_txt)
        self._labels["last_evt"].setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: 700; color: {st_color};"
        )

        # Displacement Progress Bar
        val = int(telem.displacement * 400.0)
        self.bar_disp.setValue(max(-100, min(100, val)))
