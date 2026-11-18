"""N.E.X.U.S. Holographic Virtual Keyboard & Real Text Editor Engine.
Cinematic Iron Man-inspired 3D floating QWERTY keyboard operated via webcam Two-Hand Air Typing.
Enables typing by moving individual fingers forward toward virtual keys in the air.
Rendered programmatically via QPainter for GPU-free 60fps performance on integrated graphics.
"""

import math
import time
import os
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QSizeF, Signal, Slot
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient,
    QLinearGradient, QPainterPath, QPolygonF
)
from PySide6.QtWidgets import (
    QWidget, QSizePolicy, QApplication, QFileDialog, QMessageBox,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QFrame
)

import pyautogui
from app.filter import PointFilter2D
from app.windows_keyboard_service import WindowsKeyboardInputService
from app.theme import (
    ACCENT_CYAN, ACCENT_ICY_BLUE, ACCENT_BLUE, ACCENT_GOLD,
    ACCENT_GREEN, ACCENT_RED, BG_DARK_NAVY, BG_PANEL, TEXT_PRIMARY, TEXT_MUTED
)

logger = logging.getLogger("NEXUS.HoloKeyboard")


class FingerPressState(str, Enum):
    """Lifecycle states of an individual finger and pinch interaction in Air Typing."""
    IDLE = "IDLE"                           # Hand/finger not tracked or outside interaction bounds
    HOVER = "HOVER"                         # Hovering over virtual key (NO PRESS)
    HOVERING = "HOVER"                      # Backward-compatible alias for HOVER
    PINCH_CANDIDATE = "CANDIDATE"           # Possible pinch detected (fingers closing)
    CANDIDATE = "CANDIDATE"                 # Forward or pinch candidate alias
    PRESSED = "PRESSED"                     # Pinch/press confirmed; exactly 1 keystroke sent; locked against repeat
    WAIT_FOR_RELEASE = "WAIT_FOR_RELEASE"   # Pinch held; zero repeats until released
    RELEASE_WAIT = "WAIT_FOR_RELEASE"       # Backward-compatible alias for WAIT_FOR_RELEASE
    RELEASED = "RELEASED"                   # Re-armed after release


@dataclass
class KeyDef:
    """Represents a single key on the holographic keyboard."""
    key_id: str
    label: str
    shift_label: str
    char: str
    shift_char: str
    action: Optional[str] = None       # Special action identifier if not regular char
    col_span: float = 1.0              # Relative key width
    is_accent: bool = False            # Reactor gold/amber highlight
    assigned_hand: str = "ANY"         # "LEFT", "RIGHT", "ANY"
    assigned_finger: str = "ANY"       # "PINKY", "RING", "MIDDLE", "INDEX", "THUMB", "ANY"
    rect: QRectF = field(default_factory=QRectF)
    # Animated feedback states
    glow_intensity: float = 0.0        # 0.0 to 1.0 on keypress
    is_hovered: bool = False
    is_pressed: bool = False
    hover_fingers: List[str] = field(default_factory=list)


@dataclass
class KeyRipple:
    """Holographic expanding shockwave animation emitted on keypress."""
    center: QPointF
    current_r: float = 4.0
    max_r: float = 48.0
    alpha: float = 240.0
    color: QColor = field(default_factory=lambda: QColor(0, 240, 255))
    speed: float = 3.0


@dataclass
class FingerAirState:
    """State tracking for an individual finger in Two-Hand Air Typing."""
    hand_side: str            # "LEFT" or "RIGHT"
    finger_name: str          # "thumb", "index", "middle", "ring", "pinky"
    finger_id: str            # "L_INDEX", "R_MIDDLE", etc.
    screen_pos: QPointF = field(default_factory=lambda: QPointF(-100, -100))
    norm_pos: Tuple[float, float] = (0.5, 0.5)
    raw_depth: float = 0.0    # Raw forward-press landmark metric
    calibrated_depth: float = 0.0 # Metric relative to neutral baseline (0.0 = resting)
    press_depth: float = 0.0  # Backward-compatible alias matching calibrated_depth
    baseline_depth: float = 0.10 # Calibrated resting posture baseline (default 0.10)
    state: FingerPressState = FingerPressState.IDLE
    is_pressed: bool = False
    press_locked: bool = False # Strict hysteresis lock: must withdraw before re-arming
    locked_key_id: Optional[str] = None
    last_press_time: float = 0.0
    hovered_key_id: Optional[str] = None
    filter_point: PointFilter2D = field(default_factory=lambda: PointFilter2D(filter_type="one_euro", min_cutoff=1.4, beta=0.08))
    prev_z: float = 0.0
    z_velocity: float = 0.0
    prev_canvas_pos: Optional[Tuple[float, float]] = None
    candidate_start_time: Optional[float] = None
    visible: bool = False
    tracking_confidence: float = 0.0
    norm_pinch: float = 1.0
    last_rejection_reason: str = "IDLE"
    trigger_method: str = "NONE"
    hover_start_time: float = 0.0
    dwell_progress: float = 0.0
    dwell_locked_key_id: Optional[str] = None
    dwell_anchor_pos: Optional[QPointF] = None
    last_hovered_key_id: Optional[str] = None
    is_extended: bool = True
    extension_score: float = 1.0


