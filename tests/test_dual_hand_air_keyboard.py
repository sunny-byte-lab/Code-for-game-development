"""Unit tests for Two-Hand Holographic Air Typing, Handedness Mirroring,
5-Stage Hysteresis State Machine, Neutral Posture Calibration, and Test Mode.
"""

import time
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.hand_tracker import HandTracker, HandLandmarkData
from app.holographic_keyboard import HolographicKeyboardWidget, FingerPressState
from app.windows_keyboard_service import WindowsKeyboardInputService, MockKeyboardBackend
from app.virtual_mouse import VirtualMouse
from app.scroll_controller import ScrollController


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    yield app


def make_mock_landmarks(wrist_x=0.5, wrist_y=0.8, wrist_z=0.0,
                        index_tip_x=0.5, index_tip_y=0.4, index_tip_z=-0.05,
                        dip_y=0.5, pip_y=0.6, mcp_y=0.7):
    """Constructs a 21-element list of normalized landmark tuples (x, y, z)."""
    lms = []
    for i in range(21):
        if i == 0:
            lms.append((wrist_x, wrist_y, wrist_z))
        elif i == 8:
            lms.append((index_tip_x, index_tip_y, index_tip_z))
        elif i == 7:
            lms.append((index_tip_x, dip_y, -0.02))
        elif i == 6:
            lms.append((index_tip_x, pip_y, -0.01))
        elif i == 5:
            lms.append((index_tip_x, mcp_y, 0.0))
        else:
            lms.append((wrist_x + 0.01 * i, wrist_y - 0.02 * i, 0.0))
    return lms


def create_test_hand(lms, handedness="Right", conf=0.95, h_conf=0.95):
    """Helper to instantiate HandLandmarkData with standard frame dimensions."""
    return HandLandmarkData(
        landmarks_norm=lms,
        landmarks_pixel=[(int(p[0] * 1280), int(p[1] * 720)) for p in lms],
        handedness=handedness,
        frame_width=1280,
        frame_height=720,
        confidence=conf,
        handedness_confidence=h_conf
    )


