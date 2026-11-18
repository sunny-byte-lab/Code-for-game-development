"""JARVIS Asynchronous Camera Worker Thread.
Runs the OpenCV capture loop, MediaPipe processing, FPS calculation, and input dispatch in a dedicated QThread.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any
import cv2
import numpy as np
import enum
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.hand_tracker import HandTracker, HandLandmarkData
from app.gesture_recognizer import GestureRecognizer, GestureState, GestureType
from app.virtual_mouse import VirtualMouse, MouseState
from app.physical_mouse_detector import PhysicalMouseDetector
from app.safety_controller import SafetyController, ControlMode, SystemState
from app.app_launcher import AppLauncher
from app.system_controls import SystemControls
from app.scroll_controller import ScrollController, ScrollTelemetry
from app.camera_device_utils import (
    probe_camera_devices,
    check_camera_permission,
    generate_privacy_blocked_frame,
    open_windows_camera_settings,
    get_best_camera_index
)

logger = logging.getLogger("NEXUS.CameraWorker")


class DualHandModeState(enum.Enum):
    """Explicit state machine for automatic switching between Mouse and Air Keyboard modes."""
    MOUSE_MODE = "MOUSE_MODE"
    KEYBOARD_MODE = "KEYBOARD_MODE"
    SWITCHING_TO_MOUSE = "SWITCHING_TO_MOUSE"


@dataclass
class ControlPipelineStatus:
    """Carries full 5-stage diagnostic telemetry for real-time inspection."""
    hand_detected: bool
    hand_landmarks_count: int
    gesture_name: str
    system_state: str
    control_mode: str
    action_permitted: bool
    permission_reason: str
    last_action: str
    last_action_success: bool
    last_action_error: str
    cursor_coords: Tuple[int, int]
    fps: float
    camera_index: int
    cursor_sensitivity: float = 1.2
    fine_control_mode: bool = True
    click_state: str = "IDLE"
    is_cursor_stabilized: bool = False
    tracking_confidence: float = 0.0
    index_finger_state: str = "FOLDED"
    middle_finger_state: str = "FOLDED"
    ring_finger_state: str = "FOLDED"
    pinky_finger_state: str = "FOLDED"
    two_finger_status: str = "OFF"
    hand_label: str = "NONE"
    input_api: str = "SendInput (Win32)"
    scroll_status: str = "IDLE"
    mouse_movement_status: str = "ACTIVE"
    mouse_control_mode: str = "AIR_MOUSE"  # "AIR_MOUSE" | "PHYSICAL_MOUSE" | "TRACKING_LOST" | "PAUSED"
    detected_hand_count: int = 0
    dual_hand_mode_state: str = "MOUSE_MODE"
    mode_switch_countdown: float = 0.0
    last_mode_transition_reason: str = ""
    left_hand_detected: bool = False
    right_hand_detected: bool = False


class CameraWorker(QThread):
    """Worker thread running webcam capture, neural hand tracking, and virtual input mapping."""

    frame_ready = Signal(QImage, object, object)  # (QImage, HandLandmarkData or None, GestureState)
    multi_hands_ready = Signal(list)              # List[HandLandmarkData] (two-hand air typing)
    fps_measured = Signal(float)
    status_changed = Signal(str)
    camera_error = Signal(str)
    camera_permission_blocked = Signal(str)
    pipeline_updated = Signal(object)  # ControlPipelineStatus
    scroll_telemetry_ready = Signal(object)  # ScrollTelemetry

    def __init__(self,
                 camera_index: Optional[int] = None,
                 tracker: Optional[HandTracker] = None,
                 recognizer: Optional[GestureRecognizer] = None,
                 mouse: Optional[VirtualMouse] = None,
                 safety: Optional[SafetyController] = None,
                 launcher: Optional[AppLauncher] = None,
                 system_ctrl: Optional[SystemControls] = None,
                 mirror: bool = True,
                 show_hud: bool = True,
                 active_margins: tuple = (0.16, 0.16),
                 auto_activate_duration: float = 0.40,
                 auto_exit_duration: float = 0.80):
        super().__init__()
        if camera_index is None:
            try:
                self.camera_index = get_best_camera_index(0)
            except Exception:
                self.camera_index = 0
        else:
            self.camera_index = camera_index
        self.tracker = tracker or HandTracker(max_num_hands=2)
        self.recognizer = recognizer or GestureRecognizer()
        self.mouse = mouse or VirtualMouse()
        self.safety = safety or SafetyController()
        self.launcher = launcher or AppLauncher()
        self.system_ctrl = system_ctrl or SystemControls()
        self.scroll_controller = ScrollController(backend=self.mouse.backend)
        self.physical_mouse_detector = PhysicalMouseDetector(physical_priority_timeout=1.5, movement_threshold_px=12.0)
        self.mouse.conflict_resolver = self.physical_mouse_detector
        self.virtual_mouse_enabled: bool = True  # Manual toggle for virtual mouse control

        # Automatic Two-Hand Air Typing State Tracking
        self.auto_air_typing_enabled: bool = True
        self.auto_activate_duration: float = float(auto_activate_duration)  # Confirmation seconds for 2 hands (default 0.40s)
        self.auto_exit_duration: float = float(auto_exit_duration)          # Timeout when either hand disappears (default 0.80s)
        self._two_hands_start_time: Optional[float] = None
        self._hands_lost_start_time: Optional[float] = None
        self._auto_activated_keyboard: bool = False
        self.dual_hand_state: DualHandModeState = DualHandModeState.MOUSE_MODE
        self.last_mode_transition_reason: str = "SYSTEM_INITIALIZED"
        self.switching_countdown: float = 0.0
        self.detected_hand_count: int = 0

        # Wire up safety controller drag cancellation callback
        self.safety.cancel_drag_callback = self.mouse.release_drag

        # Hand tracking persistence (prevents unwanted hand switching in mouse control)
        self._primary_hand_label: str = "Right"

        # Automatic fist lock is disabled to prevent accidental lockouts during gesture control
        self.enable_fist_emergency_stop: bool = False

        self.mirror = mirror
        self.show_hud = show_hud
        self.active_margins = active_margins

        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None

        # Mode-specific gestures cooldowns
        self.last_app_cycle_time = 0.0
        self._low_fps_count = 0

    @staticmethod
    def get_available_cameras(max_tested: int = 4) -> List[int]:
        """Probes available video devices and returns valid indices, prioritizing physical cameras."""
        try:
            probed = probe_camera_devices()
            if probed:
                physical = [d["index"] for d in probed if not d.get("is_virtual", False)]
                virtual = [d["index"] for d in probed if d.get("is_virtual", False)]
                ordered = physical if physical else virtual
                if not ordered:
                    ordered = [0]
                seen = set()
                return [x for x in ordered if not (x in seen or seen.add(x))]
        except Exception as e:
            logger.debug(f"DirectShow probe error: {e}")

        return [0]

    def set_camera_index(self, index: int) -> None:
        """Changes the active camera index on the fly."""
        if self.camera_index != index:
            self.camera_index = index
            if self.isRunning():
                logger.info(f"Switching camera to index {index}...")
                self.restart_camera()

    def cycle_camera(self) -> int:
        """Cycles to next available camera index and restarts capture."""
        cams = self.get_available_cameras()
        if not cams:
            cams = [0]
        curr_idx = cams.index(self.camera_index) if self.camera_index in cams else 0
        next_idx = cams[(curr_idx + 1) % len(cams)]
        self.set_camera_index(next_idx)
        return next_idx

    def restart_camera(self) -> None:
        """Safely restarts capture device."""
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open_capture(self, index: int) -> Optional[cv2.VideoCapture]:
        """Attempts to open capture device using best available backend (CAP_DSHOW, CAP_MSMF, CAP_ANY)."""
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        for backend in backends:
            try:
                cap = cv2.VideoCapture(index, backend)
                if cap and cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    return cap
            except Exception:
                pass
        return None

    def update_dual_hand_mode_state(self, valid_hands: List[Any], now: Optional[float] = None) -> DualHandModeState:
        """Evaluates two-hand confirmation and hand-loss grace period to switch modes cleanly."""
        if now is None:
            now = time.time()
        num_hands = len(valid_hands)
        self.detected_hand_count = num_hands

        is_kb_mode = self.safety.current_mode in (ControlMode.KEYBOARD, ControlMode.HOLO_KEYBOARD, ControlMode.AIR_TYPING)

        # Sync if external mode change occurred (e.g. user toggled UI or shortcut)
        if not is_kb_mode and self.dual_hand_state in (DualHandModeState.KEYBOARD_MODE, DualHandModeState.SWITCHING_TO_MOUSE):
            self.dual_hand_state = DualHandModeState.MOUSE_MODE
            self._two_hands_start_time = None
            self._hands_lost_start_time = None
            self.switching_countdown = 0.0
        elif is_kb_mode and self.dual_hand_state == DualHandModeState.MOUSE_MODE:
            self.dual_hand_state = DualHandModeState.KEYBOARD_MODE
            self._two_hands_start_time = None
            self._hands_lost_start_time = None
            self.switching_countdown = 0.0

        if self.auto_air_typing_enabled and not self.safety._is_emergency and self.safety.current_mode not in (ControlMode.EMERGENCY_STOP, ControlMode.PAUSED):
            if self.dual_hand_state == DualHandModeState.MOUSE_MODE:
                self.switching_countdown = 0.0
                if num_hands >= 2:
                    if self._two_hands_start_time is None:
                        self._two_hands_start_time = now
                    elif (now - self._two_hands_start_time) >= self.auto_activate_duration:
                        logger.info(f"[MODE SWITCH] Two valid hands confirmed for {self.auto_activate_duration:.2f}s -> KEYBOARD_MODE")
                        self.dual_hand_state = DualHandModeState.KEYBOARD_MODE
                        self.last_mode_transition_reason = f"TWO_HANDS_CONFIRMED ({self.auto_activate_duration:.2f}s)"
                        self._auto_activated_keyboard = True
                        self.safety.switch_mode(ControlMode.KEYBOARD, force=True)
                        if not self.safety.is_enabled:
                            self.safety.enable_control()
                        self._two_hands_start_time = None
                        self._hands_lost_start_time = None
                else:
                    self._two_hands_start_time = None

            elif self.dual_hand_state == DualHandModeState.KEYBOARD_MODE:
                self._two_hands_start_time = None
                if num_hands >= 2:
                    self._hands_lost_start_time = None
                    self.switching_countdown = 0.0
                else:
                    # Either hand disappeared! Begin SWITCHING_TO_MOUSE grace countdown
                    self.dual_hand_state = DualHandModeState.SWITCHING_TO_MOUSE
                    self._hands_lost_start_time = now
                    self.switching_countdown = self.auto_exit_duration
                    self.last_mode_transition_reason = f"HAND_DISAPPEARED ({num_hands} of 2 hands detected)"
                    logger.info(f"[MODE SWITCH] Hand loss detected ({num_hands} hands). Grace period {self.auto_exit_duration:.2f}s started -> SWITCHING_TO_MOUSE")

            elif self.dual_hand_state == DualHandModeState.SWITCHING_TO_MOUSE:
                self._two_hands_start_time = None
                if num_hands >= 2:
                    # Missing hand returned within grace period! Recover immediately!
                    logger.info("[MODE SWITCH] Second hand returned during grace period -> Recovered to KEYBOARD_MODE")
                    self.dual_hand_state = DualHandModeState.KEYBOARD_MODE
                    self._hands_lost_start_time = None
                    self.switching_countdown = 0.0
                    self.last_mode_transition_reason = "TWO_HANDS_RESTORED"
                else:
                    loss_elapsed = now - (self._hands_lost_start_time if self._hands_lost_start_time is not None else now)
                    self.switching_countdown = max(0.0, self.auto_exit_duration - loss_elapsed)
                    if loss_elapsed >= self.auto_exit_duration:
                        logger.info(f"[MODE SWITCH] Timeout {self.auto_exit_duration:.2f}s expired without 2 hands -> Returning to MOUSE_MODE")
                        self.dual_hand_state = DualHandModeState.MOUSE_MODE
                        self.last_mode_transition_reason = f"TIMEOUT_EXPIRED ({self.auto_exit_duration:.2f}s without 2 hands)"
                        self._hands_lost_start_time = None
                        self.switching_countdown = 0.0
                        self._auto_activated_keyboard = False
                        self.safety.switch_mode(ControlMode.MOUSE, force=True)

        return self.dual_hand_state

    _update_dual_hand_mode_state = update_dual_hand_mode_state

    def run(self) -> None:
        """Main camera acquisition and gesture execution loop."""
        self._running = True
        logger.info(f"Starting camera capture thread on device index {self.camera_index}...")

        # 1. Proactively test Windows Camera Privacy permission
        has_perm, perm_reason = check_camera_permission(self.camera_index)
        if not has_perm:
            err_msg = (
                f"Windows Camera Privacy is blocking optical sensor {self.camera_index}. "
                "Open Windows Settings -> Privacy & security -> Camera -> Turn ON 'Let desktop apps access your camera'."
            )
            logger.warning(f"[CAMERA ACCESS] {err_msg}")
            self.camera_permission_blocked.emit(err_msg)
            self.status_changed.emit("WINDOWS CAMERA PERMISSION BLOCKED (0x80070005)")

            # Display animated high-tech HUD security notification and retry in background
            frame_tick = 0
            while self._running:
                hud_frame = generate_privacy_blocked_frame(width=640, height=480, frame_count=frame_tick)
                rgb_hud = cv2.cvtColor(hud_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_hud.shape
                q_img = QImage(rgb_hud.data, w, h, ch * w, QImage.Format_RGB888).copy()
                self.frame_ready.emit(q_img, None, GestureState(gesture=GestureType.NONE))
                self.fps_measured.emit(1.0)
                frame_tick += 1

                # Every 1 second (20 ticks @ 50ms), attempt to acquire the sensor
                if frame_tick % 20 == 0:
                    has_perm_now, _ = check_camera_permission(self.camera_index)
                    if has_perm_now:
                        self._cap = self._open_capture(self.camera_index)
                        if self._cap and self._cap.isOpened():
                            logger.info(f"Windows Camera permission granted! Hardware optical sensor {self.camera_index} online.")
                            self.status_changed.emit("CAMERA ONLINE - OPTICAL SENSORS ACTIVE")
                            break
                time.sleep(0.05)

        if not self._running:
            return

        # 2. Open camera using DirectShow / MSMF
        if self._cap is None or not self._cap.isOpened():
            self._cap = self._open_capture(self.camera_index)

        if self._cap is None or not self._cap.isOpened():
            err_msg = f"Webcam [Index {self.camera_index}] could not be opened. Check device connection or privacy permissions."
            logger.error(err_msg)
            self.camera_error.emit(err_msg)
            self.status_changed.emit("CAMERA OFFLINE")
            self._running = False
            return

        self.status_changed.emit("CAMERA ONLINE - OPTICAL SENSORS ACTIVE")

        # Rolling FPS calculation
        prev_time = time.time()
        fps_history = []
        self._low_fps_count = 0
        frame_counter = 0

        while self._running:
            try:
                if self._cap is None or not self._cap.isOpened():
                    # Reopen attempt
                    self._cap = self._open_capture(self.camera_index)
                    if self._cap is None or not self._cap.isOpened():
                        time.sleep(0.5)
                        continue

                ret, frame = self._cap.read()
                if not ret or frame is None:
                    self.status_changed.emit("NO SIGNAL FROM SENSOR")
                    time.sleep(0.03)
                    continue

                # Mirror frame for natural interaction if configured
                if self.mirror:
                    frame = cv2.flip(frame, 1)

                # Measure real frame-to-frame FPS
                curr_time = time.time()
                dt = curr_time - prev_time
                prev_time = curr_time
                if dt > 0:
                    inst_fps = 1.0 / dt
                    fps_history.append(inst_fps)
                    if len(fps_history) > 20:
                        fps_history.pop(0)
                    avg_fps = sum(fps_history) / len(fps_history)
                    self.fps_measured.emit(avg_fps)

                    # Diagnostic check for virtual / degraded camera drivers (e.g. Vivo PC Suite feeding 1 FPS static)
                    if dt > 0.8:
                        self._low_fps_count += 1
                        if self._low_fps_count == 4:
                            logger.warning(
                                f"[CAMERA DIAGNOSTIC] Sensor {self.camera_index} framerate is very low ({avg_fps:.1f} FPS). "
                                "If the preview displays static noise, this is likely a virtual driver (such as Vivo PC Suite). "
                                "Click 'SWITCH SENSOR' in the header to switch to Camera 0, or check your laptop's privacy shutter."
                            )
                            self.status_changed.emit("STATIC/DEGRADED FEED - CLICK SWITCH SENSOR")
                    else:
                        self._low_fps_count = 0

                frame_counter += 1
                # Process hand landmarks with physical handedness mirror compensation and frame freshness
                hands = self.tracker.process_frame(
                    frame, is_mirrored=self.mirror, frame_id=frame_counter, timestamp=curr_time
                )
                now = time.time()

                # Filter fresh valid hands
                valid_hands = [
                    h for h in hands
                    if getattr(h, "confidence", 1.0) >= 0.45 and (
                        (hasattr(h, "landmarks_norm") and len(h.landmarks_norm) >= 21) or
                        (hasattr(h, "landmarks_pixel") and len(h.landmarks_pixel) >= 21) or
                        hasattr(h, "get_tracking_point")
                    )
                ]
                num_hands = len(valid_hands)
                self.detected_hand_count = num_hands

                primary_hand: Optional[HandLandmarkData] = None
                secondary_hand: Optional[HandLandmarkData] = None

                if num_hands >= 2:
                    # In Desktop Mouse mode, maintain hand persistence so the cursor does not abruptly jump
                    if self.safety.current_mode in (ControlMode.MOUSE, ControlMode.DESKTOP_CONTROL, ControlMode.DESKTOP):
                        pref = getattr(self, "_primary_hand_label", "Right")
                        matched = [h for h in valid_hands if getattr(h, "handedness", "") == pref]
                        if matched:
                            primary_hand = matched[0]
                            secondary_hand = [h for h in valid_hands if h is not primary_hand][0]
                        else:
                            r_hands = [h for h in valid_hands if getattr(h, "handedness", "") == "Right"]
                            if r_hands:
                                primary_hand = r_hands[0]
                                secondary_hand = [h for h in valid_hands if h is not primary_hand][0]
                            else:
                                sorted_hands = sorted(valid_hands, key=lambda h: h.get_tracking_point("wrist")[0] if hasattr(h, "get_tracking_point") else getattr(h, "x", 0.5))
                                primary_hand = sorted_hands[0]
                                secondary_hand = sorted_hands[1]
                    else:
                        sorted_hands = sorted(valid_hands, key=lambda h: h.get_tracking_point("wrist")[0] if hasattr(h, "get_tracking_point") else getattr(h, "x", 0.5))
                        primary_hand = sorted_hands[0]
                        secondary_hand = sorted_hands[1]

                    if primary_hand:
                        self._primary_hand_label = getattr(primary_hand, "handedness", "Right")
                    self.safety.on_hand_detected()
                elif num_hands == 1:
                    primary_hand = valid_hands[0]
                    self._primary_hand_label = getattr(primary_hand, "handedness", "Right")
                    self.safety.on_hand_detected()
                else:
                    self.safety.on_hand_lost()
                    # Do not reset mouse filters immediately on temporary 1-frame loss
                    if not getattr(self.safety, "is_hand_present", False):
                        self.mouse.reset_filter()
                    self.scroll_controller.stop_scrolling()
                    self.mouse.release_drag()

                # -------------------------------------------------------------
                # AUTOMATIC MODE SWITCHING STATE MACHINE (MOUSE / KEYBOARD)
                # -------------------------------------------------------------
                self.update_dual_hand_mode_state(valid_hands, now=now)

                # Gesture recognition
                gesture_state = self.recognizer.recognize(primary_hand)

                # Execute actions based on active mode & safety gates
                avg_fps = sum(fps_history) / len(fps_history) if fps_history else 0.0
                self._dispatch_actions(gesture_state, primary_hand, avg_fps)

                # Draw futuristic HUD overlay on frame
                if self.show_hud and primary_hand:
                    frame = self.tracker.draw_futuristic_hud(
                        frame=frame,
                        hand=primary_hand,
                        is_pinching=gesture_state.pinch_active,
                        is_dragging=gesture_state.is_dragging,
                        pinch_threshold=self.recognizer.pinch_threshold,
                        active_box_bounds=self.mouse.get_roi_bounds(),
                        tracking_landmark=self.recognizer.tracking_landmark,
                        relative_anchor=self.mouse.relative_anchor if self.mouse.cursor_mode == "relative" else None,
                        secondary_hand=secondary_hand,
                        scroll_telemetry=self.scroll_controller.get_telemetry(),
                        gesture_state=gesture_state
                    )

                # Convert OpenCV BGR to QImage for PySide6 rendering
                rgb_frame = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                q_image = QImage(rgb_frame, w, h, bytes_per_line, QImage.Format_RGB888).copy()

                # Emit frames to GUI thread
                self.multi_hands_ready.emit(valid_hands)
                self.frame_ready.emit(q_image, primary_hand, gesture_state)
            except Exception as e:
                logger.error(f"Error in optical sensor processing cycle: {e}", exc_info=True)
                time.sleep(0.03)

        # Cleanup on loop exit
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        logger.info("Camera capture loop terminated cleanly.")

    def _dispatch_actions(self, state: GestureState, hand: Optional[HandLandmarkData], fps: float = 0.0) -> ControlPipelineStatus:
        """Dispatches virtual desktop actions obeying the safety controller and mode."""
        permitted, reason = self.safety.check_action_permission()
        last_action = "STANDBY"
        action_success = True
        action_error = ""

        # 1. Emergency Gestures (Checked regardless of whether normal input is enabled)
        if state.gesture == GestureType.FIST_EMERGENCY and self.enable_fist_emergency_stop:
            self.scroll_controller.stop_scrolling()
            self.safety.emergency_stop(source="FIST GESTURE")
            self.mouse.process_frame(None, emergency=True)
            last_action = "EMERGENCY STOP (Fist Locked)"
            action_success = True
        elif state.gesture == GestureType.FIST_EMERGENCY:
            self.scroll_controller.stop_scrolling()
            self.mouse.process_frame(None, emergency=False)
            last_action = "RESTING HAND (Fist Neutral)"
            action_success = True
        elif not permitted:
            self.scroll_controller.stop_scrolling()
            # When control is not permitted or hand is absent, maintain safety and tracking loss
            self.mouse.process_frame(None, emergency=(self.safety.system_state == SystemState.EMERGENCY_STOP))
            if state.gesture in (GestureType.PINCH_LEFT_CLICK, GestureType.PINCH_RIGHT_CLICK):
                last_action = "BLOCKED: CLICK 'ENABLE CONTROL'"
            else:
                last_action = f"BLOCKED: {reason}"
            action_success = False
        else:
            mode = self.safety.current_mode
            # Check physical mouse priority
            physical_active = self.physical_mouse_detector.check_physical_activity()

            # 3. MODE: DESKTOP MOUSE MODE (Canonical Desktop Control)
            if mode in (ControlMode.MOUSE, ControlMode.DESKTOP_CONTROL, ControlMode.DESKTOP):
                th = self.recognizer.pinch_threshold
                use_norm = self.recognizer.pinch_normalized or (th > 0.18)
                pinch_dist = (hand.norm_pinch_distance if use_norm else hand.pinch_distance) if hand else None

                # Keep thresholds in sync with settings / recognizer
                self.mouse.pinch_threshold = self.recognizer.pinch_threshold
                self.mouse.candidate_threshold = self.recognizer.pinch_threshold + self.mouse.candidate_delta
                self.mouse.pinch_release_threshold = self.recognizer.pinch_release_threshold

                right_triggered = (state.gesture == GestureType.PINCH_RIGHT_CLICK)
                is_scroll_gesture = (state.gesture == GestureType.TWO_FINGER_SCROLL)
                scroll_dy = state.scroll_dy if is_scroll_gesture else 0.0

                is_virtual_clicking = self.mouse.state in (MouseState.PINCH_CANDIDATE, MouseState.CLICK_LOCKED, MouseState.DRAGGING)
                physical_active = self.physical_mouse_detector.check_physical_activity(is_virtual_clicking=is_virtual_clicking)

                if not self.virtual_mouse_enabled:
                    # Virtual mouse manually disabled: pause virtual cursor injection
                    self.scroll_controller.stop_scrolling()
                    m_state, m_coords, m_msg = self.mouse.process_frame(
                        norm_coords=None,
                        pinch_dist=None,
                        right_click_triggered=False,
                        scroll_dy=0.0,
                        is_drag_mode=False,
                        emergency=False,
                        timestamp=time.time(),
                        is_scroll_active=False
                    )
                    last_action = "VIRTUAL MOUSE DISABLED"
                    action_success = True
                    action_error = ""
                elif physical_active:
                    # Physical mouse priority: track internally, sync coords with physical mouse, but do NOT inject cursor moves
                    self.scroll_controller.stop_scrolling()
                    real_pos = self.physical_mouse_detector.get_real_cursor_pos()
                    self.mouse.curr_x = float(real_pos[0])
                    self.mouse.curr_y = float(real_pos[1])
                    if hasattr(self.mouse.point_filter, "reinitialize"):
                        self.mouse.point_filter.reinitialize(float(real_pos[0]), float(real_pos[1]), time.time())
                    last_action = "PHYSICAL MOUSE PRIORITY"
                    action_success = True
                    action_error = ""
                else:
                    # Authoritative continuous scroll processing
                    scroll_telem = self.scroll_controller.process_hand(
                        hand, is_scroll_gesture=is_scroll_gesture, now=time.time()
                    )
                    self.scroll_telemetry_ready.emit(scroll_telem)

                    m_state, m_coords, m_msg = self.mouse.process_frame(
                        norm_coords=state.cursor_coords,
                        pinch_dist=pinch_dist,
                        right_click_triggered=right_triggered,
                        scroll_dy=scroll_dy,
                        is_drag_mode=state.is_dragging,
                        emergency=False,
                        timestamp=time.time(),
                        is_scroll_active=self.scroll_controller.is_active
                    )
                    if m_coords:
                        self.physical_mouse_detector.notify_virtual_move(m_coords[0], m_coords[1])
                    last_action = m_msg or self.mouse.last_action_message
                    action_success = self.mouse.last_action_success
                    action_error = self.mouse.last_error

            # 4. MODE: APP LAUNCH MODE
            elif mode == ControlMode.APP_LAUNCH:
                self.scroll_controller.stop_scrolling()
                self.mouse.process_frame(None, emergency=False)
                now = time.time()
                # Scroll gesture in app launch mode cycles apps
                if state.gesture == GestureType.TWO_FINGER_SCROLL and abs(state.scroll_dy) > 0.02:
                    if now - self.last_app_cycle_time > 0.35:
                        if state.scroll_dy > 0:
                            self.launcher.next_app()
                        else:
                            self.launcher.prev_app()
                        self.last_app_cycle_time = now
                        sel_app = self.launcher.get_selected_app()
                        last_action = f"App Selected: {sel_app.get('name', 'App') if sel_app else 'None'}"
                        action_success = True

                # Pinch confirms launching selected app
                if state.gesture == GestureType.PINCH_LEFT_CLICK:
                    ok = self.launcher.launch_selected()
                    sel_app = self.launcher.get_selected_app()
                    app_name = sel_app.get('name', 'App') if sel_app else 'Unknown'
                    last_action = f"Launched '{app_name}'" if ok else f"Launch '{app_name}' FAILED"
                    action_success = ok

            # 5. MODE: SYSTEM CONTROL MODE
            elif mode in (ControlMode.SYSTEM_CONTROL, ControlMode.SYSTEM):
                self.mouse.process_frame(None, emergency=False)
                if state.gesture == GestureType.TWO_FINGER_SCROLL and abs(state.scroll_dy) > 0.015:
                    if state.scroll_dy < 0:
                        v = self.system_ctrl.volume_up(step=4)
                        last_action = f"Volume Up -> {v}%"
                    else:
                        v = self.system_ctrl.volume_down(step=4)
                        last_action = f"Volume Down -> {v}%"
                    action_success = True

                elif state.gesture == GestureType.SWIPE_RIGHT:
                    ok = self.system_ctrl.next_track()
                    last_action = "Media: Next Track"
                    action_success = ok

                elif state.gesture == GestureType.SWIPE_LEFT:
                    ok = self.system_ctrl.previous_track()
                    last_action = "Media: Previous Track"
                    action_success = ok

                elif state.gesture == GestureType.PINCH_LEFT_CLICK:
                    ok = self.system_ctrl.play_pause()
                    last_action = "Media: Play / Pause"
                    action_success = ok

                elif state.gesture == GestureType.PINCH_RIGHT_CLICK:
                    muted = self.system_ctrl.toggle_mute()
                    v = self.system_ctrl.get_volume()
                    last_action = "Audio MUTED" if muted else f"Audio UNMUTED ({v}%)"
                    action_success = True

            # 6. MODE: 3D LAB INTERACTIVE MODE (Hologram Control)
            elif mode in (ControlMode.LAB_3D, ControlMode.HOLOGRAM_CONTROL, ControlMode.HOLOGRAM):
                # Ensure mouse cursor remains locked/stationary during 3D hologram operations
                self.mouse.process_frame(None, emergency=False)
                if state.gesture == GestureType.TWO_FINGER_SCROLL:
                    last_action = f"3D Lab Zoom (dy={state.scroll_dy:.2f})"
                elif state.gesture == GestureType.SWIPE_RIGHT:
                    last_action = "3D Lab Next Scene"
                elif state.gesture == GestureType.SWIPE_LEFT:
                    last_action = "3D Lab Prev Scene"
                elif state.gesture == GestureType.PINCH_LEFT_CLICK:
                    last_action = "3D Lab Object Selected"
                elif state.gesture == GestureType.INDEX_POINT:
                    last_action = "3D Lab Object Highlighting"
                else:
                    last_action = "3D Lab Hologram Active"
                action_success = True

            # 7. MODE: PRESENTATION MODE
            elif mode == ControlMode.PRESENTATION:
                self.mouse.process_frame(None, emergency=False)
                if state.gesture in (GestureType.SWIPE_RIGHT, GestureType.PINCH_LEFT_CLICK) or (state.gesture == GestureType.TWO_FINGER_SCROLL and state.scroll_dy > 0.02):
                    ok = self.system_ctrl.next_slide()
                    last_action = "Presentation: Next Slide"
                    action_success = ok
                elif state.gesture in (GestureType.SWIPE_LEFT, GestureType.PINCH_RIGHT_CLICK) or (state.gesture == GestureType.TWO_FINGER_SCROLL and state.scroll_dy < -0.02):
                    ok = self.system_ctrl.previous_slide()
                    last_action = "Presentation: Previous Slide"
                    action_success = ok
                else:
                    last_action = "Presentation Mode Active"
                    action_success = True

            # 8. MODE: HOLOGRAPHIC KEYBOARD MODE / AIR TYPING
            elif mode in (ControlMode.KEYBOARD, ControlMode.HOLO_KEYBOARD, ControlMode.AIR_TYPING):
                # Ensure Windows desktop mouse cursor remains stationary and clicks are blocked
                self.mouse.process_frame(None, emergency=False)
                last_action = "AIR TYPING / Holographic Keyboard Active"
                action_success = True

        status = ControlPipelineStatus(
            hand_detected=(hand is not None),
            hand_landmarks_count=len(hand.landmarks_norm) if (hand and hasattr(hand, "landmarks_norm")) else 0,
            gesture_name=state.gesture.value,
            system_state=self.safety.system_state.value,
            control_mode=self.safety.current_mode.value,
            action_permitted=permitted,
            permission_reason=reason,
            last_action=last_action,
            last_action_success=action_success,
            last_action_error=action_error,
            cursor_coords=(int(round(self.mouse.curr_x)), int(round(self.mouse.curr_y))),
            fps=fps,
            camera_index=self.camera_index,
            cursor_sensitivity=self.mouse.effective_sensitivity,
            fine_control_mode=self.mouse.fine_control_mode,
            click_state=self.mouse.click_state_name,
            is_cursor_stabilized=self.mouse.is_stabilized,
            tracking_confidence=getattr(hand, "confidence", 0.0) if hand else 0.0,
            index_finger_state=state.finger_states.get("index", "FOLDED") if state else "FOLDED",
            middle_finger_state=state.finger_states.get("middle", "FOLDED") if state else "FOLDED",
            ring_finger_state=state.finger_states.get("ring", "FOLDED") if state else "FOLDED",
            pinky_finger_state=state.finger_states.get("pinky", "FOLDED") if state else "FOLDED",
            two_finger_status=getattr(state, "two_finger_stability_status", "OFF") if state else "OFF",
            hand_label=getattr(state, "hand_label", (hand.handedness if hand else "NONE")),
            input_api=getattr(self.mouse, "input_api", "SendInput (Win32)"),
            scroll_status=getattr(self.scroll_controller, "current_direction", None).value if getattr(self.scroll_controller, "is_active", False) and getattr(self.scroll_controller, "current_direction", None) else "IDLE",
            mouse_movement_status="LOCKED" if getattr(self.mouse, "is_stabilized", False) else ("ACTIVE" if hand is not None else "IDLE"),
            mouse_control_mode=(
                "MOUSE PAUSED" if (not self.virtual_mouse_enabled or self.safety.system_state == SystemState.PAUSED)
                else ("PHYSICAL MOUSE ACTIVE" if self.physical_mouse_detector.is_physical_active
                else ("TRACKING LOST" if hand is None
                else "AIR MOUSE ACTIVE"))
            ),
            detected_hand_count=self.detected_hand_count,
            dual_hand_mode_state=self.dual_hand_state.value,
            mode_switch_countdown=round(self.switching_countdown, 2),
            last_mode_transition_reason=self.last_mode_transition_reason,
            left_hand_detected=(self.detected_hand_count >= 2 or (self.detected_hand_count == 1 and getattr(hand, "handedness", "") == "Left")),
            right_hand_detected=(self.detected_hand_count >= 2 or (self.detected_hand_count == 1 and getattr(hand, "handedness", "") == "Right"))
        )
        self.pipeline_updated.emit(status)
        return status

    def stop(self) -> None:
        """Signals the worker thread to stop and waits for it to exit."""
        self._running = False
        try:
            self.scroll_controller.stop_scrolling()
            self.mouse.release_drag()
        except Exception:
            pass
        self.wait(1500)
        if self.isRunning():
            self.terminate()
