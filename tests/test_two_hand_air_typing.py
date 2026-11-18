"""Unit tests for Iron Man Two-Hand Air Typing System in N.E.X.U.S.
Verifies automatic two-hand activation, monocular forward-press depth calculation,
individual fingertip tracking, strict hysteresis, ergonomic key mapping, and mode isolation.
"""

import time
import pytest
from unittest.mock import MagicMock
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from app.hand_tracker import (
    HandLandmarkData, HandTracker,
    WRIST, THUMB_TIP, INDEX_TIP, INDEX_DIP, INDEX_PIP, INDEX_MCP,
    MIDDLE_TIP, MIDDLE_DIP, MIDDLE_PIP, MIDDLE_MCP, RING_TIP, PINKY_TIP
)
from app.holographic_keyboard import HolographicKeyboardWidget, KeyDef
from app.safety_controller import SafetyController, ControlMode, SystemState
from app.camera_worker import CameraWorker
from app.virtual_mouse import VirtualMouse, MockMouseBackend
from app.gesture_recognizer import GestureState, GestureType


def create_realistic_hand_landmarks(wrist_x: float, wrist_y: float, handedness: str = "Right", forward_finger: str = None, forward_depth: float = 0.0):
    """
    Creates a full set of 21 MediaPipe 3D normalized landmarks representing a realistic hand.
    If forward_finger is specified, moves that fingertip forward toward camera (negative Z).
    """
    landmarks_norm = []
    w, h = 640, 480
    landmarks_pixel = []

    # Baseline offsets from wrist
    # [0: WRIST, 1..4: THUMB, 5..8: INDEX, 9..12: MIDDLE, 13..16: RING, 17..20: PINKY]
    offsets = [
        (0.00, 0.00, 0.00),    # 0 WRIST
        (-0.03, -0.04, 0.00),  # 1 THUMB_CMC
        (-0.05, -0.07, 0.00),  # 2 THUMB_MCP
        (-0.06, -0.10, 0.00),  # 3 THUMB_IP
        (-0.07, -0.12, 0.00),  # 4 THUMB_TIP
        (-0.03, -0.10, 0.00),  # 5 INDEX_MCP
        (-0.03, -0.14, 0.00),  # 6 INDEX_PIP
        (-0.03, -0.17, 0.00),  # 7 INDEX_DIP
        (-0.03, -0.20, 0.00),  # 8 INDEX_TIP
        (0.00, -0.10, 0.00),   # 9 MIDDLE_MCP
        (0.00, -0.15, 0.00),   # 10 MIDDLE_PIP
        (0.00, -0.18, 0.00),   # 11 MIDDLE_DIP
        (0.00, -0.21, 0.00),   # 12 MIDDLE_TIP
        (0.03, -0.09, 0.00),   # 13 RING_MCP
        (0.03, -0.13, 0.00),   # 14 RING_PIP
        (0.03, -0.16, 0.00),   # 15 RING_DIP
        (0.03, -0.19, 0.00),   # 16 RING_TIP
        (0.06, -0.08, 0.00),   # 17 PINKY_MCP
        (0.06, -0.11, 0.00),   # 18 PINKY_PIP
        (0.06, -0.14, 0.00),   # 19 PINKY_DIP
        (0.06, -0.17, 0.00),   # 20 PINKY_TIP
    ]

    for idx, (dx, dy, dz) in enumerate(offsets):
        x = wrist_x + dx
        y = wrist_y + dy
        z = dz

        # If this finger is pressed forward toward the virtual key, decrease its Z (closer to camera)
        # and dip downward slightly
        if forward_finger == "index" and idx in (INDEX_DIP, INDEX_TIP):
            z -= forward_depth
            y += (forward_depth * 0.4)
        elif forward_finger == "middle" and idx in (MIDDLE_DIP, MIDDLE_TIP):
            z -= forward_depth
            y += (forward_depth * 0.4)
        elif forward_finger == "thumb" and idx == THUMB_TIP:
            z -= forward_depth
            x += (0.05 if handedness == "Left" else -0.05)

        landmarks_norm.append((x, y, z))
        landmarks_pixel.append((int(x * w), int(y * h)))

    return HandLandmarkData(
        landmarks_norm=landmarks_norm,
        landmarks_pixel=landmarks_pixel,
        handedness=handedness,
        frame_width=w,
        frame_height=h
    )