class HolographicKeyboardWidget(QWidget):
    """
    Floating 3D Holographic QWERTY Keyboard and Real Text Editor.
    Features:
    - TWO-HAND AIR TYPING: Individual finger forward-press detection in monocular space.
    - Automatic activation when both hands are positioned in front of the camera.
    - 5-row full QWERTY keyboard with numbers, symbols, shift, caps lock, backspace, space, enter, and navigation arrows.
    - Split ergonomic key assignments: Left hand covers Q-T/A-G/Z-B; Right hand covers Y-P/H-Enter/N-Shift.
    - Strict per-finger hysteresis: exactly one character per press; no accidental duplicate typing while holding.
    - Floating text preview buffer with real-time typing, blinking cursor, and telemetry.
    - Mode isolation: Blocks desktop mouse events and pinch-clicks when typing.
    - Integrated text editor tools: Select All, Clear, Copy, Cut, Paste, Save to local file.
    - Optional external typing mode (safely sends keystrokes to focused Windows app when explicitly armed).
    - Iron Man HUD aesthetics: Floating 3D perspective depth, glowing cyan/blue key outlines, scanning line, tech reticles.
    """

    text_changed = Signal(str)
    key_triggered = Signal(str)
    mode_changed = Signal(str)
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(540, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # -------------------------------------------------------------
        # Text Editor State
        # -------------------------------------------------------------
        self.text_buffer: str = "N.E.X.U.S. AIR TYPING TERMINAL READY.\n"
        self.cursor_pos: int = len(self.text_buffer)
        self.selection_start: Optional[int] = None
        self.selection_end: Optional[int] = None
        self._cursor_blink_visible: bool = True
        self._last_cursor_blink: float = time.time()

        # -------------------------------------------------------------
        # Keyboard Mode & State
        # -------------------------------------------------------------
        self.is_shift: bool = False
        self.is_caps_lock: bool = False
        self.external_typing_enabled: bool = False  # Enabled via settings or toggle for real global Windows typing
        self.global_typing_enabled: bool = False    # Dispatches live keystrokes to external apps when armed
        self.test_mode: bool = True                 # Test mode starts active for safety until armed
        self.keyboard_paused: bool = False
        self.show_perspective_3d: bool = True
        self.global_overlay = None                  # Hook for floating non-focus-stealing HUD overlay

        # OS-level Keyboard Service
        self.keyboard_service = WindowsKeyboardInputService()

        # -------------------------------------------------------------
        # Two-Hand Air Typing Engine (10 Individual Fingers)
        # -------------------------------------------------------------
        self.fingers: Dict[str, FingerAirState] = {}
        for hand in ("L", "R"):
            for fname in ("thumb", "index", "middle", "ring", "pinky"):
                fid = f"{hand}_{fname.upper()}"
                self.fingers[fid] = FingerAirState(
                    hand_side="LEFT" if hand == "L" else "RIGHT",
                    finger_name=fname,
                    finger_id=fid
                )

        # -------------------------------------------------------------
        # Dual-Hand Mode & Multi-Gesture State Machine
        # -------------------------------------------------------------
        self.one_hand_test_mode: bool = False  # Full Dual-Hand Mode (either hand or both can type anywhere!)
        self.active_typing_hand: str = "RIGHT"

        # Multi-modal trigger thresholds (DWELL default, PINCH optional)
        self.press_detection_mode: str = "DWELL"      # Hands-free Dwell-to-Type is default!
        self.pinch_candidate_threshold: float = 0.48  # Approaching pinch
        self.pinch_threshold: float = 0.36            # Confirmed deliberate pinch
        self.pinch_release_threshold: float = 0.52    # Deliberate release
        self.pinch_to_press_threshold: float = 0.36
        self.pinch_to_release_threshold: float = 0.52
        self.pinch_typing_state: FingerPressState = FingerPressState.HOVER

        # Dwell-to-Type Engine (Hands-Free Pointing)
        self.hover_dwell_time: float = 0.50           # Default 0.50s steady hover confirms keypress (0.3 - 1.0s)
        self.dwell_jitter_tolerance: float = 25.0     # 25px tremor tolerance keeps timer running
        self.hover_start_time: float = 0.0
        self.last_hovered_key_id: Optional[str] = None
        self.dwell_progress: float = 0.0              # 0.0 to 1.0 progress for visual countdown gauge
        self.dwell_locked_key_id: Optional[str] = None
        self.dwell_anchor_pos: Optional[QPointF] = None
        self.keypress_cooldown: float = 0.20          # 0.20s cooldown between consecutive key activations

        # Forward-press thresholds (kept for FORWARD_TAP/HYBRID mode compatibility)
        self.candidate_threshold: float = 0.08
        self.press_threshold: float = 0.14
        self.release_threshold: float = 0.04
        self.key_selection_test_mode: bool = False  # Diagnostic mode (Phase 5)
        self.backspace_repeat_enabled: bool = False
        self._backspace_hold_start: Optional[float] = None
        self._last_backspace_repeat: float = 0.0

        # Neutral Posture Calibration State
        self.is_calibrated: bool = False
        self.calibration_active: bool = False
        self._calibration_active: bool = False
        self.calibration_countdown: float = 0.0
        self.calibration_start_time: float = 0.0
        self.calibration_samples: Dict[str, List[float]] = {fid: [] for fid in self.fingers}
        self.hand_neutral_stabilization_until: float = 0.0
        self.hand_neutral_stabilization_duration: float = 0.0

        # Hand presence and dual-hand diagnostics telemetry (Phase 2 & 5)
        self.left_hand_present: bool = False
        self.right_hand_present: bool = False
        self.left_detected: bool = False
        self.right_detected: bool = False
        self.left_tracking_conf: float = 0.0
        self.right_tracking_conf: float = 0.0
        self.left_handedness_conf: float = 0.0
        self.right_handedness_conf: float = 0.0
        self.left_assigned_zone: str = "LEFT (Q-T, A-G, Z-B)"
        self.right_assigned_zone: str = "RIGHT (Y-P, H-Enter, N-Shift)"
        self.left_hovered_key: str = "NONE"
        self.right_hovered_key: str = "NONE"
        self.left_press_state: str = "IDLE"
        self.right_press_state: str = "IDLE"
        self.left_index_coords: Tuple[int, int] = (0, 0)
        self.right_index_coords: Tuple[int, int] = (0, 0)
        self.left_index_norm: Tuple[float, float] = (0.5, 0.5)
        self.right_index_norm: Tuple[float, float] = (0.5, 0.5)
        self.left_index_hitbox: Optional[QRectF] = None
        self.right_index_hitbox: Optional[QRectF] = None
        self.left_index_inside: bool = False
        self.right_index_inside: bool = False
        self.left_rejection_reason: str = "IDLE"
        self.right_rejection_reason: str = "IDLE"
        self.detected_hand_count: int = 0
        self.dual_hand_mode_state: str = "MOUSE_MODE"
        self.mode_switch_countdown: float = 0.0
        self.last_mode_transition_reason: str = "INITIALIZED"
        self.left_index_extended: bool = False
        self.right_index_extended: bool = False
        self.left_extension_score: float = 0.0
        self.right_extension_score: float = 0.0

        # Frame freshness telemetry
        self.last_frame_timestamp: float = 0.0
        self.last_frame_id: int = 0
        self.last_frame_age_ms: float = 0.0
        self.tracking_freshness_status: str = "AWAITING SENSOR"
        self.sensor_frame_width: int = 640
        self.sensor_frame_height: int = 480

        self.last_dispatched_event: str = "NONE"
        self.last_rejected_reason: str = "NONE"

        self.is_hand_present: bool = False
        self.total_keystrokes: int = 0
        self.session_start_time: float = time.time()
        self.last_typed_char: str = ""
        self.last_typed_key_id: str = ""
        self.last_typed_finger_id: str = ""
        self.last_typed_time: float = 0.0
        self.show_diagnostics_hud: bool = True

        # Virtual Pointer & Legacy Pinch-to-Type Compatibility
        self.pointer_filter = PointFilter2D(filter_type="one_euro", min_cutoff=1.2, beta=0.08)
        self.pointer_screen_pos: QPointF = QPointF(-100, -100)
        self.pointer_norm_pos: Tuple[float, float] = (0.5, 0.5)
        self.pointer_visible: bool = False
        self.hovered_key: Optional[KeyDef] = None
        self.pinch_threshold: float = 0.38
        self.pinch_release_threshold: float = 0.52
        self.is_pinch_active: bool = False
        self.pinch_locked: bool = False
        self.current_pinch_dist: float = 1.0
        self.last_keypress_time: float = 0.0

        # Tracking calibration / ROI mapping
        self.sensitivity_x: float = 1.35
        self.sensitivity_y: float = 1.35
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0
        self.roi_left: float = 0.15
        self.roi_right: float = 0.85
        self.roi_top: float = 0.15
        self.roi_bottom: float = 0.85

        # Visual Animation States
        self._ripples: List[KeyRipple] = []
        self._scan_line_y: float = 0.0
        self._phase: float = 0.0
        self._activation_anim_progress: float = 0.0  # 1.0 -> 0.0 fade out
        self._activation_banner_text: str = ""
        self._particles = [
            {"x": 0.1 * i, "y": 0.2 * i, "speed": 0.003 + 0.002 * (i % 3), "r": 1.5 + (i % 2)}
            for i in range(16)
        ]

        # Initialize layout
        self.keys: List[KeyDef] = []
        self._init_keyboard_layout()

        # Animation timer (30-60 FPS smooth updates)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animation_tick)
        self._timer.start(33)

    # -----------------------------------------------------------------
    # Layout Builder with Ergonomic Finger Assignments
    # -----------------------------------------------------------------
    def _init_keyboard_layout(self) -> None:
        """Constructs the complete futuristic QWERTY keyboard with two-hand finger assignments."""
        self.keys.clear()

        # Row 0: Esc, Numbers, Punctuation, Backspace
        row0 = [
            KeyDef("esc", "ESC", "ESC", "", "", action="esc", col_span=1.2, is_accent=True, assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("1", "1", "!", "1", "!", assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("2", "2", "@", "2", "@", assigned_hand="LEFT", assigned_finger="RING"),
            KeyDef("3", "3", "#", "3", "#", assigned_hand="LEFT", assigned_finger="MIDDLE"),
            KeyDef("4", "4", "$", "4", "$", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("5", "5", "%", "5", "%", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("6", "6", "^", "6", "^", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("7", "7", "&", "7", "&", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("8", "8", "*", "8", "*", assigned_hand="RIGHT", assigned_finger="MIDDLE"),
            KeyDef("9", "9", "(", "9", "(", assigned_hand="RIGHT", assigned_finger="RING"),
            KeyDef("0", "0", ")", "0", ")", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("-", "-", "_", "-", "_", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("=", "=", "+", "=", "+", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("bsp", "BKSP", "BKSP", "", "", action="backspace", col_span=1.6, is_accent=True, assigned_hand="RIGHT", assigned_finger="PINKY"),
        ]

        # Row 1: Tab, QWERTY, Brackets
        row1 = [
            KeyDef("tab", "TAB", "TAB", "\t", "\t", action="tab", col_span=1.4, is_accent=True, assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("q", "Q", "Q", "q", "Q", assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("w", "W", "W", "w", "W", assigned_hand="LEFT", assigned_finger="RING"),
            KeyDef("e", "E", "E", "e", "E", assigned_hand="LEFT", assigned_finger="MIDDLE"),
            KeyDef("r", "R", "R", "r", "R", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("t", "T", "T", "t", "T", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("y", "Y", "Y", "y", "Y", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("u", "U", "U", "u", "U", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("i", "I", "I", "i", "I", assigned_hand="RIGHT", assigned_finger="MIDDLE"),
            KeyDef("o", "O", "O", "o", "O", assigned_hand="RIGHT", assigned_finger="RING"),
            KeyDef("p", "P", "P", "p", "P", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("[", "[", "{", "[", "{", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("]", "]", "}", "]", "}", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("\\", "\\", "|", "\\", "|", col_span=1.2, assigned_hand="RIGHT", assigned_finger="PINKY"),
        ]

        # Row 2: Caps Lock, ASDF, Semicolon, Quote, Enter
        row2 = [
            KeyDef("caps", "CAPS", "CAPS", "", "", action="caps", col_span=1.6, is_accent=True, assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("a", "A", "A", "a", "A", assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("s", "S", "S", "s", "S", assigned_hand="LEFT", assigned_finger="RING"),
            KeyDef("d", "D", "D", "d", "D", assigned_hand="LEFT", assigned_finger="MIDDLE"),
            KeyDef("f", "F", "F", "f", "F", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("g", "G", "G", "g", "G", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("h", "H", "H", "h", "H", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("j", "J", "J", "j", "J", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("k", "K", "K", "k", "K", assigned_hand="RIGHT", assigned_finger="MIDDLE"),
            KeyDef("l", "L", "L", "l", "L", assigned_hand="RIGHT", assigned_finger="RING"),
            KeyDef(";", ";", ":", ";", ":", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("'", "'", "\"", "'", "\"", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("enter", "ENTER", "ENTER", "\n", "\n", action="enter", col_span=1.8, is_accent=True, assigned_hand="RIGHT", assigned_finger="PINKY"),
        ]

        # Row 3: Shift, ZXCV, Navigation Up, Shift
        row3 = [
            KeyDef("shift_l", "SHIFT", "SHIFT", "", "", action="shift", col_span=1.8, is_accent=True, assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("z", "Z", "Z", "z", "Z", assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("x", "X", "X", "x", "X", assigned_hand="LEFT", assigned_finger="RING"),
            KeyDef("c", "C", "C", "c", "C", assigned_hand="LEFT", assigned_finger="MIDDLE"),
            KeyDef("v", "V", "V", "v", "V", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("b", "B", "B", "b", "B", assigned_hand="LEFT", assigned_finger="INDEX"),
            KeyDef("n", "N", "N", "n", "N", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef("m", "M", "M", "m", "M", assigned_hand="RIGHT", assigned_finger="INDEX"),
            KeyDef(",", ",", "<", ",", "<", assigned_hand="RIGHT", assigned_finger="MIDDLE"),
            KeyDef(".", ".", ">", ".", ">", assigned_hand="RIGHT", assigned_finger="RING"),
            KeyDef("/", "/", "?", "/", "?", assigned_hand="RIGHT", assigned_finger="PINKY"),
            KeyDef("up", "▲", "▲", "", "", action="up", col_span=1.1, is_accent=True, assigned_hand="RIGHT", assigned_finger="THUMB"),
            KeyDef("shift_r", "SHIFT", "SHIFT", "", "", action="shift", col_span=1.5, is_accent=True, assigned_hand="RIGHT", assigned_finger="PINKY"),
        ]

        # Row 4: Space, Edit Actions, Arrows
        row4 = [
            KeyDef("clr", "CLEAR", "CLEAR", "", "", action="clear", col_span=1.3, is_accent=True, assigned_hand="LEFT", assigned_finger="PINKY"),
            KeyDef("all", "ALL", "ALL", "", "", action="select_all", col_span=1.1, assigned_hand="LEFT", assigned_finger="THUMB"),
            KeyDef("space", "SPACEBAR", "SPACEBAR", " ", " ", action="space", col_span=5.2, assigned_hand="ANY", assigned_finger="THUMB"),
            KeyDef("left", "◄", "◄", "", "", action="left", col_span=1.0, is_accent=True, assigned_hand="RIGHT", assigned_finger="THUMB"),
            KeyDef("down", "▼", "▼", "", "", action="down", col_span=1.0, is_accent=True, assigned_hand="RIGHT", assigned_finger="THUMB"),
            KeyDef("right", "►", "►", "", "", action="right", col_span=1.0, is_accent=True, assigned_hand="RIGHT", assigned_finger="THUMB"),
            KeyDef("copy", "COPY", "COPY", "", "", action="copy", col_span=1.1, assigned_hand="RIGHT", assigned_finger="THUMB"),
            KeyDef("paste", "PASTE", "PASTE", "", "", action="paste", col_span=1.1, assigned_hand="RIGHT", assigned_finger="THUMB"),
        ]

        self.keyboard_rows = [row0, row1, row2, row3, row4]
        for row in self.keyboard_rows:
            self.keys.extend(row)
        self._recalculate_key_geometry()

    # -----------------------------------------------------------------
    # Geometry and Layout Calculation
    # -----------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.keyboard_paused = False
        self._recalculate_key_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._recalculate_key_geometry()

    def _recalculate_key_geometry(self) -> None:
        """Computes bounding boxes for each key based on widget size."""
        w = float(self.width())
        h = float(self.height())
        if w <= 10.0 or h <= 10.0:
            return

        # Top area reserved for text preview & telemetry (top 35%)
        top_margin = max(90.0, h * 0.35)
        bottom_margin = 12.0
        side_margin = 18.0

        kb_w = w - (side_margin * 2.0)
        kb_h = h - top_margin - bottom_margin
        row_count = len(self.keyboard_rows)
        row_h = (kb_h - (row_count - 1) * 5.0) / row_count

        for r_idx, row in enumerate(self.keyboard_rows):
            total_spans = sum(k.col_span for k in row)
            spacing = 5.0
            avail_w = kb_w - (len(row) - 1) * spacing
            unit_w = avail_w / total_spans

            y_pos = top_margin + (r_idx * (row_h + spacing))
            cur_x = side_margin

            for k in row:
                key_w = unit_w * k.col_span
                # 1:1 match between visual key rectangle and interaction hitbox
                k.rect = QRectF(cur_x, y_pos, key_w, row_h)
                cur_x += key_w + spacing

    def get_key_at_point(self, pos: QPointF) -> Optional[KeyDef]:
        """
        Finds the virtual key under or closest to the given screen coordinates.
        Checks exact QRectF containment first. If the point falls in the 5px gap between keys
        or near boundaries, resolves to the nearest valid key within a 48px proximity margin.
        """
        if pos.x() < 0 or pos.y() < 0:
            return None

        # 1. Exact containment
        for k in self.keys:
            if k.rect.contains(pos):
                return k

        # 2. Generous proximity fallback: find nearest key within 48px margin
        best_k = None
        min_dist_sq = 48.0 * 48.0
        for k in self.keys:
            r = k.rect
            cx = max(r.left(), min(pos.x(), r.right()))
            cy = max(r.top(), min(pos.y(), r.bottom()))
            dist_sq = (pos.x() - cx) ** 2 + (pos.y() - cy) ** 2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                best_k = k

        return best_k

    def map_camera_to_keyboard(self, norm_x: float, norm_y: float) -> Tuple[float, float, bool]:
        """
        Authoritative 1:1 camera-to-virtual-keyboard coordinate transformation.
        Maps interaction area [roi_left..roi_right, roi_top..roi_bottom]
        directly into the interactive keyboard key area [side_margin..w-side_margin, top_margin..h-bottom_margin].
        Used identically for both left and right hands to ensure zero coordinate jumps or distortions.

        Returns:
            (canvas_x: float, canvas_y: float, is_in_roi: bool)
        """
        w = float(self.width())
        h = float(self.height())
        top_margin = max(90.0, h * 0.35)
        bottom_margin = 12.0
        side_margin = 18.0

        is_in_roi = (self.roi_left <= norm_x <= self.roi_right and self.roi_top <= norm_y <= self.roi_bottom)

        denom_x = max(0.05, self.roi_right - self.roi_left)
        denom_y = max(0.05, self.roi_bottom - self.roi_top)

        clamped_nx = max(0.0, min(1.0, (norm_x - self.roi_left) / denom_x))
        clamped_ny = max(0.0, min(1.0, (norm_y - self.roi_top) / denom_y))

        canvas_x = side_margin + clamped_nx * (w - (side_margin * 2.0))
        canvas_y = top_margin + clamped_ny * (h - top_margin - bottom_margin)
        return canvas_x, canvas_y, is_in_roi

    def map_keyboard_to_camera(self, canvas_x: float, canvas_y: float) -> Tuple[float, float]:
        """
        Inverse transformation: converts canvas pixel coordinates back to normalized camera coordinates.
        Ensures exact 1:1 mathematical alignment for test fixtures and auto-calibration.
        """
        w = float(self.width())
        h = float(self.height())
        top_margin = max(90.0, h * 0.35)
        bottom_margin = 12.0
        side_margin = 18.0

        avail_w = max(1.0, w - (side_margin * 2.0))
        avail_h = max(1.0, h - top_margin - bottom_margin)

        clamped_nx = max(0.0, min(1.0, (canvas_x - side_margin) / avail_w))
        clamped_ny = max(0.0, min(1.0, (canvas_y - top_margin) / avail_h))

        denom_x = max(0.05, self.roi_right - self.roi_left)
        denom_y = max(0.05, self.roi_bottom - self.roi_top)

        norm_x = self.roi_left + clamped_nx * denom_x
        norm_y = self.roi_top + clamped_ny * denom_y
        return norm_x, norm_y

    def test_key_hitbox(self, pos: QPointF) -> Tuple[Optional[KeyDef], bool, Optional[QRectF]]:
        """
        Diagnostic helper for Key-Selection Test Mode.
        Returns:
            (selected_key: Optional[KeyDef], is_inside_hitbox: bool, hitbox_rect: Optional[QRectF])
        """
        if pos.x() < 0 or pos.y() < 0:
            return None, False, None

        for k in self.keys:
            if k.rect.contains(pos):
                return k, True, k.rect

        nearest = self.get_key_at_point(pos)
        if nearest:
            return nearest, False, nearest.rect
        return None, False, None

    @staticmethod
    def _check_index_extension(hand: Any) -> Tuple[bool, float]:
        """
        Calculates rotation-invariant, distance-invariant index finger extension.
        Evaluates joint vector angle (cos theta), MCP-to-TIP reach ratio, and wrist distance.
        Supports any hand tilt, rotation, and camera distance without depending on screen height.
        Returns: (is_extended: bool, confidence_score: float)
        """
        if hasattr(hand, "_is_finger_extended") and hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 8:
            try:
                res = hand._is_finger_extended(5, 6, 8)
                if isinstance(res, (tuple, list)) and len(res) == 2:
                    return bool(res[0]), float(res[1])
                elif isinstance(res, bool):
                    return res, 1.0 if res else 0.0
            except Exception:
                pass

        if hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) >= 9:
            lms = hand.landmarks_norm
            wrist = lms[0]
            mcp = lms[5]
            pip = lms[6]
            tip = lms[8]

            d_mcp_pip = math.hypot(pip[0] - mcp[0], pip[1] - mcp[1])
            if d_mcp_pip < 1e-4:
                # Unpopulated or mock intermediate joints: assume extended
                return getattr(hand, "is_index_extended", True), 1.0

            # Vector (PIP - MCP) and (TIP - PIP)
            u = (pip[0] - mcp[0], pip[1] - mcp[1])
            v = (tip[0] - pip[0], tip[1] - pip[1])
            u_len = math.hypot(u[0], u[1])
            v_len = math.hypot(v[0], v[1])
            cos_angle = 1.0 if (u_len < 1e-4 or v_len < 1e-4) else max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (u_len * v_len)))

            d_mcp_tip = math.hypot(tip[0] - mcp[0], tip[1] - mcp[1])
            d_w_tip = math.hypot(tip[0] - wrist[0], tip[1] - wrist[1])
            d_w_pip = math.hypot(pip[0] - wrist[0], pip[1] - wrist[1])

            straight = cos_angle > 0.20
            reached = (d_mcp_tip > d_mcp_pip * 1.20) if d_mcp_pip > 1e-4 else (d_w_tip > d_w_pip * 1.05)
            wrist_ext = d_w_tip > d_w_pip * 1.05

            is_ext = wrist_ext and (reached or straight)
            score = max(0.0, min(1.0, 0.5 * max(0.0, cos_angle) + 0.5 * min(1.0, d_mcp_tip / max(0.01, d_mcp_pip * 2.0))))
            return is_ext, score

        if hasattr(hand, "fingers_extended"):
            is_ext = hand.fingers_extended.get("index", True)
            score = 1.0 if is_ext else 0.0
            if hasattr(hand, "finger_scores"):
                score = hand.finger_scores.get("index", score)
            return is_ext, score

        if hasattr(hand, "index_state"):
            is_ext = (hand.index_state == "EXTENDED")
            return is_ext, 1.0 if is_ext else 0.0

        return getattr(hand, "is_index_extended", True), 1.0

    # -----------------------------------------------------------------
    # Two-Hand Air Typing Optical Input Engine
    # -----------------------------------------------------------------
    def process_multi_hands(self, hands: List[Any], timestamp: Optional[float] = None) -> None:
        """
        Primary Air Typing Engine: Tracks all 10 individual fingertips,
        separates left and right hands independently, evaluates calibrated forward-press
        and pinch metrics, applies strict 5-stage hysteresis state machine,
        and triggers keystrokes safely.
        """
        if self.keyboard_paused:
            self._reset_all_finger_visuals()
            return

        now = timestamp if timestamp is not None else time.time()
        num_hands = len(hands)

        if num_hands == 0:
            self.tracking_freshness_status = "TRACKING_LOST (AWAITING HANDS)"
            self.left_hand_present = False
            self.right_hand_present = False
            self.left_detected = False
            self.right_detected = False
            self.left_tracking_conf = 0.0
            self.right_tracking_conf = 0.0
            self.left_handedness_conf = 0.0
            self.right_handedness_conf = 0.0
            self.left_hovered_key = "NONE"
            self.right_hovered_key = "NONE"
            self.left_press_state = "IDLE"
            self.right_press_state = "IDLE"
            self.left_index_coords = (-100, -100)
            self.right_index_coords = (-100, -100)
            self.left_index_hitbox = None
            self.right_index_hitbox = None
            self.left_index_inside = False
            self.right_index_inside = False
            self.is_hand_present = False
            self.pointer_visible = False
            self.keyboard_service.release_all_held_keys()
            self._reset_all_finger_visuals()
            self.last_hovered_key_id = None
            self.hover_start_time = 0.0
            self.dwell_progress = 0.0
            self.dwell_locked_key_id = None
            self.dwell_anchor_pos = None
            return

        # Frame freshness calculation
        first_hand = hands[0]
        hand_conf = getattr(first_hand, "confidence", 1.0)
        frame_timestamp = getattr(first_hand, "frame_timestamp", now)
        frame_id = getattr(first_hand, "frame_id", 0)
        self.last_frame_timestamp = frame_timestamp
        self.last_frame_id = frame_id
        self.last_frame_age_ms = max(0.0, (now - frame_timestamp) * 1000.0)
        self.sensor_frame_width = getattr(first_hand, "frame_width", 640)
        self.sensor_frame_height = getattr(first_hand, "frame_height", 480)

        if self.last_frame_age_ms > 400.0 or hand_conf < 0.45:
            self.tracking_freshness_status = f"LOW CONFIDENCE / STALE ({self.last_frame_age_ms:.0f}ms, {hand_conf:.2f})"
            self.dwell_progress = 0.0
            self.last_hovered_key_id = None
            self.dwell_locked_key_id = None
            self.dwell_anchor_pos = None
            if hand_conf < 0.45:
                return
        else:
            self.tracking_freshness_status = f"LIVE FEED (Frame #{frame_id}, {self.last_frame_age_ms:.1f}ms)"

        self.is_hand_present = True
        self.pointer_visible = True
        w = float(self.width())
        h = float(self.height())

        left_hand = None
        right_hand = None

        if num_hands >= 2:
            # Determine hand identity using handedness when reliable, but do not depend on handedness alone
            h0 = hands[0]
            h1 = hands[1]
            h0_label = getattr(h0, "handedness", "Unknown")
            h1_label = getattr(h1, "handedness", "Unknown")
            h0_conf = getattr(h0, "handedness_confidence", 0.5)
            h1_conf = getattr(h1, "handedness_confidence", 0.5)

            if h0_label != h1_label and h0_label in ("Left", "Right") and h1_label in ("Left", "Right") and h0_conf >= 0.70 and h1_conf >= 0.70:
                if h0_label == "Left":
                    left_hand = h0
                    right_hand = h1
                else:
                    left_hand = h1
                    right_hand = h0
            else:
                # Spatial assignment by wrist X: in mirrored space, lower X is screen-left, higher X is screen-right
                sorted_hands = sorted(hands[:2], key=lambda hd: hd.get_tracking_point("wrist")[0] if hasattr(hd, "get_tracking_point") else getattr(hd, "x", 0.5))
                left_hand = sorted_hands[0]
                right_hand = sorted_hands[1]

            self.left_detected = True
            self.right_detected = True
            self.left_tracking_conf = getattr(left_hand, "confidence", 0.95)
            self.right_tracking_conf = getattr(right_hand, "confidence", 0.95)
            self.left_handedness_conf = getattr(left_hand, "handedness_confidence", 0.95)
            self.right_handedness_conf = getattr(right_hand, "handedness_confidence", 0.95)
        else:
            single = hands[0]
            wrist_x = single.get_tracking_point("wrist")[0] if hasattr(single, "get_tracking_point") else getattr(single, "x", 0.5)
            h_label = getattr(single, "handedness", "Right")  # Physical handedness from mirror correction
            h_conf = getattr(single, "handedness_confidence", 0.95)

            # Assign based on physical handedness and spatial side
            if h_label == "Left" or (wrist_x < 0.45 and h_conf < 0.70):
                left_hand = single
                right_hand = None
                self.left_detected = True
                self.right_detected = False
                self.left_tracking_conf = getattr(single, "confidence", 0.95)
                self.right_tracking_conf = 0.0
                self.left_handedness_conf = h_conf
                self.right_handedness_conf = 0.0
            else:
                right_hand = single
                left_hand = None
                self.right_detected = True
                self.left_detected = False
                self.right_tracking_conf = getattr(single, "confidence", 0.95)
                self.left_tracking_conf = 0.0
                self.right_handedness_conf = h_conf
                self.left_handedness_conf = 0.0

        # Set stabilization grace on first detection to avoid instant press on appearance
        was_any_absent = not self.left_hand_present and not self.right_hand_present
        self.left_hand_present = (left_hand is not None)
        self.right_hand_present = (right_hand is not None)
        if was_any_absent and (self.left_hand_present or self.right_hand_present) and self.hand_neutral_stabilization_duration > 0:
            self.hand_neutral_stabilization_until = now + self.hand_neutral_stabilization_duration

        # Clear hovered finger lists on all keys
        for k in self.keys:
            k.is_hovered = False
            k.hover_fingers.clear()

        # Calibration sampling if active
        if self.calibration_active:
            self._sample_calibration_frame(left_hand, right_hand, now)

        # Process hands according to One-Hand Test Mode vs Dual-Hand Mode
        if self.one_hand_test_mode:
            # One-Hand Test Mode: Only the active typing hand (default Right) controls the keyboard.
            if self.active_typing_hand == "RIGHT":
                active_hand = right_hand
                if active_hand:
                    self._process_single_hand_fingers(active_hand, "R", now=now, w=w, h=h)
                else:
                    self._idle_hand_fingers("R", was_detected=(right_hand is not None))
                self._idle_hand_fingers("L", was_detected=(left_hand is not None))
            else:  # "LEFT"
                active_hand = left_hand
                if active_hand:
                    self._process_single_hand_fingers(active_hand, "L", now=now, w=w, h=h)
                else:
                    self._idle_hand_fingers("L", was_detected=(left_hand is not None))
                self._idle_hand_fingers("R", was_detected=(right_hand is not None))
        else:
            # Dual-Hand Mode: Both hands processed independently
            if left_hand:
                self._process_single_hand_fingers(left_hand, "L", now=now, w=w, h=h)
            else:
                self._idle_hand_fingers("L")

            if right_hand:
                self._process_single_hand_fingers(right_hand, "R", now=now, w=w, h=h)
            else:
                self._idle_hand_fingers("R")

        # Update legacy hovered_key and aggregate dwell properties
        any_hovered = [k for k in self.keys if k.is_hovered]
        self.hovered_key = any_hovered[0] if any_hovered else None

        l_idx = self.fingers.get("L_INDEX")
        r_idx = self.fingers.get("R_INDEX")
        self.dwell_progress = max(l_idx.dwell_progress if l_idx else 0.0, r_idx.dwell_progress if r_idx else 0.0)
        self.dwell_locked_key_id = (l_idx.dwell_locked_key_id if l_idx and l_idx.dwell_locked_key_id else None) or \
                                   (r_idx.dwell_locked_key_id if r_idx and r_idx.dwell_locked_key_id else None)
        self.last_hovered_key_id = (r_idx.last_hovered_key_id if r_idx and r_idx.last_hovered_key_id else None) or \
                                   (l_idx.last_hovered_key_id if l_idx and l_idx.last_hovered_key_id else None)
        self.dwell_anchor_pos = (r_idx.dwell_anchor_pos if r_idx and r_idx.dwell_anchor_pos else None) or \
                                (l_idx.dwell_anchor_pos if l_idx and l_idx.dwell_anchor_pos else None)
        self.hover_start_time = (r_idx.hover_start_time if r_idx and r_idx.hover_start_time else 0.0) or \
                                (l_idx.hover_start_time if l_idx and l_idx.hover_start_time else 0.0)

    def _idle_hand_fingers(self, side_prefix: str, was_detected: bool = False) -> None:
        """Safely transitions all 5 fingers of an idled hand to IDLE state."""
        for fname in ("thumb", "index", "middle", "ring", "pinky"):
            fid = f"{side_prefix}_{fname.upper()}"
            f = self.fingers[fid]
            f.visible = False
            f.state = FingerPressState.IDLE
            f.is_pressed = False
            f.press_locked = False
            f.locked_key_id = None
            f.candidate_start_time = None
            f.hover_start_time = 0.0
            f.dwell_progress = 0.0
            f.dwell_locked_key_id = None
            f.dwell_anchor_pos = None
            f.last_hovered_key_id = None
            f.is_extended = False
            f.last_rejection_reason = "IDLE (1-HAND_MODE_SUPPRESSED)" if was_detected else "IDLE (HAND_ABSENT)"
        if side_prefix == "L":
            self.left_hovered_key = "NONE"
            self.left_press_state = "IDLE"
            self.left_detected = was_detected
            self.left_index_coords = (-100, -100)
            self.left_index_hitbox = None
            self.left_index_inside = False
            self.left_index_extended = False
        else:
            self.right_hovered_key = "NONE"
            self.right_press_state = "IDLE"
            self.right_detected = was_detected
            self.right_index_coords = (-100, -100)
            self.right_index_hitbox = None
            self.right_index_inside = False
            self.right_index_extended = False

    def _process_single_hand_fingers(self, hand: Any, side_prefix: str, now: float, w: float, h: float) -> None:
        """Processes fingers for one hand using 1:1 unified coordinate mapping and state machine."""
        finger_names = ("thumb", "index", "middle", "ring", "pinky")
        active_candidates: List[Tuple[float, FingerAirState, KeyDef, str]] = []

        # Robust scale-invariant pinch distance extraction
        norm_pinch = 1.0
        if hasattr(hand, "norm_pinch_distance"):
            norm_pinch = hand.norm_pinch_distance
        elif hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 8:
            t = hand.landmarks_norm[4]
            i = hand.landmarks_norm[8]
            w_pt = hand.landmarks_norm[0] if len(hand.landmarks_norm) > 0 else (0.5, 0.5)
            m_pt = hand.landmarks_norm[9] if len(hand.landmarks_norm) > 9 else (0.5, 0.5)
            palm_scale = max(0.04, math.hypot(w_pt[0] - m_pt[0], w_pt[1] - m_pt[1]))
            norm_pinch = math.hypot(t[0] - i[0], t[1] - i[1]) / palm_scale
        else:
            norm_pinch = getattr(hand, "pinch_distance", 1.0)
        self.current_pinch_dist = norm_pinch

        # Index fingertip position & hitbox telemetry for HUD
        itip_x, itip_y = 0.5, 0.5
        if hasattr(hand, "get_finger_tip"):
            itip_x, itip_y, _ = hand.get_finger_tip("index")
        elif hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 8:
            itip_x, itip_y, _ = hand.landmarks_norm[8]
        elif hasattr(hand, "get_tracking_point"):
            itip_x, itip_y = hand.get_tracking_point("index_tip")
        else:
            itip_x, itip_y = getattr(hand, "x", 0.5), getattr(hand, "y", 0.5)

        icx, icy, is_in_roi = self.map_camera_to_keyboard(itip_x, itip_y)
        itest_key, is_inside, hitbox = self.test_key_hitbox(QPointF(icx, icy))

        # Check rotation-invariant index finger extension
        is_ext, ext_score = self._check_index_extension(hand)
        idx_fid = f"{side_prefix}_INDEX"
        idx_fstate = self.fingers[idx_fid]
        idx_fstate.is_extended = is_ext
        idx_fstate.extension_score = ext_score

        if side_prefix == "L":
            self.left_index_coords = (int(icx), int(icy))
            self.left_index_norm = (round(itip_x, 3), round(itip_y, 3))
            self.left_index_hitbox = hitbox
            self.left_index_inside = is_inside
            self.left_hovered_key = itest_key.label if (itest_key and is_ext) else "NONE"
            self.left_index_extended = is_ext
            self.left_extension_score = ext_score
        else:
            self.right_index_coords = (int(icx), int(icy))
            self.right_index_norm = (round(itip_x, 3), round(itip_y, 3))
            self.right_index_hitbox = hitbox
            self.right_index_inside = is_inside
            self.right_hovered_key = itest_key.label if (itest_key and is_ext) else "NONE"
            self.right_index_extended = is_ext
            self.right_extension_score = ext_score

        if not is_ext:
            # Finger is folded/curled: suppress key hover, selection, and dwell
            idx_fstate.state = FingerPressState.IDLE
            idx_fstate.is_pressed = False
            idx_fstate.press_locked = False
            idx_fstate.dwell_progress = 0.0
            idx_fstate.dwell_locked_key_id = None
            idx_fstate.hover_start_time = 0.0
            idx_fstate.last_hovered_key_id = None
            idx_fstate.last_rejection_reason = f"INDEX FOLDED (Score:{ext_score:.2f})"
            if side_prefix == "L":
                self.left_press_state = "IDLE"
                self.left_rejection_reason = idx_fstate.last_rejection_reason
            else:
                self.right_press_state = "IDLE"
                self.right_rejection_reason = idx_fstate.last_rejection_reason
            return

        # -----------------------------------------------------------------
        # AIR TYPING GESTURE ENGINE (DWELL hands-free default, PINCH optional)
        # -----------------------------------------------------------------
        if self.press_detection_mode in ("DWELL", "PINCH", "HYBRID"):
            smooth_px, smooth_py = idx_fstate.filter_point.filter(icx, icy, now)
            current_screen_pos = QPointF(smooth_px, smooth_py)
            idx_fstate.screen_pos = current_screen_pos
            idx_fstate.norm_pos = (itip_x, itip_y)
            idx_fstate.visible = True
            idx_fstate.norm_pinch = norm_pinch

            # Calculate raw and calibrated depth for forward tap compatibility
            if hasattr(hand, "get_raw_finger_metric"):
                raw_metric = hand.get_raw_finger_metric("index")
            elif hasattr(hand, "calculate_finger_press_metric"):
                raw_metric = hand.calculate_finger_press_metric("index")
            else:
                raw_metric = max(0.0, 1.0 - norm_pinch)
            calibrated_depth = max(0.0, raw_metric - idx_fstate.baseline_depth)
            idx_fstate.press_depth = calibrated_depth

            # Check for fast lateral swipe
            is_fast_lateral = False
            if idx_fstate.prev_canvas_pos:
                prev_x, prev_y = idx_fstate.prev_canvas_pos
                lat_dist = math.hypot(smooth_px - prev_x, smooth_py - prev_y)
                if lat_dist > 80.0:
                    is_fast_lateral = True
            idx_fstate.prev_canvas_pos = (smooth_px, smooth_py)

            # Hit-test key under index fingertip
            hovered_key = self.get_key_at_point(current_screen_pos)
            idx_fstate.hovered_key_id = hovered_key.key_id if hovered_key else None

            # Map remaining 4 fingers for visual HUD tracking
            for fname in ("thumb", "middle", "ring", "pinky"):
                fid = f"{side_prefix}_{fname.upper()}"
                fstate = self.fingers[fid]
                if hasattr(hand, "get_finger_tip"):
                    tx, ty, _ = hand.get_finger_tip(fname)
                elif hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 20:
                    idx_map = {"thumb": 4, "middle": 12, "ring": 16, "pinky": 20}
                    tx, ty, _ = hand.landmarks_norm[idx_map[fname]]
                else:
                    tx, ty = getattr(hand, "x", 0.5), getattr(hand, "y", 0.5)
                px, py, _ = self.map_camera_to_keyboard(tx, ty)
                spx, spy = fstate.filter_point.filter(px, py, now)
                fstate.screen_pos = QPointF(spx, spy)
                fstate.norm_pos = (tx, ty)
                fstate.visible = True
                fstate.norm_pinch = norm_pinch
                fstate.state = FingerPressState.IDLE
                fstate.is_pressed = False

            # =============================================================
            # MODE A: DWELL-TO-TYPE (HANDS-FREE HOVER POINTING - DEFAULT)
            # =============================================================
            if self.press_detection_mode == "DWELL":
                idx_fstate.trigger_method = "DWELL"
                if hovered_key:
                    hovered_key.is_hovered = True
                    hovered_key.hover_fingers.append(idx_fid)

                    if self.key_selection_test_mode:
                        idx_fstate.state = FingerPressState.IDLE
                        idx_fstate.is_pressed = False
                        idx_fstate.last_rejection_reason = "KEY_SELECTION_TEST_MODE (HOVER ONLY)"
                    elif hovered_key.key_id != idx_fstate.last_hovered_key_id:
                        # Arrived at a NEW key for this hand: start fresh dwell timer and clear lock
                        idx_fstate.last_hovered_key_id = hovered_key.key_id
                        idx_fstate.hover_start_time = now
                        idx_fstate.dwell_progress = 0.0
                        idx_fstate.dwell_locked_key_id = None
                        idx_fstate.dwell_anchor_pos = current_screen_pos
                        idx_fstate.state = FingerPressState.HOVER
                        idx_fstate.is_pressed = False
                        idx_fstate.press_locked = False
                        idx_fstate.last_rejection_reason = f"DWELL_START ('{hovered_key.label}')"
                    else:
                        # Remaining on the SAME key
                        if idx_fstate.dwell_locked_key_id == hovered_key.key_id:
                            # Already triggered once! Require leaving key before re-arm.
                            idx_fstate.dwell_progress = 1.0
                            idx_fstate.state = FingerPressState.WAIT_FOR_RELEASE
                            idx_fstate.is_pressed = False
                            idx_fstate.last_rejection_reason = "LOCKED (LEAVE KEY TO RE-ARM)"
                        else:
                            # Natural hand tremor / jitter tolerance:
                            if idx_fstate.dwell_anchor_pos:
                                dist = math.hypot(smooth_px - idx_fstate.dwell_anchor_pos.x(),
                                                  smooth_py - idx_fstate.dwell_anchor_pos.y())
                                if dist > self.dwell_jitter_tolerance:
                                    idx_fstate.dwell_anchor_pos = current_screen_pos

                            dwell_elapsed = now - idx_fstate.hover_start_time
                            if self.hover_dwell_time > 0:
                                idx_fstate.dwell_progress = min(1.0, dwell_elapsed / self.hover_dwell_time)
                            else:
                                idx_fstate.dwell_progress = 1.0

                            # Forward tap depth also immediately satisfies activation without waiting
                            is_forward_tap = (calibrated_depth >= self.press_threshold)
                            is_dwell_done = (idx_fstate.dwell_progress >= 1.0)

                            if is_dwell_done or is_forward_tap:
                                # Duplicate keypress check across both hands
                                other_fid = "R_INDEX" if side_prefix == "L" else "L_INDEX"
                                other_fstate = self.fingers.get(other_fid)
                                other_locked = (other_fstate and other_fstate.dwell_locked_key_id == hovered_key.key_id)
                                other_recently_fired = (other_fstate and (now - other_fstate.last_press_time) < 0.35 and other_fstate.locked_key_id == hovered_key.key_id)

                                if other_locked or other_recently_fired:
                                    # Suppress duplicate keypress!
                                    idx_fstate.state = FingerPressState.WAIT_FOR_RELEASE
                                    idx_fstate.dwell_locked_key_id = hovered_key.key_id
                                    idx_fstate.is_pressed = False
                                    idx_fstate.last_rejection_reason = "SUPPRESSED (DUPLICATE KEY - OTHER HAND ACTIVE)"
                                elif (now - idx_fstate.last_press_time) < self.keypress_cooldown:
                                    idx_fstate.state = FingerPressState.PINCH_CANDIDATE
                                    idx_fstate.last_rejection_reason = "REJECTED (COOLDOWN)"
                                elif self.key_selection_test_mode:
                                    idx_fstate.state = FingerPressState.IDLE
                                    idx_fstate.last_rejection_reason = "KEY_SELECTION_TEST_MODE (HOVER ONLY)"
                                else:
                                    # Trigger exactly once!
                                    idx_fstate.state = FingerPressState.PRESSED
                                    idx_fstate.is_pressed = True
                                    idx_fstate.press_locked = True
                                    idx_fstate.locked_key_id = hovered_key.key_id
                                    idx_fstate.dwell_locked_key_id = hovered_key.key_id  # Lock until key exit!
                                    idx_fstate.last_press_time = now
                                    trig_label = "DWELL" if is_dwell_done else "FORWARD_TAP"
                                    idx_fstate.last_rejection_reason = f"ACCEPTED ({trig_label} {self.hover_dwell_time:.2f}s)"
                                    self.handle_virtual_key(hovered_key.key_id, finger_id=idx_fid, trigger_method=trig_label)
                            else:
                                idx_fstate.state = FingerPressState.HOVER
                                idx_fstate.is_pressed = False
                                idx_fstate.last_rejection_reason = f"DWELLING ({idx_fstate.dwell_progress * 100:.0f}%)"
                else:
                    # Finger left key or outside keybounds: immediately reset dwell timer and lock for this finger
                    idx_fstate.last_hovered_key_id = None
                    idx_fstate.hover_start_time = 0.0
                    idx_fstate.dwell_progress = 0.0
                    idx_fstate.dwell_locked_key_id = None
                    idx_fstate.dwell_anchor_pos = None
                    idx_fstate.state = FingerPressState.HOVER
                    idx_fstate.is_pressed = False
                    idx_fstate.press_locked = False
                    idx_fstate.last_rejection_reason = "NO_KEY (HOVER)"

            # =============================================================
            # MODE B: PINCH-TO-TYPE (DELIBERATE THUMB-INDEX PINCH)
            # =============================================================
            elif self.press_detection_mode == "PINCH":
                idx_fstate.trigger_method = "PINCH"
                self.dwell_progress = 0.0
                if hovered_key:
                    hovered_key.is_hovered = True
                    hovered_key.hover_fingers.append(idx_fid)

                if idx_fstate.press_locked:
                    if norm_pinch >= self.pinch_release_threshold:
                        idx_fstate.press_locked = False
                        idx_fstate.is_pressed = False
                        idx_fstate.state = FingerPressState.HOVER
                        self.pinch_typing_state = FingerPressState.HOVER
                        idx_fstate.locked_key_id = None
                        idx_fstate.last_rejection_reason = "RE-ARMED (RELEASED)"
                    else:
                        idx_fstate.state = FingerPressState.WAIT_FOR_RELEASE
                        self.pinch_typing_state = FingerPressState.WAIT_FOR_RELEASE
                        idx_fstate.is_pressed = False
                        idx_fstate.last_rejection_reason = f"WAIT_FOR_RELEASE (Pinch:{norm_pinch:.2f} < {self.pinch_release_threshold:.2f})"
                else:
                    if self.key_selection_test_mode:
                        idx_fstate.state = FingerPressState.IDLE
                        self.pinch_typing_state = FingerPressState.HOVER
                        idx_fstate.last_rejection_reason = "KEY_SELECTION_TEST_MODE (HOVER ONLY)"
                    elif norm_pinch <= self.pinch_threshold:
                        if hovered_key is None:
                            idx_fstate.state = FingerPressState.PINCH_CANDIDATE
                            self.pinch_typing_state = FingerPressState.PINCH_CANDIDATE
                            idx_fstate.last_rejection_reason = "REJECTED (NO_KEY_UNDER_FINGERTIP)"
                        elif is_fast_lateral:
                            idx_fstate.state = FingerPressState.PINCH_CANDIDATE
                            self.pinch_typing_state = FingerPressState.PINCH_CANDIDATE
                            idx_fstate.last_rejection_reason = "REJECTED (LATERAL_SWIPE)"
                        elif (now - idx_fstate.last_press_time) < self.keypress_cooldown:
                            idx_fstate.state = FingerPressState.PINCH_CANDIDATE
                            self.pinch_typing_state = FingerPressState.PINCH_CANDIDATE
                            idx_fstate.last_rejection_reason = "REJECTED (COOLDOWN)"
                        else:
                            idx_fstate.state = FingerPressState.PRESSED
                            self.pinch_typing_state = FingerPressState.PRESSED
                            idx_fstate.is_pressed = True
                            idx_fstate.press_locked = True
                            idx_fstate.locked_key_id = hovered_key.key_id
                            idx_fstate.last_press_time = now
                            idx_fstate.last_rejection_reason = "ACCEPTED (PINCH)"
                            self.handle_virtual_key(hovered_key.key_id, finger_id=idx_fid, trigger_method="PINCH")
                    elif norm_pinch <= self.pinch_candidate_threshold:
                        idx_fstate.state = FingerPressState.PINCH_CANDIDATE
                        self.pinch_typing_state = FingerPressState.PINCH_CANDIDATE
                        idx_fstate.last_rejection_reason = f"PINCH_CANDIDATE ({norm_pinch:.2f})"
                    else:
                        idx_fstate.state = FingerPressState.HOVER
                        self.pinch_typing_state = FingerPressState.HOVER
                        idx_fstate.last_rejection_reason = f"HOVER ({norm_pinch:.2f})"

            # =============================================================
            # MODE C: HYBRID (BOTH DWELL & PINCH ACTIVE)
            # =============================================================
            else:
                idx_fstate.trigger_method = "HYBRID"
                if hovered_key:
                    hovered_key.is_hovered = True
                    hovered_key.hover_fingers.append(idx_fid)

                    if hovered_key.key_id != idx_fstate.last_hovered_key_id:
                        idx_fstate.last_hovered_key_id = hovered_key.key_id
                        idx_fstate.hover_start_time = now
                        idx_fstate.dwell_progress = 0.0
                        idx_fstate.dwell_locked_key_id = None
                        idx_fstate.dwell_anchor_pos = current_screen_pos
                        idx_fstate.state = FingerPressState.HOVER

                        self.last_hovered_key_id = hovered_key.key_id
                        self.hover_start_time = now
                        self.dwell_progress = 0.0
                        self.dwell_locked_key_id = None
                        self.dwell_anchor_pos = current_screen_pos
                    else:
                        dwell_elapsed = now - idx_fstate.hover_start_time
                        if self.hover_dwell_time > 0:
                            idx_fstate.dwell_progress = min(1.0, dwell_elapsed / self.hover_dwell_time)
                        else:
                            idx_fstate.dwell_progress = 1.0
                        self.dwell_progress = idx_fstate.dwell_progress

                    is_pinch = (norm_pinch <= self.pinch_threshold)
                    is_dwell = (idx_fstate.dwell_progress >= 1.0)
                    is_tap = (calibrated_depth >= self.press_threshold)

                    if idx_fstate.press_locked:
                        if norm_pinch >= self.pinch_release_threshold and not is_tap:
                            idx_fstate.press_locked = False
                            idx_fstate.is_pressed = False
                            idx_fstate.state = FingerPressState.HOVER
                    elif (is_pinch or is_dwell or is_tap) and idx_fstate.dwell_locked_key_id != hovered_key.key_id:
                        if (now - idx_fstate.last_press_time) >= self.keypress_cooldown and not self.key_selection_test_mode:
                            idx_fstate.state = FingerPressState.PRESSED
                            idx_fstate.is_pressed = True
                            idx_fstate.press_locked = True
                            idx_fstate.locked_key_id = hovered_key.key_id
                            idx_fstate.dwell_locked_key_id = hovered_key.key_id
                            self.dwell_locked_key_id = hovered_key.key_id
                            idx_fstate.last_press_time = now
                            trig_m = "PINCH" if is_pinch else ("DWELL" if is_dwell else "FORWARD_TAP")
                            idx_fstate.last_rejection_reason = f"ACCEPTED ({trig_m})"
                            self.handle_virtual_key(hovered_key.key_id, finger_id=idx_fid, trigger_method=trig_m)
                else:
                    idx_fstate.last_hovered_key_id = None
                    idx_fstate.hover_start_time = 0.0
                    idx_fstate.dwell_progress = 0.0
                    idx_fstate.dwell_locked_key_id = None
                    idx_fstate.dwell_anchor_pos = None

                    self.last_hovered_key_id = None
                    self.hover_start_time = 0.0
                    self.dwell_progress = 0.0
                    self.dwell_locked_key_id = None
                    self.dwell_anchor_pos = None

            if side_prefix == "L":
                self.left_press_state = idx_fstate.state.value
                self.left_rejection_reason = idx_fstate.last_rejection_reason
            else:
                self.right_press_state = idx_fstate.state.value
                self.right_rejection_reason = idx_fstate.last_rejection_reason
            return

        for fname in finger_names:
            fid = f"{side_prefix}_{fname.upper()}"
            fstate = self.fingers[fid]

            # 1. Unified 1:1 coordinate extraction without split-mode warping
            if hasattr(hand, "get_finger_tip"):
                tip_x, tip_y, tip_z = hand.get_finger_tip(fname)
            elif hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 20:
                idx_map = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
                tip_x, tip_y, tip_z = hand.landmarks_norm[idx_map[fname]]
            else:
                tip_x, tip_y = getattr(hand, "x", 0.5), getattr(hand, "y", 0.5)
                tip_z = 0.0

            raw_px, raw_py, in_roi = self.map_camera_to_keyboard(tip_x, tip_y)
            smooth_px, smooth_py = fstate.filter_point.filter(raw_px, raw_py, now)

            fstate.screen_pos = QPointF(smooth_px, smooth_py)
            fstate.norm_pos = (tip_x, tip_y)
            fstate.visible = True
            fstate.norm_pinch = norm_pinch

            # 2. Raw & Calibrated Depth Calculation
            if hasattr(hand, "get_raw_finger_metric"):
                raw_metric = hand.get_raw_finger_metric(fname)
            elif hasattr(hand, "calculate_finger_press_metric"):
                raw_metric = hand.calculate_finger_press_metric(fname)
            else:
                raw_metric = max(0.0, 1.0 - norm_pinch)

            fstate.raw_depth = raw_metric
            calibrated_depth = max(0.0, raw_metric - fstate.baseline_depth)
            fstate.calibrated_depth = calibrated_depth
            fstate.press_depth = calibrated_depth

            # Velocity & lateral speed calculation to reject fast sideways swipes
            dt = max(0.001, now - (fstate.last_press_time or now))
            fstate.prev_z = tip_z

            is_fast_lateral = False
            if fstate.prev_canvas_pos:
                prev_x, prev_y = fstate.prev_canvas_pos
                lat_dist = math.hypot(smooth_px - prev_x, smooth_py - prev_y)
                if lat_dist > 45.0:
                    is_fast_lateral = True
            fstate.prev_canvas_pos = (smooth_px, smooth_py)

            # Hit-test key
            hovered_key = self.get_key_at_point(fstate.screen_pos)
            fstate.hovered_key_id = hovered_key.key_id if hovered_key else None
            if hovered_key:
                hovered_key.is_hovered = True
                hovered_key.hover_fingers.append(fid)

            # Dual-mode Press Trigger Logic (Forward Tap or Pinch Fallback)
            is_forward_press = (calibrated_depth >= self.press_threshold)
            is_pinch_press = (fname in ("index", "thumb") and norm_pinch <= self.pinch_to_press_threshold)

            if self.press_detection_mode == "FORWARD_TAP":
                trigger_pressed = is_forward_press
                trigger_method = "FORWARD_TAP"
            elif self.press_detection_mode == "PINCH":
                trigger_pressed = is_pinch_press
                trigger_method = "PINCH"
            else:  # "HYBRID" (default)
                trigger_pressed = is_forward_press or is_pinch_press
                trigger_method = "PINCH" if is_pinch_press else "FORWARD_TAP"

            # Withdrawal check for releasing hysteresis lock based on trigger method
            if fstate.trigger_method == "PINCH":
                is_withdrawn = (norm_pinch >= self.pinch_to_release_threshold)
            else:
                is_withdrawn = (calibrated_depth <= self.release_threshold)

            # -------------------------------------------------------------
            # 5-STAGE INDEPENDENT FINGER HYSTERESIS STATE MACHINE
            # IDLE -> CANDIDATE -> PRESSED -> RELEASE_WAIT -> IDLE
            # -------------------------------------------------------------
            if fstate.press_locked:
                if is_withdrawn:
                    # Successfully withdrawn below release threshold: RE-ARM!
                    fstate.press_locked = False
                    fstate.is_pressed = False
                    fstate.state = FingerPressState.IDLE
                    fstate.locked_key_id = None
                    fstate.candidate_start_time = None
                    fstate.last_rejection_reason = "RE-ARMED (WITHDRAWN)"
                else:
                    # Finger remains forward: lock against duplicate keystrokes!
                    fstate.state = FingerPressState.RELEASE_WAIT
                    fstate.is_pressed = False
                    fstate.last_rejection_reason = f"RELEASE_WAIT (Depth:{calibrated_depth:.2f} > {self.release_threshold:.2f})"
            else:
                if self.key_selection_test_mode:
                    # In Key Selection Test Mode: Hovering and selection only; typing strictly suppressed!
                    fstate.state = FingerPressState.IDLE
                    fstate.last_rejection_reason = "KEY_SELECTION_TEST_MODE (HOVER ONLY)"
                elif trigger_pressed:
                    if hovered_key is None:
                        fstate.state = FingerPressState.CANDIDATE
                        fstate.last_rejection_reason = "REJECTED (NO_KEY_UNDER_FINGERTIP)"
                    elif is_fast_lateral:
                        fstate.state = FingerPressState.CANDIDATE
                        fstate.last_rejection_reason = "REJECTED (LATERAL_SWIPE)"
                    elif now - fstate.last_press_time < self.keypress_cooldown:
                        fstate.state = FingerPressState.CANDIDATE
                        fstate.last_rejection_reason = "REJECTED (COOLDOWN)"
                    else:
                        fstate.state = FingerPressState.PRESSED
                        active_candidates.append((calibrated_depth if trigger_method == "FORWARD_TAP" else 0.5, fstate, hovered_key, trigger_method))
                elif calibrated_depth >= self.candidate_threshold or (fname == "index" and norm_pinch < 0.48):
                    fstate.state = FingerPressState.CANDIDATE
                    if fstate.candidate_start_time is None:
                        fstate.candidate_start_time = now
                    fstate.last_rejection_reason = f"CANDIDATE (Depth:{calibrated_depth:.2f} < {self.press_threshold:.2f})"
                else:
                    fstate.state = FingerPressState.IDLE
                    fstate.candidate_start_time = None
                    fstate.last_rejection_reason = "IDLE (RESTING)"

            # Update Hand telemetry for HUD
            if fname == "index":
                if side_prefix == "L":
                    self.left_press_state = fstate.state.value
                    self.left_rejection_reason = fstate.last_rejection_reason
                else:
                    self.right_press_state = fstate.state.value
                    self.right_rejection_reason = fstate.last_rejection_reason

        # Resolve primary striking finger for this hand
        if active_candidates:
            active_candidates.sort(key=lambda item: (item[0], 1 if item[1].finger_name == "index" else 0), reverse=True)
            dominant_depth, dominant_finger, dominant_key, trigger_method = active_candidates[0]

            dominant_finger.is_pressed = True
            dominant_finger.press_locked = True
            dominant_finger.locked_key_id = dominant_key.key_id
            dominant_finger.last_press_time = now
            dominant_finger.state = FingerPressState.PRESSED
            dominant_finger.last_rejection_reason = f"ACCEPTED ({trigger_method})"

            self.handle_virtual_key(dominant_key.key_id, finger_id=dominant_finger.finger_id, trigger_method=trigger_method)

    def start_neutral_calibration(self, duration: float = 1.0) -> None:
        """Starts 1.0-second neutral baseline sampling for all 10 fingers."""
        self.calibration_active = True
        self._calibration_active = True
        self.calibration_countdown = duration
        self.calibration_start_time = time.time()
        self.calibration_samples = {fid: [] for fid in self.fingers}
        self.mode_changed.emit("CALIBRATING NEUTRAL POSE... HOLD HANDS STEADY")
        logger.info("[KEYBOARD CALIBRATION] Neutral pose calibration started.")

    def _sample_calibration_frame(self, left_hand: Any, right_hand: Any, now: float) -> None:
        """Accumulates resting metrics during neutral calibration."""
        if left_hand and hasattr(left_hand, "get_raw_finger_metric"):
            for fname in ("thumb", "index", "middle", "ring", "pinky"):
                m = left_hand.get_raw_finger_metric(fname)
                self.calibration_samples[f"L_{fname.upper()}"].append(m)

        if right_hand and hasattr(right_hand, "get_raw_finger_metric"):
            for fname in ("thumb", "index", "middle", "ring", "pinky"):
                m = right_hand.get_raw_finger_metric(fname)
                self.calibration_samples[f"R_{fname.upper()}"].append(m)

        if now - self.calibration_start_time >= self.calibration_countdown:
            self.calibration_active = False
            self._calibration_active = False
            calibrated_count = 0
            for fid, samples in self.calibration_samples.items():
                if samples:
                    avg_base = sum(samples) / len(samples)
                    self.fingers[fid].baseline_depth = avg_base
                    calibrated_count += 1
            self.is_calibrated = (calibrated_count >= 5)
            self.mode_changed.emit("NEUTRAL CALIBRATION COMPLETE! BASELINES LOCKED.")
            logger.info(f"[KEYBOARD CALIBRATION] Neutral calibration finished ({calibrated_count} fingers updated).")

    def toggle_test_mode(self) -> bool:
        """Toggles TEST MODE on/off (dry run without sending actual Windows input)."""
        self.test_mode = not self.test_mode
        if self.test_mode:
            self.global_typing_enabled = False
            self.external_typing_enabled = False
        st = "ON (PREVIEW ONLY - NO OS INPUT)" if self.test_mode else "OFF (LIVE OS INPUT ARMED)"
        self.mode_changed.emit(f"TEST MODE: {st}")
        logger.warning(f"[KEYBOARD MODE] Test mode toggled: {st}")
        self.update()
        return self.test_mode

    def set_test_mode(self, enabled: bool) -> None:
        """Sets TEST MODE state."""
        self.test_mode = enabled
        if self.test_mode:
            self.global_typing_enabled = False
            self.external_typing_enabled = False
        self.update()

    def toggle_global_typing(self) -> bool:
        """Toggles sending live keystrokes to external Windows applications."""
        self.global_typing_enabled = not self.global_typing_enabled
        self.external_typing_enabled = self.global_typing_enabled
        if self.global_typing_enabled:
            self.test_mode = False
        status = "ARMED (GLOBAL WINDOWS)" if self.global_typing_enabled else "OFF (INTERNAL BUFFER ONLY)"
        self.mode_changed.emit(f"GLOBAL TYPING: {status}")
        logger.warning(f"[KEYBOARD SAFETY] Global typing mode toggled: {status}")
        self.update()
        return self.global_typing_enabled

    def set_global_typing(self, enabled: bool) -> None:
        """Sets Global Typing state."""
        self.global_typing_enabled = enabled
        self.external_typing_enabled = enabled
        if self.global_typing_enabled:
            self.test_mode = False
        self.update()

    def toggle_key_selection_test_mode(self) -> bool:
        """Toggles Key-Selection Diagnostic Test Mode (Phase 5)."""
        self.key_selection_test_mode = not self.key_selection_test_mode
        if self.key_selection_test_mode:
            self.test_mode = True
            self.global_typing_enabled = False
            self.mode_changed.emit("KEY-SELECTION TEST MODE: ON (HOVER ONLY - HITBOX DIAGNOSTICS)")
            logger.info("[KEYBOARD] Key-Selection Diagnostic Mode ON. Real keyboard output disabled.")
        else:
            self.mode_changed.emit("KEY-SELECTION TEST MODE: OFF")
            logger.info("[KEYBOARD] Key-Selection Diagnostic Mode OFF.")
        self.update()
        return self.key_selection_test_mode

    def set_key_selection_test_mode(self, enabled: bool) -> None:
        """Sets Key-Selection Diagnostic Test Mode state."""
        self.key_selection_test_mode = enabled
        if enabled:
            self.test_mode = True
            self.global_typing_enabled = False
        self.update()

    def send_test_key(self, char: str = "a") -> Tuple[bool, str]:
        """
        Sends one harmless test character through the actual Windows keyboard input service
        without stealing focus from the target application (e.g. Notepad).
        """
        self.keyboard_service.restore_target_window_focus()
        time.sleep(0.02)
        ok, msg = self.keyboard_service.send_char(char)
        target = self.keyboard_service.last_external_title or "External App"
        status_msg = f"TEST KEY '{char}' -> {target}: {'SUCCESS' if ok else 'FAILED (' + msg + ')'}"
        self.mode_changed.emit(status_msg)
        logger.info(f"[KEYBOARD TEST] {status_msg}")
        return ok, msg

    def toggle_one_hand_mode(self) -> bool:
        """Toggles between 1-Hand Test Mode (Right hand primary) and Dual-Hand Mode."""
        self.one_hand_test_mode = not self.one_hand_test_mode
        mode_str = f"1-HAND ({self.active_typing_hand})" if self.one_hand_test_mode else "2-HAND DUAL"
        self.mode_changed.emit(f"AIR TYPING MODE: {mode_str}")
        logger.info(f"[KEYBOARD] One-hand mode toggled: {mode_str}")
        self.update()
        return self.one_hand_test_mode

    def set_one_hand_mode(self, enabled: bool, hand_side: str = "RIGHT") -> None:
        """Configures One-Hand Test Mode explicitly."""
        self.one_hand_test_mode = enabled
        self.active_typing_hand = hand_side.upper()
        if self.one_hand_test_mode:
            if self.active_typing_hand == "RIGHT":
                self._idle_hand_fingers("L")
            else:
                self._idle_hand_fingers("R")
        self.update()

    def set_press_detection_mode(self, mode: str) -> None:
        """Sets the press detection engine mode: 'PINCH', 'FORWARD_TAP', or 'HYBRID'."""
        mode_up = mode.upper()
        if mode_up in ("PINCH", "FORWARD_TAP", "HYBRID"):
            self.press_detection_mode = mode_up
            self.mode_changed.emit(f"TRIGGER MODE: {self.press_detection_mode}")
            logger.info(f"[KEYBOARD] Trigger mode set to: {self.press_detection_mode}")
            self.update()

    def handle_virtual_key(self, key_id_or_action: str, finger_id: Optional[str] = None, trigger_method: str = "DIRECT") -> bool:
        """
        Authoritative central virtual key handler.
        Decoupled completely from animations and paint events.
        Directly executes text manipulations, modifiers, clipboard, and emits signals.
        """
        target_key: Optional[KeyDef] = None
        for k in self.keys:
            if k.key_id == key_id_or_action or k.action == key_id_or_action:
                target_key = k
                break

        if target_key is None:
            # Fallback for direct action string (e.g. "backspace", "space", "enter")
            target_key = KeyDef(
                key_id=key_id_or_action,
                label=key_id_or_action.upper(),
                shift_label=key_id_or_action.upper(),
                char=key_id_or_action if len(key_id_or_action) == 1 else "",
                shift_char=key_id_or_action.upper() if len(key_id_or_action) == 1 else "",
                action=key_id_or_action if len(key_id_or_action) > 1 else None
            )

        self._execute_key(target_key, finger_id=finger_id, trigger_method=trigger_method)
        self.total_keystrokes += 1
        self.last_typed_key_id = target_key.key_id
        self.last_typed_finger_id = finger_id or "DIRECT"
        self.last_typed_time = time.time()

        # Visual shockwave ripple animation
        ripple_center = target_key.rect.center() if target_key.rect.isValid() else QPointF(self.width() * 0.5, self.height() * 0.5)
        ripple = KeyRipple(
            center=ripple_center,
            current_r=6.0,
            max_r=50.0,
            alpha=255.0,
            color=QColor(0, 240, 255) if (finger_id and "L_" in finger_id) else QColor(50, 180, 255),
            speed=3.2
        )
        self._ripples.append(ripple)
        target_key.glow_intensity = 1.0
        self.key_triggered.emit(target_key.key_id)
        logger.info(f"[KEY HANDLER] Accepted key '{target_key.label}' via {self.last_typed_finger_id} [{trigger_method}]")
        return True

    def synthetic_press(self, key_id: str) -> bool:
        """Direct synthetic keypress for automated tests and diagnostic verification."""
        return self.handle_virtual_key(key_id, finger_id="SYNTHETIC")

    def _trigger_air_keypress(self, key: KeyDef, finger: FingerAirState) -> None:
        """Delegates to authoritative central virtual key handler."""
        self.handle_virtual_key(key.key_id, finger_id=finger.finger_id)

    def process_hand_frame(self, hand: Any, gesture_state: Any) -> None:
        """
        Single-hand entry point for backward compatibility.
        Supports both pinch-to-type and forward-press typing.
        """
        if hand is None:
            self.process_multi_hands([])
            self.is_pinch_active = False
            self.pinch_locked = False
            return

        if hasattr(hand, "calculate_finger_press_metric") or (hasattr(hand, "landmarks_norm") and len(hand.landmarks_norm) > 20):
            self.process_multi_hands([hand])
            return

        # Legacy pointer / mock hand path
        self.is_hand_present = True
        self.pointer_visible = True
        nx, ny = hand.get_tracking_point("index_tip") if hasattr(hand, "get_tracking_point") else (getattr(hand, "x", 0.5), getattr(hand, "y", 0.5))
        self.pointer_norm_pos = (nx, ny)

        w = float(self.width())
        h = float(self.height())
        roi_w = max(0.1, self.roi_right - self.roi_left)
        roi_h = max(0.1, self.roi_bottom - self.roi_top)
        cal_x = (nx - self.roi_left) / roi_w
        cal_y = (ny - self.roi_top) / roi_h

        cx = (cal_x - 0.5) * self.sensitivity_x + 0.5 + self.offset_x
        cy = (cal_y - 0.5) * self.sensitivity_y + 0.5 + self.offset_y
        target_px = max(10.0, min(w - 10.0, cx * w))
        target_py = max(10.0, min(h - 10.0, cy * h))

        now = time.time()
        smooth_x, smooth_y = self.pointer_filter.filter(target_px, target_py, now)
        self.pointer_screen_pos = QPointF(smooth_x, smooth_y)

        # Detect hovered key
        for k in self.keys:
            if k.rect.contains(self.pointer_screen_pos):
                self.hovered_key = k
                k.is_hovered = True
            else:
                k.is_hovered = False

        pinch_dist = getattr(hand, "norm_pinch_distance", getattr(hand, "pinch_distance", 1.0))
        self.current_pinch_dist = pinch_dist
        if pinch_dist < self.pinch_threshold:
            self.is_pinch_active = True
            if not self.pinch_locked and (now - self.last_keypress_time >= self.keypress_cooldown):
                if self.hovered_key is not None:
                    self._execute_key(self.hovered_key)
                    self.pinch_locked = True
                    self.last_keypress_time = now
        elif pinch_dist > self.pinch_release_threshold:
            self.is_pinch_active = False
            self.pinch_locked = False

    def trigger_activation_animation(self) -> None:
        """Triggers a futuristic Iron Man activation banner and shockwave sweep."""
        self._activation_anim_progress = 1.0
        self._activation_banner_text = "AIR TYPING ACTIVE // TWO-HAND OPTICAL SYNC ENGAGED"
        w = float(self.width())
        h = float(self.height())
        self._ripples.append(KeyRipple(
            center=QPointF(w * 0.5, h * 0.6),
            current_r=10.0,
            max_r=w * 0.6,
            alpha=255.0,
            color=QColor(0, 255, 200),
            speed=7.0
        ))

    def reset_all_fingers(self) -> None:
        """Resets all per-finger tracking and lock states on mode switch."""
        self._reset_all_finger_visuals()
        self.is_pinch_active = False
        self.pinch_locked = False
        self.left_hand_present = False
        self.right_hand_present = False

    def _reset_all_finger_visuals(self) -> None:
        for f in self.fingers.values():
            f.visible = False
            f.state = FingerPressState.IDLE
            f.is_pressed = False
            f.press_locked = False
            f.locked_key_id = None
            f.press_depth = 0.0
            f.hovered_key_id = None
            f.hover_start_time = 0.0
            f.dwell_progress = 0.0
            f.dwell_locked_key_id = None
            f.dwell_anchor_pos = None
            f.last_hovered_key_id = None
            f.is_extended = False
        for k in self.keys:
            k.is_hovered = False
            k.hover_fingers.clear()
        self.dwell_progress = 0.0
        self.dwell_locked_key_id = None
        self.last_hovered_key_id = None
        self.dwell_anchor_pos = None
        self.hover_start_time = 0.0

    # -----------------------------------------------------------------
    # Keypress Execution & Text Operations
    # -----------------------------------------------------------------
    def _execute_key(self, key: KeyDef, finger_id: Optional[str] = None, trigger_method: str = "DIRECT") -> None:
        """Executes action for the chosen key and triggers visual shockwaves."""
        key.glow_intensity = 1.0
        self.last_typed_char = key.label
        fid = finger_id or "DIRECT"

        # 6-Stage Input Pipeline Logging
        logger.info(f"[STAGE 1/6: FINGER DETECTED] Finger={fid} at screen=({key.rect.center().x():.1f}, {key.rect.center().y():.1f})")
        logger.info(f"[STAGE 2/6: KEY SELECTED] Key='{key.label}' ID={key.key_id} Hitbox={key.rect}")
        logger.info(f"[STAGE 3/6: PRESS ACCEPTED] Method={trigger_method} Finger={fid} Key='{key.label}'")

        # 1. Action-based keys
        if key.action:
            act = key.action
            if act == "backspace":
                self._action_backspace()
            elif act == "space":
                self._insert_text(" ")
            elif act == "enter":
                self._insert_text("\n")
            elif act == "tab":
                self._insert_text("    ")
            elif act == "caps":
                self.is_caps_lock = not self.is_caps_lock
                self.mode_changed.emit(f"CAPS LOCK: {'ON' if self.is_caps_lock else 'OFF'}")
            elif act == "shift":
                self.is_shift = not self.is_shift
            elif act == "esc":
                self.clear_selection()
            elif act == "clear":
                self.clear_text()
            elif act == "select_all":
                self.select_all()
            elif act == "copy":
                self.copy_to_clipboard()
            elif act == "paste":
                self.paste_from_clipboard()
            elif act == "left":
                self.cursor_pos = max(0, self.cursor_pos - 1)
            elif act == "right":
                self.cursor_pos = min(len(self.text_buffer), self.cursor_pos + 1)
            elif act == "up":
                self._move_cursor_vertical(-1)
            elif act == "down":
                self._move_cursor_vertical(1)

            if self.test_mode or self.key_selection_test_mode:
                self.last_dispatched_event = f"PREDICTED (TEST MODE): '{act}'"
                self.last_rejected_reason = "TEST_MODE_ACTIVE (SendInput Suppressed)"
                logger.info(f"[TEST MODE] Recorded action '{act}' without sending OS input.")
            elif self.global_typing_enabled or self.external_typing_enabled:
                logger.info(f"[STAGE 4/6: KEY MAPPED] Action='{act}' -> Windows Action Mapping")
                logger.info(f"[STAGE 5/6: INPUT API CALLED] Target Application: Dispatching external action '{act}'")
                ok, msg = self._send_external_action(act)
                logger.info(f"[STAGE 6/6: INPUT API RESULT] Success={ok} Result='{msg}'")
                self.last_dispatched_event = f"DISPATCHED (LIVE OS INPUT): '{act}'"
                self.last_rejected_reason = "NONE (ACCEPTED)"
            else:
                self.last_dispatched_event = f"LOCAL BUFFER ONLY: '{act}'"
                self.last_rejected_reason = "GLOBAL_INPUT_DISABLED"
        else:
            # 2. Character keys
            use_shift = self.is_shift ^ self.is_caps_lock
            out_char = key.shift_char if use_shift else key.char

            if out_char:
                self._insert_text(out_char)
                if self.test_mode or self.key_selection_test_mode:
                    self.last_dispatched_event = f"PREDICTED (TEST MODE): '{out_char}'"
                    self.last_rejected_reason = "TEST_MODE_ACTIVE (SendInput Suppressed)"
                    logger.info(f"[TEST MODE] Recorded char '{out_char}' without sending OS input.")
                elif self.global_typing_enabled or self.external_typing_enabled:
                    logger.info(f"[STAGE 4/6: KEY MAPPED] Char='{out_char}' -> Windows Virtual Key / Unicode")
                    logger.info(f"[STAGE 5/6: INPUT API CALLED] Target Application: Dispatching external char '{out_char}'")
                    ok, msg = self._send_external_char(out_char)
                    logger.info(f"[STAGE 6/6: INPUT API RESULT] Success={ok} Result='{msg}'")
                    self.last_dispatched_event = f"DISPATCHED (LIVE OS INPUT): '{out_char}'"
                    self.last_rejected_reason = "NONE (ACCEPTED)"
                else:
                    self.last_dispatched_event = f"LOCAL BUFFER ONLY: '{out_char}'"
                    self.last_rejected_reason = "GLOBAL_INPUT_DISABLED"

            # Auto-reset one-shot shift after regular character
            if self.is_shift:
                self.is_shift = False

        self.update()

    def _insert_text(self, text: str) -> None:
        """Inserts text at cursor position, replacing active selection if present."""
        if self.selection_start is not None and self.selection_end is not None:
            low = min(self.selection_start, self.selection_end)
            high = max(self.selection_start, self.selection_end)
            self.text_buffer = self.text_buffer[:low] + text + self.text_buffer[high:]
            self.cursor_pos = low + len(text)
            self.clear_selection()
        else:
            self.text_buffer = (
                self.text_buffer[:self.cursor_pos] + text + self.text_buffer[self.cursor_pos:]
            )
            self.cursor_pos += len(text)

        self.text_changed.emit(self.text_buffer)

    def _action_backspace(self) -> None:
        """Removes selected text or preceding character."""
        if self.selection_start is not None and self.selection_end is not None:
            low = min(self.selection_start, self.selection_end)
            high = max(self.selection_start, self.selection_end)
            self.text_buffer = self.text_buffer[:low] + self.text_buffer[high:]
            self.cursor_pos = low
            self.clear_selection()
        elif self.cursor_pos > 0:
            self.text_buffer = self.text_buffer[:self.cursor_pos - 1] + self.text_buffer[self.cursor_pos:]
            self.cursor_pos -= 1

        self.text_changed.emit(self.text_buffer)

    def _move_cursor_vertical(self, line_delta: int) -> None:
        """Moves cursor vertically across lines in the text buffer."""
        lines = self.text_buffer.split("\n")
        cur_line = 0
        cur_col = 0
        accum = 0
        for i, l in enumerate(lines):
            line_len = len(l) + 1  # include \n
            if accum + line_len > self.cursor_pos:
                cur_line = i
                cur_col = self.cursor_pos - accum
                break
            accum += line_len

        target_line = max(0, min(len(lines) - 1, cur_line + line_delta))
        target_accum = sum(len(lines[i]) + 1 for i in range(target_line))
        target_col = min(len(lines[target_line]), cur_col)
        self.cursor_pos = target_accum + target_col

    def select_all(self) -> None:
        self.selection_start = 0
        self.selection_end = len(self.text_buffer)
        self.cursor_pos = len(self.text_buffer)

    def clear_selection(self) -> None:
        self.selection_start = None
        self.selection_end = None

    def clear_text(self) -> None:
        self.text_buffer = ""
        self.cursor_pos = 0
        self.clear_selection()
        self.text_changed.emit(self.text_buffer)

    def copy_to_clipboard(self) -> bool:
        cb = QApplication.clipboard()
        if cb:
            text_to_copy = self.get_selected_text() or self.text_buffer
            cb.setText(text_to_copy)
            logger.info(f"[KEYBOARD] Copied {len(text_to_copy)} chars to clipboard.")
            return True
        return False

    def cut_to_clipboard(self) -> bool:
        if self.copy_to_clipboard():
            if self.selection_start is not None and self.selection_end is not None:
                self._action_backspace()
            else:
                self.clear_text()
            return True
        return False

    def paste_from_clipboard(self) -> bool:
        cb = QApplication.clipboard()
        if cb:
            txt = cb.text()
            if txt:
                self._insert_text(txt)
                return True
        return False

    def get_selected_text(self) -> str:
        if self.selection_start is not None and self.selection_end is not None:
            low = min(self.selection_start, self.selection_end)
            high = max(self.selection_start, self.selection_end)
            return self.text_buffer[low:high]
        return ""

    def save_to_file(self, filepath: Optional[str] = None) -> bool:
        """Saves current text buffer to a local text file."""
        if not filepath:
            filepath = os.path.join(os.getcwd(), "nexus_document.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.text_buffer)
            logger.info(f"[KEYBOARD] Document saved successfully to: {filepath}")
            return True
        except Exception as e:
            logger.error(f"[KEYBOARD] Failed to save document: {e}")
            return False

    # -------------------------------------------------------------
    # Optional External Typing (Windows API / PyAutoGUI)
    # -------------------------------------------------------------
    def toggle_external_typing(self) -> bool:
        """Toggles sending keystrokes to the focused external application."""
        self.external_typing_enabled = not self.external_typing_enabled
        if self.external_typing_enabled:
            self.test_mode = False
        status = "ARMED (EXTERNAL APP)" if self.external_typing_enabled else "OFF (INTERNAL ONLY)"
        self.mode_changed.emit(f"EXTERNAL TYPING: {status}")
        logger.warning(f"[KEYBOARD SAFETY] External typing mode changed: {status}")
        self.update()
        return self.external_typing_enabled

    def _send_external_char(self, char: str) -> Tuple[bool, str]:
        ok = True
        msg = f"Dispatched '{char}'"
        try:
            if hasattr(self, "keyboard_service") and self.keyboard_service and self.global_typing_enabled:
                use_shift = self.is_shift ^ self.is_caps_lock
                ok, msg = self.keyboard_service.send_char(char, is_shift=use_shift, is_caps_lock=self.is_caps_lock)
            elif self.external_typing_enabled:
                pyautogui.write(char, _pause=False)
                msg = f"PyAutoGUI dispatched '{char}'"
            return ok, msg
        except Exception as e:
            logger.error(f"Error sending external char: {e}")
            return False, str(e)

    def _send_external_action(self, action: str) -> Tuple[bool, str]:
        ok = True
        msg = f"Dispatched action '{action}'"
        try:
            if hasattr(self, "keyboard_service") and self.keyboard_service and self.global_typing_enabled:
                ok, msg = self.keyboard_service.send_action(action)
            elif self.external_typing_enabled:
                key_map = {
                    "backspace": "backspace",
                    "enter": "enter",
                    "tab": "tab",
                    "esc": "esc",
                    "space": "space",
                    "left": "left",
                    "right": "right",
                    "up": "up",
                    "down": "down"
                }
                if action in key_map:
                    pyautogui.press(key_map[action], _pause=False)
                    msg = f"PyAutoGUI pressed '{action}'"
            return ok, msg
        except Exception as e:
            logger.error(f"Error sending external action {action}: {e}")
            return False, str(e)

    # -------------------------------------------------------------
    # Animation Tick
    # -------------------------------------------------------------
    def _animation_tick(self) -> None:
        if not self.isVisible():
            return

        now = time.time()
        self._phase = (self._phase + 0.05) % (2.0 * math.pi)

        # Cursor blink
        if now - self._last_cursor_blink >= 0.50:
            self._cursor_blink_visible = not self._cursor_blink_visible
            self._last_cursor_blink = now

        # Decay activation banner
        if self._activation_anim_progress > 0.0:
            self._activation_anim_progress = max(0.0, self._activation_anim_progress - 0.03)

        # Decay key glow intensities
        for k in self.keys:
            if k.glow_intensity > 0.0:
                k.glow_intensity = max(0.0, k.glow_intensity - 0.08)

        # Update ripples
        active_ripples = []
        for r in self._ripples:
            r.current_r += r.speed
            r.alpha = max(0.0, r.alpha - 12.0)
            if r.alpha > 0 and r.current_r < r.max_r:
                active_ripples.append(r)
        self._ripples = active_ripples

        # Scan line animation
        self._scan_line_y = (self._scan_line_y + 3.0) % max(1, self.height())

        # Particles drift
        for p in self._particles:
            p["y"] -= p["speed"]
            if p["y"] < 0:
                p["y"] = 1.0

        self.update()

    # -------------------------------------------------------------
    # Mouse Click Fallback
    # -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if self._handle_action_bar_click(pos):
            event.accept()
            return

        for k in self.keys:
            if k.rect.contains(pos):
                self.handle_virtual_key(k.key_id, finger_id="MOUSE_CLICK")
                event.accept()
                return

        super().mousePressEvent(event)

    def _handle_action_bar_click(self, pos: QPointF) -> bool:
        y = pos.y()
        if 4.0 <= y <= 30.0:
            w = float(self.width())
            x = pos.x()
            if 160.0 <= x <= 210.0:
                self.save_to_file()
                return True
            elif 215.0 <= x <= 300.0:
                self.toggle_key_selection_test_mode()
                return True
            elif 305.0 <= x <= 390.0:
                self.toggle_test_mode()
                return True
            elif 395.0 <= x <= 480.0:
                self.toggle_global_typing()
                return True
            elif 485.0 <= x <= 565.0:
                modes = ["DWELL", "PINCH"]
                curr_idx = modes.index(self.press_detection_mode) if self.press_detection_mode in modes else 0
                self.press_detection_mode = modes[(curr_idx + 1) % len(modes)]
                self.mode_changed.emit(f"TYPING MODE: {self.press_detection_mode}")
                if hasattr(self, "settings_manager") and self.settings_manager:
                    self.settings_manager.set("air_typing", "typing_mode", self.press_detection_mode)
                    self.settings_manager.save()
                self.update()
                return True
            elif 570.0 <= x <= 610.0:
                self.toggle_one_hand_mode()
                return True
            elif 612.0 <= x <= 652.0:
                self.send_test_key('a')
                return True
            elif 655.0 <= x <= 710.0:
                self.show_diagnostics_hud = not self.show_diagnostics_hud
                self.update()
                return True
            elif 715.0 <= x <= 775.0:
                self.toggle_overlay()
                return True
            elif 780.0 <= x <= 845.0:
                self.open_keyboard_diagnostics_dialog()
                return True
            elif (w - 70.0) <= x <= (w - 8.0):
                self.closed.emit()
                return True
        return False

    def toggle_overlay(self) -> None:
        """Toggles the floating desktop keyboard overlay window."""
        if hasattr(self, "global_overlay") and self.global_overlay is not None:
            self.global_overlay.toggle_overlay()

    def set_typing_mode(self, mode: str) -> None:
        """Sets active typing mode ('DWELL' or 'PINCH') and persists."""
        mode_upper = mode.upper()
        if mode_upper in ("DWELL", "PINCH", "HYBRID"):
            self.press_detection_mode = mode_upper
            self.mode_changed.emit(f"TYPING MODE: {self.press_detection_mode}")
            if hasattr(self, "settings_manager") and self.settings_manager:
                self.settings_manager.set("air_typing", "typing_mode", self.press_detection_mode)
                self.settings_manager.save()
            self.update()

    def set_dwell_duration(self, seconds: float) -> None:
        """Configures dwell-to-type duration clamped between 0.3s and 1.0s."""
        self.hover_dwell_time = max(0.30, min(1.0, float(seconds)))
        if hasattr(self, "settings_manager") and self.settings_manager:
            self.settings_manager.set("air_typing", "dwell_duration", self.hover_dwell_time)
            self.settings_manager.save()
        self.update()

    def open_keyboard_diagnostics_dialog(self) -> None:
        """Launches the dedicated 8-test Keyboard Diagnostics Panel."""
        try:
            from app.keyboard_diagnostics_dialog import KeyboardDiagnosticsDialog
            dlg = KeyboardDiagnosticsDialog(self, parent=self.window())
            dlg.show()
        except Exception as e:
            logger.error(f"Failed to open KeyboardDiagnosticsDialog: {e}", exc_info=True)

    def open_air_typing_calibration_dialog(self) -> None:
        """Opens the interactive Two-Hand Air Typing calibration dialog."""
        dlg = AirTypingCalibrationDialog(self)
        dlg.exec()

    # -------------------------------------------------------------
    # Rendering Engine (Cinematic Iron Man QPainter Projection)
    # -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)

            w = float(self.width())
            h = float(self.height())

            # 1. Dark futuristic cockpit backdrop
            p.fillRect(0, 0, w, h, QColor(3, 8, 20, 240))
            p.setPen(QPen(QColor(0, 240, 255, 60), 0.8))
            p.drawRect(QRectF(1, 1, w - 2, h - 2))

            # Corner HUD brackets
            blen = 14.0
            p.setPen(QPen(QColor(0, 240, 255, 180), 1.5))
            p.drawLine(1, 1, 1 + blen, 1); p.drawLine(1, 1, 1, 1 + blen)
            p.drawLine(w - 2, 1, w - 2 - blen, 1); p.drawLine(w - 2, 1, w - 2, 1 + blen)
            p.drawLine(1, h - 2, 1 + blen, h - 2); p.drawLine(1, h - 2, 1, h - 2 - blen)
            p.drawLine(w - 2, h - 2, w - 2 - blen, h - 2); p.drawLine(w - 2, h - 2, w - 2, h - 2 - blen)

            # 2. Ambient Particles
            for pt in self._particles:
                px = pt["x"] * w
                py = pt["y"] * h
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(0, 240, 255, 45)))
                p.drawEllipse(QRectF(px - pt["r"], py - pt["r"], pt["r"] * 2, pt["r"] * 2))

            # 3. Top Action Bar & Telemetry Status
            self._draw_action_bar(p, w)

            # 4. Floating Holographic Text Preview Panel
            self._draw_text_preview(p, w, h)

            # 5. Holographic Keyboard Keys
            self._draw_keys(p)

            # 6. Radiating Keypress Ripples / Shockwaves
            for r in self._ripples:
                p.setPen(QPen(QColor(r.color.red(), r.color.green(), r.color.blue(), int(r.alpha)), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(r.center.x() - r.current_r, r.center.y() - r.current_r, r.current_r * 2, r.current_r * 2))

            # 7. Subtle Scanning Line
            p.setPen(QPen(QColor(0, 240, 255, 28), 1.0))
            p.drawLine(QPointF(0, self._scan_line_y), QPointF(w, self._scan_line_y))

            # 8. Individual Finger Reticles (Two-Hand Air Typing)
            self._draw_finger_reticles(p)

            # 9. Activation Banner
            if self._activation_anim_progress > 0.0:
                self._draw_activation_banner(p, w, h)
        except Exception as e:
            logger.error(f"[HOLO_KEYBOARD] paintEvent error: {e}", exc_info=True)
        finally:
            p.end()

    def _draw_action_bar(self, p: QPainter, w: float) -> None:
        """Renders top action buttons, calibration, diagnostics test triggers, and system status bar."""
        p.fillRect(QRectF(0, 0, w, 32), QColor(6, 14, 32, 220))
        p.setPen(QPen(QColor(0, 240, 255, 40), 1.0))
        p.drawLine(QPointF(0, 32), QPointF(w, 32))

        # Title
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.setPen(QColor(ACCENT_CYAN))
        p.drawText(10, 20, "N.E.X.U.S. // TWO-HAND AIR TYPING")

        # Save TXT Button [160..210]
        btn_save = QRectF(160, 6, 50, 20)
        p.fillRect(btn_save, QColor(0, 100, 200, 50))
        p.setPen(QPen(QColor(0, 240, 255, 120), 1.0))
        p.drawRect(btn_save)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(btn_save, Qt.AlignCenter, "SAVE")

        # KEY SELECTION TEST MODE Toggle Button [215..300]
        btn_key_test = QRectF(215, 6, 85, 20)
        if self.key_selection_test_mode:
            p.fillRect(btn_key_test, QColor(168, 85, 247, 90))
            p.setPen(QPen(QColor(192, 132, 252, 230), 1.2))
            p.drawRect(btn_key_test)
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn_key_test, Qt.AlignCenter, "● TEST-KEY:ON")
        else:
            p.fillRect(btn_key_test, QColor(8, 20, 44, 90))
            p.setPen(QPen(QColor(0, 200, 255, 50), 1.0))
            p.drawRect(btn_key_test)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(btn_key_test, Qt.AlignCenter, "○ TEST-KEY")

        # DRY-RUN TEST MODE Toggle Button [305..390]
        btn_test = QRectF(305, 6, 85, 20)
        if self.test_mode:
            p.fillRect(btn_test, QColor(99, 102, 241, 90))
            p.setPen(QPen(QColor(129, 140, 248, 230), 1.2))
            p.drawRect(btn_test)
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn_test, Qt.AlignCenter, "● DRY-RUN:ON")
        else:
            p.fillRect(btn_test, QColor(245, 158, 11, 80))
            p.setPen(QPen(QColor(245, 158, 11, 230), 1.2))
            p.drawRect(btn_test)
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn_test, Qt.AlignCenter, "○ LIVE INPUT")

        # GLOBAL WINDOWS KEYBOARD Button [395..480]
        btn_global = QRectF(395, 6, 85, 20)
        if self.global_typing_enabled:
            p.fillRect(btn_global, QColor(34, 197, 94, 90))
            p.setPen(QPen(QColor(74, 222, 128, 230), 1.2))
            p.drawRect(btn_global)
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn_global, Qt.AlignCenter, "● GLOBAL:ON")
        else:
            p.fillRect(btn_global, QColor(8, 20, 44, 90))
            p.setPen(QPen(QColor(0, 200, 255, 50), 1.0))
            p.drawRect(btn_global)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(btn_global, Qt.AlignCenter, "○ GLOBAL")

        # TYPING MODE Toggle Button [485..565]
        btn_trig = QRectF(485, 6, 80, 20)
        is_dwell = (self.press_detection_mode == "DWELL")
        mode_bg = QColor(6, 182, 212, 100) if is_dwell else QColor(168, 85, 247, 90)
        mode_border = QColor(0, 240, 255, 220) if is_dwell else QColor(192, 132, 252, 220)
        p.fillRect(btn_trig, mode_bg)
        p.setPen(QPen(mode_border, 1.2))
        p.drawRect(btn_trig)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(btn_trig, Qt.AlignCenter, "● DWELL" if is_dwell else "○ PINCH")

        # 1-HAND / 2-HAND Toggle Button [570..610]
        btn_hand_mode = QRectF(570, 6, 40, 20)
        if self.one_hand_test_mode:
            p.fillRect(btn_hand_mode, QColor(14, 165, 233, 90))
            p.setPen(QPen(QColor(56, 189, 248, 230), 1.2))
            p.drawRect(btn_hand_mode)
            p.setFont(QFont("Consolas", 7, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn_hand_mode, Qt.AlignCenter, f"1H:{self.active_typing_hand[:1]}")
        else:
            p.fillRect(btn_hand_mode, QColor(8, 20, 44, 90))
            p.setPen(QPen(QColor(0, 200, 255, 50), 1.0))
            p.drawRect(btn_hand_mode)
            p.setFont(QFont("Consolas", 7, QFont.Bold))
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(btn_hand_mode, Qt.AlignCenter, "2H")

        # TEST KEY Button [615..650]
        btn_test_key = QRectF(615, 6, 35, 20)
        p.fillRect(btn_test_key, QColor(168, 85, 247, 90))
        p.setPen(QPen(QColor(192, 132, 252, 230), 1.2))
        p.drawRect(btn_test_key)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(btn_test_key, Qt.AlignCenter, "⚡TEST")

        # Diagnostics HUD Toggle Button [655..710]
        btn_hud = QRectF(655, 6, 55, 20)
        hud_bg = QColor(16, 185, 129, 60) if self.show_diagnostics_hud else QColor(8, 20, 44, 90)
        hud_border = QColor(16, 185, 129, 180) if self.show_diagnostics_hud else QColor(0, 200, 255, 50)
        p.fillRect(btn_hud, hud_bg)
        p.setPen(QPen(hud_border, 1.0))
        p.drawRect(btn_hud)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255) if self.show_diagnostics_hud else QColor(TEXT_MUTED))
        p.drawText(btn_hud, Qt.AlignCenter, f"HUD:{'ON' if self.show_diagnostics_hud else 'OFF'}")

        # OVERLAY Toggle Button [715..775]
        btn_overlay = QRectF(715, 6, 60, 20)
        overlay_active = getattr(self.global_overlay, "is_visible", False) if self.global_overlay else False
        p.fillRect(btn_overlay, QColor(99, 102, 241, 80) if overlay_active else QColor(8, 20, 44, 90))
        p.setPen(QPen(QColor(129, 140, 248, 200) if overlay_active else QColor(0, 200, 255, 50), 1.0))
        p.drawRect(btn_overlay)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255) if overlay_active else QColor(TEXT_MUTED))
        p.drawText(btn_overlay, Qt.AlignCenter, "OVERLAY")

        # DIAGNOSTICS DIALOG Button [780..845]
        btn_diag = QRectF(780, 6, 65, 20)
        p.fillRect(btn_diag, QColor(16, 185, 129, 80))
        p.setPen(QPen(QColor(52, 211, 153, 200), 1.0))
        p.drawRect(btn_diag)
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(btn_diag, Qt.AlignCenter, "🔬 DIAG")

        # Status telemetry pills (Right side)
        caps_str = "CAPS" if self.is_caps_lock else ""
        shift_str = "SHIFT" if self.is_shift else ""
        mode_str = f"{caps_str} {shift_str}".strip() or "STD"

        l_str = "L:ON" if self.left_detected else "L:OFF"
        r_str = "R:ON" if self.right_detected else "R:OFF"
        hands_str = f"[{l_str} {r_str}]"

        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(0, 240, 255, 180))
        p.drawText(QRectF(w - 240, 6, 160, 20), Qt.AlignRight | Qt.AlignVCenter, f"{hands_str} [{mode_str}]")

        # Close button [w - 70 .. w - 10]
        btn_close = QRectF(w - 70, 6, 60, 20)
        p.fillRect(btn_close, QColor(239, 68, 68, 40))
        p.setPen(QPen(QColor(239, 68, 68, 140), 1.0))
        p.drawRect(btn_close)
        p.setPen(QColor(255, 200, 200))
        p.drawText(btn_close, Qt.AlignCenter, "CLOSE [X]")

    def _draw_text_preview(self, p: QPainter, w: float, h: float) -> None:
        """Renders the floating holographic text document and status telemetry."""
        preview_h = max(60.0, (h * 0.35) - 38.0)
        box = QRectF(16, 38, w - 32, preview_h)

        p.fillRect(box, QColor(4, 12, 28, 200))
        p.setPen(QPen(QColor(0, 240, 255, 120), 1.0))
        p.drawRect(box)

        # Corner brackets
        blen = 8.0
        p.setPen(QPen(QColor(0, 240, 255, 220), 1.2))
        p.drawLine(box.left(), box.top(), box.left() + blen, box.top())
        p.drawLine(box.left(), box.top(), box.left(), box.top() + blen)
        p.drawLine(box.right(), box.top(), box.right() - blen, box.top())
        p.drawLine(box.right(), box.top(), box.right(), box.top() + blen)

        # Layout width division for text preview vs diagnostic HUD
        hud_w = min(380.0, (w - 32.0) * 0.50) if self.show_diagnostics_hud else 0.0
        text_w = (box.width() - 20.0) if hud_w == 0.0 else (box.width() - hud_w - 24.0)

        # Text display
        p.setFont(QFont("Consolas", 10))
        p.setPen(QColor(240, 248, 255))

        visible_text = self.text_buffer
        if self._cursor_blink_visible:
            pos = self.cursor_pos
            rendered = visible_text[:pos] + "█" + visible_text[pos:]
        else:
            rendered = visible_text + " "

        inner = QRectF(box.left() + 10.0, box.top() + 8.0, max(100.0, text_w), box.height() - 24.0)
        p.drawText(inner, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, rendered)

        # Prominent Tracking Lost indicator if hands absent
        if not self.left_detected and not self.right_detected:
            p.save()
            warn_rect = QRectF(box.left() + 10, box.top() + 4, min(380.0, max(140.0, text_w)), 20)
            p.fillRect(warn_rect, QColor(220, 38, 38, 75))
            p.setPen(QPen(QColor(239, 68, 68, 210), 1.0))
            p.drawRect(warn_rect)
            p.setFont(QFont("Consolas", 7, QFont.Bold))
            p.setPen(QColor(254, 202, 202))
            p.drawText(warn_rect, Qt.AlignCenter, "⚠ TRACKING PAUSED // PLACE HANDS IN SENSOR VIEW")
            p.restore()

        # Telemetry metrics at bottom-left
        char_count = len(self.text_buffer)
        word_count = len(self.text_buffer.split())
        elapsed_min = max(0.1, (time.time() - self.session_start_time) / 60.0)
        wpm = int(word_count / elapsed_min)

        p.setFont(QFont("Consolas", 6, QFont.Bold))
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(box.left() + 10, box.bottom() - 16, max(120.0, text_w), 14),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   f"CHARS: {char_count} | WORDS: {word_count} | WPM: {wpm} | KEYS: {self.total_keystrokes}")

        # Dedicated Live Diagnostics HUD Overlay
        if self.show_diagnostics_hud and hud_w > 120.0:
            hud_rect = QRectF(box.right() - hud_w, box.top(), hud_w, box.height())
            p.fillRect(hud_rect, QColor(2, 9, 22, 235))
            p.setPen(QPen(QColor(0, 240, 255, 90), 1.0))
            p.drawLine(hud_rect.left(), hud_rect.top(), hud_rect.left(), hud_rect.bottom())

            p.setFont(QFont("Consolas", 7, QFont.Bold))
            p.setPen(QColor(0, 240, 255))
            mode_str = self.dual_hand_mode_state.value if hasattr(self.dual_hand_mode_state, "value") else str(self.dual_hand_mode_state or "")
            mode_hdr = mode_str
            if "SWITCHING" in mode_str and self.mode_switch_countdown > 0:
                mode_hdr += f" ({self.mode_switch_countdown:.1f}s)"

            p.drawText(QRectF(hud_rect.left() + 8, hud_rect.top() + 3, hud_w - 16, 13),
                       Qt.AlignLeft, f"HUD // STATE: {mode_hdr} | HANDS: {self.detected_hand_count}")

            p.setFont(QFont("Consolas", 6))
            y_cur = hud_rect.top() + 17

            # Left Hand Telemetry
            l_det = "YES" if self.left_detected else "NO"
            l_ext = "EXT" if self.left_index_extended else "FOLDED"
            l_dwell = int((self.fingers["L_INDEX"].dwell_progress if "L_INDEX" in self.fingers else 0.0) * 100)
            p.setPen(QColor(56, 189, 248) if self.left_detected else QColor(TEXT_MUTED))
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"L-HAND: [{l_det}] | Idx:[{l_ext}] | Key:[{self.left_hovered_key}] | Dwell:{l_dwell}%")
            y_cur += 11
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"  State:{self.left_press_state} | Gate:{self.left_rejection_reason[:25]}")
            y_cur += 12

            # Right Hand Telemetry
            r_det = "YES" if self.right_detected else "NO"
            r_ext = "EXT" if self.right_index_extended else "FOLDED"
            r_dwell = int((self.fingers["R_INDEX"].dwell_progress if "R_INDEX" in self.fingers else 0.0) * 100)
            p.setPen(QColor(52, 211, 153) if self.right_detected else QColor(TEXT_MUTED))
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"R-HAND: [{r_det}] | Idx:[{r_ext}] | Key:[{self.right_hovered_key}] | Dwell:{r_dwell}%")
            y_cur += 11
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"  State:{self.right_press_state} | Gate:{self.right_rejection_reason[:25]}")
            y_cur += 12

            # Mode Transition & Timing
            p.setPen(QColor(245, 158, 11) if "SWITCHING" in mode_str else QColor(168, 85, 247))
            sw_str = f" [TIMEOUT: {self.mode_switch_countdown:.1f}s]" if self.mode_switch_countdown > 0 else ""
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"MODE: {mode_str}{sw_str}")
            y_cur += 11

            p.setPen(QColor(148, 163, 184))
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"TRANSITION: {self.last_mode_transition_reason[:32]}")
            y_cur += 11

            # Target Window
            target_title = self.keyboard_service.last_external_title or "Focused Window"
            p.setPen(QColor(226, 232, 240))
            p.drawText(QRectF(hud_rect.left() + 8, y_cur, hud_w - 16, 11),
                       Qt.AlignLeft, f"TARGET: {target_title[:28]}")

    def _draw_keys(self, p: QPainter) -> None:
        """Renders all keyboard keys with holographic styling, ergonomic border tints, and labels."""
        use_shift = self.is_shift ^ self.is_caps_lock

        for k in self.keys:
            r = k.rect
            if r.width() <= 0 or r.height() <= 0:
                continue

            if k.is_hovered:
                bg_col = QColor(0, 160, 240, 95)
                border_col = QColor(0, 240, 255, 240)
                pen_w = 1.6
                text_col = QColor(255, 255, 255)
            elif k.glow_intensity > 0.0:
                alpha = int(120 + 135 * k.glow_intensity)
                bg_col = QColor(245, 158, 11, alpha) if k.is_accent else QColor(0, 240, 255, alpha)
                border_col = QColor(255, 255, 255, 255)
                pen_w = 2.0
                text_col = QColor(255, 255, 255)
            elif k.is_accent:
                bg_col = QColor(14, 28, 55, 160)
                border_col = QColor(245, 158, 11, 140)
                pen_w = 1.1
                text_col = QColor(245, 158, 11)
            else:
                # Ergonomic split tint (Left hand keys vs Right hand keys)
                if k.assigned_hand == "LEFT":
                    border_col = QColor(0, 210, 255, 80)
                elif k.assigned_hand == "RIGHT":
                    border_col = QColor(0, 160, 255, 80)
                else:
                    border_col = QColor(0, 200, 255, 70)
                bg_col = QColor(6, 16, 36, 140)
                pen_w = 0.9
                text_col = QColor(TEXT_PRIMARY)

            # Draw key body
            p.fillRect(r, bg_col)
            p.setPen(QPen(border_col, pen_w))
            p.drawRect(r)

            # Dwell-to-type countdown indicator on hovered key
            if k.is_hovered:
                key_prog = 0.0
                if k.hover_fingers:
                    prog_vals = [self.fingers[fid].dwell_progress for fid in k.hover_fingers if fid in self.fingers]
                    key_prog = max(prog_vals) if prog_vals else self.dwell_progress
                else:
                    key_prog = self.dwell_progress

                if key_prog > 0.0:
                    p.save()
                    prog_w = r.width() * min(1.0, key_prog)
                    prog_rect = QRectF(r.left(), r.bottom() - 3.5, prog_w, 3.5)
                    is_locked = any(self.fingers[fid].dwell_locked_key_id == k.key_id for fid in k.hover_fingers if fid in self.fingers) or (self.dwell_locked_key_id == k.key_id)
                    bar_col = QColor(74, 222, 128, 240) if is_locked else QColor(0, 240, 255, 230)
                    p.fillRect(prog_rect, bar_col)
                    p.restore()

            if k.is_hovered or k.is_accent:
                klen = 4.0
                p.setPen(QPen(QColor(0, 240, 255, 220), 1.2))
                p.drawLine(r.left(), r.top(), r.left() + klen, r.top())
                p.drawLine(r.right(), r.top(), r.right() - klen, r.top())

            label = k.shift_label if use_shift else k.label
            font_sz = 8 if len(label) <= 2 else 7
            p.setFont(QFont("Consolas", font_sz, QFont.Bold))
            p.setPen(text_col)
            p.drawText(r, Qt.AlignCenter, label)

    def _draw_finger_reticles(self, p: QPainter) -> None:
        """Renders holographic circular tracking reticles and depth gauges for active fingers."""
        # Key Selection Test Mode (Phase 5 Diagnostic Highlighting)
        if self.key_selection_test_mode:
            p.save()
            for is_l, box, key_name, col in (
                (True, self.left_index_hitbox, self.left_hovered_key, QColor(0, 240, 255)),
                (False, self.right_index_hitbox, self.right_hovered_key, QColor(52, 211, 153))
            ):
                if box and not box.isEmpty() and key_name != "NONE":
                    p.setPen(QPen(col, 2.0))
                    p.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), 40)))
                    p.drawRect(box)
                    blen = 6.0
                    p.drawLine(box.left(), box.top(), box.left() + blen, box.top())
                    p.drawLine(box.left(), box.top(), box.left(), box.top() + blen)
                    p.drawLine(box.right(), box.bottom(), box.right() - blen, box.bottom())
                    p.drawLine(box.right(), box.bottom(), box.right(), box.bottom() - blen)
                    p.setFont(QFont("Consolas", 6, QFont.Bold))
                    p.setPen(col)
                    tag_str = f"[{'L' if is_l else 'R'}:{key_name}]"
                    p.drawText(QRectF(box.left(), box.top() - 11, box.width(), 10), Qt.AlignCenter, tag_str)
            p.restore()

        for fid, f in self.fingers.items():
            if not f.visible:
                continue

            cx = f.screen_pos.x()
            cy = f.screen_pos.y()
            if cx < 0 or cy < 0:
                continue

            is_left = (f.hand_side == "LEFT")
            base_col = QColor(0, 240, 255) if is_left else QColor(50, 180, 255)

            # Ratio of current forward-press depth to activation threshold
            press_ratio = min(1.0, max(0.0, f.press_depth / max(0.01, self.press_threshold)))

            # Dynamic color transition as finger pushes forward
            if f.is_pressed or press_ratio >= 1.0:
                ring_col = QColor(34, 197, 94) if is_left else QColor(245, 158, 11)  # Triggered
                radius = 16.0
            elif press_ratio > 0.6:
                ring_col = QColor(0, 255, 200)
                radius = 14.0
            else:
                ring_col = base_col
                radius = 12.0

            # Outer reticle circle
            p.setPen(QPen(QColor(ring_col.red(), ring_col.green(), ring_col.blue(), 140), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

            # Depth progress arc
            span_angle = int(press_ratio * 360 * 16)
            if span_angle > 0:
                p.setPen(QPen(ring_col, 2.2))
                p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2), 90 * 16, -span_angle)

            # Dwell progress circular gauge around index fingertip reticle
            f_dwell = getattr(f, "dwell_progress", 0.0)
            if self.press_detection_mode in ("DWELL", "HYBRID") and "INDEX" in fid and f_dwell > 0.0:
                dwell_angle = int(min(1.0, f_dwell) * 360 * 16)
                is_finger_locked = (getattr(f, "dwell_locked_key_id", None) is not None)
                dwell_col = QColor(74, 222, 128) if is_finger_locked else (QColor(0, 240, 255) if is_left else QColor(52, 211, 153))
                p.setPen(QPen(dwell_col, 2.4))
                p.drawArc(QRectF(cx - radius - 3, cy - radius - 3, (radius + 3) * 2, (radius + 3) * 2), 90 * 16, -dwell_angle)

            # Center focal dot
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(ring_col))
            dot_r = 3.5 if f.is_pressed else 2.2
            p.drawEllipse(QRectF(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))

            # Compact finger ID tag
            tag = f"{'L' if is_left else 'R'}-{f.finger_name[:3].upper()}"
            p.setFont(QFont("Consolas", 6, QFont.Bold))
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QRectF(cx - 20, cy + radius + 2, 40, 12), Qt.AlignCenter, tag)

    def _draw_activation_banner(self, p: QPainter, w: float, h: float) -> None:
        """Renders an expanding Iron Man HUD banner when Air Typing activates."""
        alpha = int(self._activation_anim_progress * 240)
        banner_w = min(w - 40, 520.0)
        banner_h = 36.0
        bx = (w - banner_w) / 2.0
        by = (h * 0.36) - 18.0
        rect = QRectF(bx, by, banner_w, banner_h)

        p.fillRect(rect, QColor(4, 20, 36, alpha))
        p.setPen(QPen(QColor(0, 240, 255, alpha), 1.5))
        p.drawRect(rect)

        # Center holographic text
        p.setFont(QFont("Consolas", 9, QFont.Bold))
        p.setPen(QColor(255, 255, 255, alpha))
        p.drawText(rect, Qt.AlignCenter, self._activation_banner_text)


class AirTypingCalibrationDialog(QDialog):
    """Interactive Calibration Dialog for Two-Hand Air Typing Sensitivity and Forward Press Depth."""

    def __init__(self, keyboard_widget: HolographicKeyboardWidget, parent: Optional[QWidget] = None):
        super().__init__(parent or keyboard_widget)
        self.keyboard = keyboard_widget
        self.setWindowTitle("N.E.X.U.S. :: TWO-HAND AIR TYPING CALIBRATION")
        self.setFixedSize(480, 380)
        self.setStyleSheet("""
            QDialog { background-color: #030814; border: 1px solid #00F0FF; }
            QLabel { color: #E0F2FE; font-family: Consolas; font-size: 11px; }
            QPushButton {
                background: rgba(0, 180, 255, 0.15); border: 1px solid #00F0FF;
                color: #FFFFFF; font-family: Consolas; font-weight: bold; padding: 6px 14px;
            }
            QPushButton:hover { background: rgba(0, 240, 255, 0.35); }
            QSlider::groove:horizontal { height: 4px; background: #0A1C36; }
            QSlider::handle:horizontal { background: #00F0FF; width: 14px; margin: -5px 0; border-radius: 7px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("AIR TYPING CALIBRATION PROTOCOL")
        title.setStyleSheet("font-size: 14px; font-weight: 900; color: #00F0FF; letter-spacing: 2px;")
        layout.addWidget(title)

        desc = QLabel(
            "Move fingers forward toward the virtual keys in the air.\n"
            "Adjust forward-press depth and sensitivity to match your natural hand motion."
        )
        desc.setStyleSheet("color: #94A3B8; font-size: 9px;")
        layout.addWidget(desc)

        # Press Threshold Slider
        layout.addWidget(QLabel("FORWARD PRESS THRESHOLD (Trigger Depth):"))
        self.slider_press = QSlider(Qt.Horizontal)
        self.slider_press.setRange(10, 50)
        self.slider_press.setValue(int(self.keyboard.press_threshold * 100))
        self.lbl_press = QLabel(f"{self.keyboard.press_threshold:.2f}")
        h1 = QHBoxLayout()
        h1.addWidget(self.slider_press)
        h1.addWidget(self.lbl_press)
        layout.addLayout(h1)

        # Release Threshold Slider
        layout.addWidget(QLabel("RELEASE THRESHOLD (Withdraw Depth):"))
        self.slider_release = QSlider(Qt.Horizontal)
        self.slider_release.setRange(5, 30)
        self.slider_release.setValue(int(self.keyboard.release_threshold * 100))
        self.lbl_release = QLabel(f"{self.keyboard.release_threshold:.2f}")
        h2 = QHBoxLayout()
        h2.addWidget(self.slider_release)
        h2.addWidget(self.lbl_release)
        layout.addLayout(h2)

        # Sensitivity Slider
        layout.addWidget(QLabel("HORIZONTAL SPAN SENSITIVITY:"))
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(80, 220)
        self.slider_sens.setValue(int(self.keyboard.sensitivity_x * 100))
        self.lbl_sens = QLabel(f"{self.keyboard.sensitivity_x:.2f}")
        h3 = QHBoxLayout()
        h3.addWidget(self.slider_sens)
        h3.addWidget(self.lbl_sens)
        layout.addLayout(h3)

        self.slider_press.valueChanged.connect(self._on_press_changed)
        self.slider_release.valueChanged.connect(self._on_release_changed)
        self.slider_sens.valueChanged.connect(self._on_sens_changed)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton("RESET DEFAULTS")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_save = QPushButton("SAVE & CLOSE")
        btn_save.clicked.connect(self._save_and_close)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def _on_press_changed(self, val: int) -> None:
        th = val / 100.0
        self.lbl_press.setText(f"{th:.2f}")
        self.keyboard.press_threshold = th

    def _on_release_changed(self, val: int) -> None:
        th = val / 100.0
        self.lbl_release.setText(f"{th:.2f}")
        self.keyboard.release_threshold = th

    def _on_sens_changed(self, val: int) -> None:
        sens = val / 100.0
        self.lbl_sens.setText(f"{sens:.2f}")
        self.keyboard.sensitivity_x = sens
        self.keyboard.sensitivity_y = sens

    def _reset_defaults(self) -> None:
        self.slider_press.setValue(22)
        self.slider_release.setValue(12)
        self.slider_sens.setValue(135)

    def _save_and_close(self) -> None:
        self.accept()