class TestDualHandTrackingAndMirroring:
    """Verifies that physical handedness is accurate under camera mirroring."""

    def test_handedness_mirror_inversion(self):
        """When webcam frame is horizontally mirrored, MediaPipe's raw classification
        must be inverted to correctly match the user's physical hand."""
        tracker = HandTracker()

        mock_mp_hand = MagicMock()
        mock_mp_hand.landmark = [MagicMock(x=0.5, y=0.5, z=0.0) for _ in range(21)]

        mock_classification = MagicMock()
        mock_classification.label = "Left"
        mock_classification.score = 0.98

        mock_handedness = MagicMock()
        mock_handedness.classification = [mock_classification]

        mock_results = MagicMock()
        mock_results.multi_hand_landmarks = [mock_mp_hand]
        mock_results.multi_handedness = [mock_handedness]

        with patch.object(tracker.hands, "process", return_value=mock_results):
            # Test with is_mirrored=True (default webcam setting)
            hands_mirrored = tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8), is_mirrored=True)
            assert len(hands_mirrored) == 1
            assert hands_mirrored[0].handedness == "Right"
            assert hands_mirrored[0].handedness_confidence == 0.98

            # Test with is_mirrored=False (unmirrored feed preserves raw classification)
            hands_raw = tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8), is_mirrored=False)
            assert len(hands_raw) == 1
            assert hands_raw[0].handedness == "Left"

    def test_dual_hand_spatial_separation(self, qapp):
        """Verifies that the holographic keyboard correctly separates and maps left and right hands."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        # Create two hands: Left hand (wrist_x = 0.25), Right hand (wrist_x = 0.75)
        hand_left = create_test_hand(
            make_mock_landmarks(wrist_x=0.25, index_tip_x=0.28, index_tip_y=0.5),
            handedness="Left",
            conf=0.96,
            h_conf=0.95
        )
        hand_right = create_test_hand(
            make_mock_landmarks(wrist_x=0.75, index_tip_x=0.72, index_tip_y=0.5),
            handedness="Right",
            conf=0.94,
            h_conf=0.93
        )

        # Feed both hands into process_multi_hands (even in reverse order)
        kb.process_multi_hands([hand_right, hand_left])

        assert kb.left_detected is True
        assert kb.right_detected is True
        assert kb.left_tracking_conf == 0.96
        assert kb.right_tracking_conf == 0.94
        assert kb.left_handedness_conf == 0.95
        assert kb.right_handedness_conf == 0.93


class TestHysteresisAndTyping:
    """Verifies that resting hands produce zero machine-gun presses,
    5-stage hysteresis operates cleanly, and Test Mode prevents OS input."""

    def test_resting_hand_produces_zero_presses(self, qapp):
        """A resting, stationary hand held in view must have calibrated depth near 0.0
        and NEVER trigger automatic keystrokes."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb.test_mode = True

        resting_lms = make_mock_landmarks(
            wrist_x=0.7, wrist_y=0.8,
            index_tip_x=0.7, index_tip_y=0.45, index_tip_z=0.0,
            dip_y=0.50, pip_y=0.58, mcp_y=0.68
        )
        hand = create_test_hand(resting_lms, handedness="Right", conf=0.95, h_conf=0.95)

        initial_count = kb.total_keystrokes

        # Feed 30 consecutive resting frames
        for _ in range(30):
            kb.process_multi_hands([hand])

        # Keystroke count must remain exactly 0
        assert kb.total_keystrokes == initial_count
        assert kb.fingers["R_INDEX"].state in (FingerPressState.IDLE, FingerPressState.HOVERING)
        assert kb.fingers["R_INDEX"].is_pressed is False

    def test_five_stage_hysteresis_state_machine(self, qapp):
        """Verifies full state cycle: IDLE -> HOVERING -> CANDIDATE -> PRESSED -> RELEASE_WAIT -> HOVERING."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True
        kb.press_detection_mode = "FORWARD_TAP"
        kb.one_hand_test_mode = False

        f_state = kb.fingers["R_INDEX"]
        f_state.baseline_depth = 0.10

        # Position fingertip directly over key 'J' (x=0.56, y=0.66)
        lms_hover = make_mock_landmarks(wrist_x=0.6, index_tip_x=0.56, index_tip_y=0.66, dip_y=0.67, pip_y=0.70)
        hand_hover = create_test_hand(lms_hover, handedness="Right")

        # Stage 1: IDLE / HOVERING (calibrated depth < candidate_threshold 0.08)
        kb.process_multi_hands([hand_hover])
        assert f_state.state in (FingerPressState.IDLE, FingerPressState.HOVERING)
        assert f_state.is_pressed is False

        # Clear initial stabilization grace period to test active state transitions
        kb.hand_neutral_stabilization_until = 0.0

        # Stage 2: CANDIDATE (candidate_threshold <= calibrated_depth < press_threshold)
        with patch.object(hand_hover, "get_raw_finger_metric", return_value=0.20):
            kb.process_multi_hands([hand_hover])
            assert f_state.state == FingerPressState.CANDIDATE
            assert f_state.is_pressed is False

        # Stage 3: PRESSED (calibrated_depth >= press_threshold 0.15)
        with patch.object(hand_hover, "get_raw_finger_metric", return_value=0.35):
            kb.process_multi_hands([hand_hover])
            assert f_state.state == FingerPressState.PRESSED
            assert f_state.is_pressed is True
            assert f_state.press_locked is True

        # Stage 4: RELEASE_WAIT (Finger lingers above release_threshold 0.04; must NOT re-press!)
        with patch.object(hand_hover, "get_raw_finger_metric", return_value=0.20):
            stroke_count = kb.total_keystrokes
            kb.process_multi_hands([hand_hover])
            assert f_state.state == FingerPressState.RELEASE_WAIT
            assert f_state.press_locked is True
            assert kb.total_keystrokes == stroke_count

        # Stage 5: RE-ARM (Finger withdraws below release_threshold 0.04)
        with patch.object(hand_hover, "get_raw_finger_metric", return_value=0.12):
            kb.process_multi_hands([hand_hover])
            assert f_state.press_locked is False
            assert f_state.state in (FingerPressState.IDLE, FingerPressState.HOVERING)

    def test_test_mode_suppresses_send_input(self, qapp):
        """In TEST MODE (dry run), virtual key triggers must update preview buffer and glow,
        but SendInput keystroke injection to the OS must be completely suppressed."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        # Inject mock WindowsKeyboardInputService backend
        mock_backend = MockKeyboardBackend()
        kb.keyboard_service = WindowsKeyboardInputService(backend=mock_backend)

        # Ensure Test Mode is ON
        kb.set_test_mode(True)
        assert kb.test_mode is True

        # Trigger synthetic keypress 'A'
        triggered_labels = []
        kb.key_triggered.connect(triggered_labels.append)

        kb.synthetic_press("a")

        # 1. Prediction event was emitted and recorded
        assert "a" in triggered_labels or "A" in triggered_labels
        assert "PREDICTED (TEST MODE)" in kb.last_dispatched_event
        assert "TEST_MODE_ACTIVE" in kb.last_rejected_reason
        assert "a" in kb.text_buffer.lower()

        # 2. Zero OS-level SendInput events dispatched!
        assert kb.keyboard_service.total_keystrokes_dispatched == 0
        assert len(mock_backend.down_events) == 0

    def test_live_global_typing_dispatches_when_test_mode_off(self, qapp):
        """When TEST MODE is turned OFF and GLOBAL TYPING is ON, keystrokes must be
        dispatched via SendInput."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        mock_backend = MockKeyboardBackend()
        kb.keyboard_service = WindowsKeyboardInputService(backend=mock_backend)

        # Turn OFF test mode and turn ON global typing
        kb.set_test_mode(False)
        kb.set_global_typing(True)

        kb.synthetic_press("b")

        assert kb.keyboard_service.total_keystrokes_dispatched > 0
        assert len(mock_backend.down_events) > 0
        assert "DISPATCHED (LIVE OS INPUT)" in kb.last_dispatched_event
        assert kb.last_rejected_reason == "NONE (ACCEPTED)"


class TestNeutralCalibrationAndSafety:
    """Verifies baseline calibration logic and safe key release on hand loss."""

    def test_neutral_baseline_calibration(self, qapp):
        """Verifies neutral calibration samples finger resting positions and locks baseline."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        lms = make_mock_landmarks(wrist_x=0.7, index_tip_x=0.7, index_tip_y=0.5)
        hand = create_test_hand(lms, handedness="Right")

        # Start calibration for 0.05 seconds
        kb.start_neutral_calibration(duration=0.05)
        assert kb.calibration_active is True

        # Provide calibration frames with raw depth 0.22
        with patch.object(hand, "get_raw_finger_metric", return_value=0.22):
            kb.process_multi_hands([hand])
            time.sleep(0.06)
            kb.process_multi_hands([hand])

        # Calibration completed and baseline locked to 0.22
        assert kb.calibration_active is False
        assert kb.fingers["R_INDEX"].baseline_depth == pytest.approx(0.22, abs=0.01)

    def test_hand_loss_releases_held_keys(self, qapp):
        """When hands leave camera frame, any held keys must be immediately released."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        mock_backend = MockKeyboardBackend()
        kb.keyboard_service = WindowsKeyboardInputService(backend=mock_backend)

        # Simulate holding Shift
        kb.keyboard_service.send_key_down(0x10)
        assert 0x10 in kb.keyboard_service.held_vks

        # Call process_multi_hands with 0 hands (hands lost)
        kb.process_multi_hands([])

        # Held keys must be safely released
        assert len(kb.keyboard_service.held_vks) == 0
        assert kb.left_detected is False
        assert kb.right_detected is False


class TestMouseAndScrollRegression:
    """Ensures existing mouse movement, cursor stabilization, and scrolling remain intact."""

    def test_mouse_cursor_movement_and_smoothing(self):
        vm = VirtualMouse(smoothing=0.6, fine_control_mode=True, fine_control_scale=0.40)
        vm.screen_width = 1920
        vm.screen_height = 1080

        # Simulate moving hand
        now = time.time()
        st, (x1, y1), _ = vm.process_frame(norm_coords=(0.50, 0.50), timestamp=now)
        st, (x2, y2), _ = vm.process_frame(norm_coords=(0.52, 0.51), timestamp=now + 0.033)

        assert x2 != 0 and y2 != 0
        assert 0 <= x2 <= 1920
        assert 0 <= y2 <= 1080

    def test_scroll_controller_activation_and_release(self):
        ctrl = ScrollController(sensitivity=1.2, deadzone=0.035)

        hand = create_test_hand(make_mock_landmarks(index_tip_y=0.40), handedness="Right")

        now = time.time()
        telem = ctrl.process_hand(hand, is_scroll_gesture=True, now=now)
        hand.landmarks_norm = make_mock_landmarks(index_tip_y=0.35)
        telem = ctrl.process_hand(hand, is_scroll_gesture=True, now=now + 0.05)

        assert telem.hand_detected is True

        # Stop scrolling
        ctrl.stop_scrolling()
        assert ctrl.is_active is False


class TestKeySelectionAndActionControls:
    """Verifies Key Selection Test Mode, 1:1 coordinate mapping, and Action Bar interactions."""

    def test_key_selection_test_mode_suppresses_typing(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()

        # Toggle Key Selection Test Mode ON
        kb.set_key_selection_test_mode(True)
        assert kb.key_selection_test_mode is True
        assert kb.test_mode is True
        assert kb.global_typing_enabled is False

        # Simulate hand hovering and attempting to press
        lms = make_mock_landmarks(wrist_x=0.6, index_tip_x=0.56, index_tip_y=0.66)
        hand = create_test_hand(lms, handedness="Right")
        with patch.object(hand, "get_raw_finger_metric", return_value=0.35):
            kb.process_multi_hands([hand])

        # Keypress must be strictly suppressed
        assert kb.fingers["R_INDEX"].state == FingerPressState.IDLE
        assert kb.fingers["R_INDEX"].is_pressed is False

    def test_1_to_1_linear_mapping_both_hands(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        # Left and Right hand mappings across keyboard canvas
        px_left, py_left, in_l = kb.map_camera_to_keyboard(0.20, 0.50)
        px_mid, py_mid, in_m = kb.map_camera_to_keyboard(0.50, 0.50)
        px_right, py_right, in_r = kb.map_camera_to_keyboard(0.80, 0.50)

        assert in_l and in_m and in_r
        assert px_left < px_mid < px_right
        assert py_left == py_mid == py_right

    def test_action_bar_click_handling(self, qapp):
        from PySide6.QtCore import QPointF
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)

        # Click KEY TEST [215..300]
        initial_test = kb.key_selection_test_mode
        handled = kb._handle_action_bar_click(QPointF(250.0, 15.0))
        assert handled is True
        assert kb.key_selection_test_mode != initial_test

        # Click DRY-RUN TEST [305..390]
        handled = kb._handle_action_bar_click(QPointF(350.0, 15.0))
        assert handled is True

        # Click GLOBAL KB [395..480]
        handled = kb._handle_action_bar_click(QPointF(440.0, 15.0))
        assert handled is True

        # Click TRIGGER MODE cycle [485..565]
        init_mode = kb.press_detection_mode
        handled = kb._handle_action_bar_click(QPointF(520.0, 15.0))
        assert handled is True
        assert kb.press_detection_mode != init_mode

        # Click HUD [655..710]
        init_hud = kb.show_diagnostics_hud
        handled = kb._handle_action_bar_click(QPointF(680.0, 15.0))
        assert handled is True
        assert kb.show_diagnostics_hud != init_hud