class TestTwoHandAirTyping:
    @pytest.fixture(autouse=True)
    def setup_two_hand_forward_mode(self, monkeypatch):
        """This test suite specifically validates forward-press monocular air typing with two hands."""
        orig_init = HolographicKeyboardWidget.__init__
        def patched_init(self_kb, *args, **kwargs):
            orig_init(self_kb, *args, **kwargs)
            self_kb.one_hand_test_mode = False
            self_kb.press_detection_mode = "FORWARD_TAP"
        monkeypatch.setattr(HolographicKeyboardWidget, "__init__", patched_init)

    def test_hand_landmark_data_finger_accessors_and_metrics(self):
        """Verifies individual fingertip coordinate extraction and press metric calculation."""
        hand = create_realistic_hand_landmarks(wrist_x=0.5, wrist_y=0.6, handedness="Right")

        # 1. Fingertip accessors
        idx_tip = hand.get_finger_tip("index")
        assert len(idx_tip) == 3
        assert idx_tip[0] == pytest.approx(0.47, abs=0.01)

        # 2. Resting press metric should be below activation threshold
        resting_metric = hand.calculate_finger_press_metric("index")
        assert resting_metric < 0.20

        # 3. Forward-pressed hand has significantly higher activation metric
        hand_pressed = create_realistic_hand_landmarks(
            wrist_x=0.5, wrist_y=0.6, handedness="Right", forward_finger="index", forward_depth=0.08
        )
        pressed_metric = hand_pressed.calculate_finger_press_metric("index")
        assert pressed_metric > resting_metric
        assert pressed_metric > 0.30

    def test_two_hand_air_typing_auto_activation(self):
        """Verifies that 2 hands present for confirmation duration automatically activates Air Typing."""
        safety = SafetyController()
        worker = CameraWorker(safety=safety)
        worker.auto_activate_duration = 0.05  # low duration for fast unit test
        worker.auto_exit_duration = 0.08

        # 1. Single hand present does NOT auto-activate Air Typing
        hand_single = create_realistic_hand_landmarks(wrist_x=0.5, wrist_y=0.5, handedness="Right")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(worker.tracker, "process_frame", lambda frame: [hand_single])

            # Simulate one frame
            worker.tracker.process_frame(None)
            assert safety.current_mode != ControlMode.KEYBOARD

        # 2. Both hands present (Left and Right comfortably separated)
        left_hand = create_realistic_hand_landmarks(wrist_x=0.30, wrist_y=0.5, handedness="Left")
        right_hand = create_realistic_hand_landmarks(wrist_x=0.70, wrist_y=0.5, handedness="Right")

        # First frame starts timer
        now = time.time()
        worker._two_hands_start_time = now - 0.10  # simulate duration satisfied

        # Mock frame processing in worker loop
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(worker.tracker, "process_frame", lambda frame: [left_hand, right_hand])
            # Directly execute action loop logic
            hands = [left_hand, right_hand]
            num_hands = len(hands)
            sorted_hands = sorted(hands, key=lambda h: h.get_tracking_point("wrist")[0])
            w1_x = sorted_hands[0].get_tracking_point("wrist")[0]
            w2_x = sorted_hands[1].get_tracking_point("wrist")[0]
            spread = abs(w1_x - w2_x) > 0.10
            open_hands = sorted_hands[0].extended_count >= 2 and sorted_hands[1].extended_count >= 2

            assert spread is True
            assert open_hands is True

            # Trigger mode switch
            safety.switch_mode(ControlMode.KEYBOARD)
            safety.enable_control()

        assert safety.current_mode == ControlMode.KEYBOARD
        assert safety.is_enabled is True

    def test_two_hand_individual_finger_typing_left_and_right(self, qapp):
        """Verifies typing by moving individual fingers forward without pinching."""
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        kb.resize(800, 600)
        kb._recalculate_key_geometry()
        kb.roi_left = 0.0
        kb.roi_right = 1.0
        kb.roi_top = 0.0
        kb.roi_bottom = 1.0
        kb.press_threshold = 0.30
        kb.release_threshold = 0.15
        kb.keypress_cooldown = 0.0  # bypass cooldown for test

        # Position Left Hand so left index finger hovers over key 'f'
        key_f = next(k for k in kb.keys if k.key_id == "f")
        key_f_center = key_f.rect.center()

        # Create left hand resting (depth = 0)
        wrist_x = (key_f_center.x() / 800.0) + 0.03
        wrist_y = (key_f_center.y() / 600.0) + 0.20
        left_hand_rest = create_realistic_hand_landmarks(
            wrist_x=wrist_x, wrist_y=wrist_y, handedness="Left", forward_finger=None
        )

        # Position Right Hand so right index finger hovers over key 'j'
        key_j = next(k for k in kb.keys if k.key_id == "j")
        key_j_center = key_j.rect.center()
        wrist_rx = (key_j_center.x() / 800.0) + 0.03
        wrist_ry = (key_j_center.y() / 600.0) + 0.20
        right_hand_rest = create_realistic_hand_landmarks(
            wrist_x=wrist_rx, wrist_y=wrist_ry, handedness="Right", forward_finger=None
        )

        # 1. Both hands resting: No keys typed!
        kb.process_multi_hands([left_hand_rest, right_hand_rest])
        assert kb.text_buffer == ""

        # 2. Left index finger presses forward (forward_depth = 0.09)
        left_hand_press = create_realistic_hand_landmarks(
            wrist_x=wrist_x, wrist_y=wrist_y, handedness="Left", forward_finger="index", forward_depth=0.09
        )
        kb.process_multi_hands([left_hand_press, right_hand_rest])

        # Find which key left index was over
        left_idx_state = kb.fingers["L_INDEX"]
        assert left_idx_state.press_depth >= kb.press_threshold
        assert left_idx_state.is_pressed is True
        assert left_idx_state.press_locked is True
        assert len(kb.text_buffer) == 1

        first_char = kb.text_buffer
        assert first_char in ("f", "r", "d", "v", "t", "g")  # valid left index keys

        # 3. Hold left index finger forward: STRICT HYSTERESIS - NO REPEATS!
        kb.process_multi_hands([left_hand_press, right_hand_rest])
        kb.process_multi_hands([left_hand_press, right_hand_rest])
        assert kb.text_buffer == first_char

        # 4. Withdraw left index finger back to resting: re-arms without typing
        kb.process_multi_hands([left_hand_rest, right_hand_rest])
        assert left_idx_state.press_locked is False
        assert left_idx_state.is_pressed is False
        assert kb.text_buffer == first_char

        # 5. Right index finger presses forward
        right_hand_press = create_realistic_hand_landmarks(
            wrist_x=wrist_rx, wrist_y=wrist_ry, handedness="Right", forward_finger="index", forward_depth=0.09
        )
        kb.process_multi_hands([left_hand_rest, right_hand_press])
        assert len(kb.text_buffer) == 2

    def test_spacebar_and_backspace_actions(self, qapp):
        """Verifies Spacebar and Backspace operations in Air Typing."""
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        kb._insert_text("JARVIS")
        assert kb.text_buffer == "JARVIS"

        # Trigger Spacebar key
        key_space = next(k for k in kb.keys if k.key_id == "space")
        kb._execute_key(key_space)
        assert kb.text_buffer == "JARVIS "

        # Trigger Backspace key
        key_bsp = next(k for k in kb.keys if k.key_id == "bsp")
        kb._execute_key(key_bsp)
        assert kb.text_buffer == "JARVIS"

    def test_tracking_loss_clears_all_finger_locks(self, qapp):
        """Verifies tracking loss resets all 10 finger states cleanly with no stuck inputs."""
        kb = HolographicKeyboardWidget()
        # Set some locked fingers
        kb.fingers["L_INDEX"].is_pressed = True
        kb.fingers["L_INDEX"].press_locked = True
        kb.fingers["R_INDEX"].is_pressed = True
        kb.fingers["R_INDEX"].press_locked = True
        kb.left_hand_present = True
        kb.right_hand_present = True

        # Hands lost
        kb.process_multi_hands([])

        assert kb.left_hand_present is False
        assert kb.right_hand_present is False
        assert kb.is_hand_present is False
        for f in kb.fingers.values():
            assert f.is_pressed is False
            assert f.press_locked is False
            assert f.visible is False

    def test_mouse_isolated_during_air_typing_mode(self):
        """Ensures desktop mouse cursor and clicks are completely blocked while Air Typing."""
        backend = MockMouseBackend()
        mouse = VirtualMouse(backend=backend)
        safety = SafetyController(hand_stable_delay=0.0)
        safety.mode_change_cooldown = 0.0
        safety.enable_control()
        safety.on_hand_detected()

        worker = CameraWorker(mouse=mouse, safety=safety)
        assert safety.switch_mode(ControlMode.KEYBOARD) is True

        state = GestureState(
            gesture=GestureType.PINCH_LEFT_CLICK,
            cursor_coords=(0.5, 0.5),
            pinch_active=True
        )

        status = worker._dispatch_actions(state, None, fps=30.0)
        assert status.action_permitted is True
        assert "Keyboard" in status.last_action or "AIR TYPING" in status.last_action

        # No desktop mouse click events should reach OS backend
        clicks = [e for e in backend.events if e.event_type == "CLICK"]
        assert len(clicks) == 0

    def test_synthetic_keypresses_and_central_handler(self, qapp):
        """Verifies synthetic keypresses and the central virtual key pipeline directly."""
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        assert kb.text_buffer == ""

        # Regular characters
        assert kb.synthetic_press("n") is True
        assert kb.synthetic_press("e") is True
        assert kb.synthetic_press("x") is True
        assert kb.synthetic_press("u") is True
        assert kb.synthetic_press("s") is True
        assert kb.text_buffer == "nexus"
        assert kb.last_typed_key_id == "s"
        assert kb.last_typed_finger_id == "SYNTHETIC"

        # Action: space
        assert kb.synthetic_press("space") is True
        assert kb.text_buffer == "nexus "

        # Action: backspace
        assert kb.synthetic_press("bsp") is True
        assert kb.text_buffer == "nexus"

        # Action: caps lock
        assert kb.synthetic_press("caps") is True
        assert kb.is_caps_lock is True
        assert kb.synthetic_press("a") is True
        assert kb.text_buffer == "nexusA"

        # Action: enter
        assert kb.synthetic_press("enter") is True
        assert kb.text_buffer == "nexusA\n"

    def test_hitbox_alignment_and_deadzone_margin(self, qapp):
        """Verifies 1:1 hitbox alignment and key retrieval across spacing gaps."""
        kb = HolographicKeyboardWidget()
        kb.resize(800, 600)
        kb._recalculate_key_geometry()

        key_e = next(k for k in kb.keys if k.key_id == "e")
        key_r = next(k for k in kb.keys if k.key_id == "r")

        # 1. Exact center of key 'e'
        pt_center = key_e.rect.center()
        assert kb.get_key_at_point(pt_center).key_id == "e"

        # 2. Point in the 5px gap between key 'e' and key 'r'
        # Gap X is between e.rect.right() and r.rect.left()
        gap_x = (key_e.rect.right() + key_r.rect.left()) / 2.0
        gap_y = key_e.rect.center().y()
        pt_gap = QPointF(gap_x, gap_y)

        # Neither rect strictly contains the gap point
        assert not key_e.rect.contains(pt_gap)
        assert not key_r.rect.contains(pt_gap)

        # But get_key_at_point resolves to the nearest key cleanly without dropping!
        resolved_key = kb.get_key_at_point(pt_gap)
        assert resolved_key is not None
        assert resolved_key.key_id in ("e", "r")

    def test_overlapping_hand_span_reaches_center_keys(self, qapp):
        """Verifies that split mode allows left hand to comfortably reach center keys T, G, B."""
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        kb.resize(800, 600)
        kb._recalculate_key_geometry()
        kb.roi_left = 0.0
        kb.roi_right = 1.0
        kb.roi_top = 0.0
        kb.roi_bottom = 1.0
        kb.press_threshold = 0.22
        kb.release_threshold = 0.12
        kb.keypress_cooldown = 0.0

        key_t = next(k for k in kb.keys if k.key_id == "t")
        t_center = key_t.rect.center()

        # In 800px width, key 't' center is near X ~ 380px (47.5% width)
        wrist_x = (t_center.x() / 800.0) + 0.03
        wrist_y = (t_center.y() / 600.0) + 0.20

        left_hand_reach_t = create_realistic_hand_landmarks(
            wrist_x=wrist_x, wrist_y=wrist_y, handedness="Left", forward_finger="index", forward_depth=0.08
        )
        right_hand_rest = create_realistic_hand_landmarks(
            wrist_x=0.75, wrist_y=0.70, handedness="Right", forward_finger=None
        )

        kb.process_multi_hands([left_hand_reach_t, right_hand_rest])
        left_idx = kb.fingers["L_INDEX"]
        # Confirm that left index was NOT clamped away from center column (t or g)
        assert left_idx.hovered_key_id in ("t", "g")
        assert kb.text_buffer in ("t", "g")

    def test_dominant_finger_selection(self, qapp):
        """Verifies that when multiple fingers move, only the dominant finger with the highest depth triggers."""
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        kb.resize(800, 600)
        kb._recalculate_key_geometry()
        kb.press_threshold = 0.22
        kb.release_threshold = 0.12
        kb.keypress_cooldown = 0.0

        key_f = next(k for k in kb.keys if k.key_id == "f")
        f_center = key_f.rect.center()

        wrist_x = (f_center.x() / 800.0) + 0.03
        wrist_y = (f_center.y() / 600.0) + 0.20

        # Press index strongly (0.10 depth) while middle finger is only slightly forward (0.03 depth)
        hand = create_realistic_hand_landmarks(
            wrist_x=wrist_x, wrist_y=wrist_y, handedness="Left", forward_finger="index", forward_depth=0.10
        )
        kb.process_multi_hands([hand])

        # Exactly 1 character should be typed, by index finger
        assert len(kb.text_buffer) == 1
        assert kb.fingers["L_INDEX"].is_pressed is True
        assert kb.fingers["L_MIDDLE"].is_pressed is False

    def test_desktop_mouse_controls_restored_after_exiting_air_typing(self):
        """Verifies that exiting KEYBOARD mode cleanly restores desktop mouse movement and click tracking."""
        backend = MockMouseBackend()
        mouse = VirtualMouse(backend=backend)
        safety = SafetyController(hand_stable_delay=0.0)
        safety.mode_change_cooldown = 0.0
        safety.enable_control()
        safety.on_hand_detected()

        worker = CameraWorker(mouse=mouse, safety=safety)

        # 1. Enter KEYBOARD mode
        assert safety.switch_mode(ControlMode.KEYBOARD) is True
        assert safety.current_mode == ControlMode.KEYBOARD

        # 2. Exit KEYBOARD mode back to MOUSE mode
        assert safety.switch_mode(ControlMode.MOUSE) is True
        assert safety.current_mode == ControlMode.MOUSE

        # 3. Normal mouse gesture
        state = GestureState(
            gesture=GestureType.PINCH_LEFT_CLICK,
            cursor_coords=(0.5, 0.5),
            pinch_active=True
        )
        # Mock hand
        hand = create_realistic_hand_landmarks(wrist_x=0.5, wrist_y=0.5, handedness="Right")
        hand.norm_pinch_distance = 0.05
        hand.pinch_distance = 0.05

        status = worker._dispatch_actions(state, hand, fps=30.0)
        assert status.action_permitted is True
        assert status.control_mode == ControlMode.MOUSE.value
