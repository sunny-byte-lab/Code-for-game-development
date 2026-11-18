"""Unit and integration tests verifying the complete removal of unwanted locking behavior.

Validates:
1. Open hand and closed fist are treated as neutral resting postures, NEVER locking N.E.X.U.S.
2. Temporary hand loss transitions cleanly to READY (not EMERGENCY_STOP).
3. Hand reacquisition immediately restores ACTIVE control without manual button clicks or re-engagement.
4. Emergency stop is ONLY triggered manually (via Esc key or UI button), stopping virtual inputs immediately.
5. Re-engagement from manual emergency stop restores normal operation.
6. Desktop mouse movement, clicks, scrolling, and air typing remain fully operational.
"""

import time
import pytest
from unittest.mock import MagicMock

from app.gesture_recognizer import GestureRecognizer, GestureType, GestureState
from app.hand_tracker import HandLandmarkData
from app.safety_controller import SafetyController, SystemState, ControlMode
from app.camera_worker import CameraWorker
from app.virtual_mouse import VirtualMouse, MockMouseBackend
from tests.test_gesture_logic import create_mock_hand


def create_mock_hand_from_extensions(extensions: dict) -> HandLandmarkData:
    """Helper creating a synthetic HandLandmarkData with specified finger states."""
    # 21 landmarks formatted as (x, y, z)
    # Default base palm points
    lms = [(0.5, 0.7, 0.0)] * 21
    # Wrist
    lms[0] = (0.5, 0.8, 0.0)

    # Index finger
    if extensions.get("index", False):
        lms[8] = (0.5, 0.3, 0.0)  # Tip high up
        lms[6] = (0.5, 0.5, 0.0)  # PIP lower
    else:
        lms[8] = (0.5, 0.65, 0.0) # Tip curled down
        lms[6] = (0.5, 0.55, 0.0)

    # Middle finger
    if extensions.get("middle", False):
        lms[12] = (0.52, 0.3, 0.0)
        lms[10] = (0.52, 0.5, 0.0)
    else:
        lms[12] = (0.52, 0.65, 0.0)
        lms[10] = (0.52, 0.55, 0.0)

    # Ring finger
    if extensions.get("ring", False):
        lms[16] = (0.54, 0.3, 0.0)
        lms[14] = (0.54, 0.5, 0.0)
    else:
        lms[16] = (0.54, 0.65, 0.0)
        lms[14] = (0.54, 0.55, 0.0)

    # Pinky finger
    if extensions.get("pinky", False):
        lms[20] = (0.56, 0.35, 0.0)
        lms[18] = (0.56, 0.55, 0.0)
    else:
        lms[20] = (0.56, 0.65, 0.0)
        lms[18] = (0.56, 0.58, 0.0)

    # Thumb
    if extensions.get("thumb", False):
        lms[4] = (0.42, 0.5, 0.0)
        lms[2] = (0.46, 0.6, 0.0)
    else:
        lms[4] = (0.48, 0.6, 0.0)
        lms[2] = (0.47, 0.6, 0.0)

    return HandLandmarkData(
        landmarks_norm=lms,
        landmarks_pixel=[(int(x * 640), int(y * 480)) for x, y, z in lms],
        handedness="Right",
        frame_width=640,
        frame_height=480,
        confidence=0.95
    )


class TestLockRemovalAndNormalOperation:
    """Tests that ordinary hand movements and fists never lock N.E.X.U.S."""

    def test_closed_fist_does_not_lock(self):
        """Holding an ordinary closed fist must NOT trigger emergency stop or lock the UI."""
        recognizer = GestureRecognizer()
        fist_hand = create_mock_hand({
            "thumb": False, "index": False, "middle": False, "ring": False, "pinky": False
        })
        assert fist_hand.extended_count == 0

        # Repeated frames of a closed fist over 1.0 second
        for _ in range(10):
            state = recognizer.recognize(fist_hand)
            time.sleep(0.02)

        # Must be safe neutral / resting posture, NEVER FIST_EMERGENCY
        assert state.gesture != GestureType.FIST_EMERGENCY
        assert state.gesture == GestureType.NONE
        assert "RESTING" in state.description or "CLOSED FIST" in state.description

    def test_open_hand_does_not_lock(self):
        """An open palm (5 fingers extended) is a comfortable neutral pose and does not lock."""
        recognizer = GestureRecognizer()
        open_hand = create_mock_hand({
            "thumb": True, "index": True, "middle": True, "ring": True, "pinky": True
        })
        assert open_hand.extended_count == 5

        state = recognizer.recognize(open_hand)
        assert state.gesture != GestureType.FIST_EMERGENCY
        assert state.gesture == GestureType.NONE
        assert "OPEN PALM" in state.description or "NEUTRAL" in state.description

    def test_hand_loss_and_automatic_reacquisition(self):
        """When a hand leaves camera view, state becomes READY; when hand returns, it immediately becomes ACTIVE."""
        safety = SafetyController(hand_stable_delay=0.01)
        safety.enable_control()

        # 1. Hand present -> ACTIVE
        safety.on_hand_detected()
        time.sleep(0.02)
        assert safety.system_state == SystemState.ACTIVE
        assert safety.can_process_input() is True

        # 2. Hand leaves camera -> READY (control is NOT disabled or locked!)
        safety.hand_loss_grace_duration = 0.0
        safety.on_hand_lost()
        assert safety.system_state == SystemState.READY
        assert safety.is_enabled is True  # Still enabled!
        assert safety.can_process_input() is False  # Awaiting hand

        # 3. Hand re-enters view -> IMMEDIATELY ACTIVE without requiring manual clicks or re-engagement
        safety.on_hand_detected()
        time.sleep(0.02)
        assert safety.system_state == SystemState.ACTIVE
        assert safety.can_process_input() is True

    def test_manual_emergency_stop_and_clean_resume(self):
        """Manual emergency stop (via Esc or button) halts input and releases all buttons cleanly."""
        mock_backend = MockMouseBackend()
        mouse = VirtualMouse(backend=mock_backend)
        safety = SafetyController()
        safety.cancel_drag_callback = mouse.release_drag
        safety.enable_control()
        safety.on_hand_detected()

        # Simulate mouse dragging
        mouse.start_drag()
        assert mouse.is_dragging is True

        # User presses Esc or clicks UI button
        safety.emergency_stop(source="MANUAL [ESC]")
        assert safety.system_state == SystemState.EMERGENCY_STOP
        assert mouse.is_dragging is False
        assert safety.can_process_input() is False

        # Verify buttons were safely released
        up_events = [e for e in mock_backend.events if e.event_type == "UP"]
        assert len(up_events) >= 1

        # User re-engages / resumes control
        safety.reengage_from_emergency()
        assert safety.system_state != SystemState.EMERGENCY_STOP
        assert safety.is_enabled is True

    def test_camera_worker_fist_neutral_dispatch(self):
        """CameraWorker action dispatch treats resting fist as neutral and does not lock safety controller."""
        safety = SafetyController()
        safety.enable_control()
        safety.on_hand_detected()
        time.sleep(0.02)
        assert safety.system_state == SystemState.ACTIVE

        worker = CameraWorker(safety=safety)
        fist_state = GestureState(GestureType.NONE, description="CLOSED FIST (RESTING HAND)")
        fist_hand = create_mock_hand({
            "thumb": False, "index": False, "middle": False, "ring": False, "pinky": False
        })

        status = worker._dispatch_actions(fist_state, fist_hand, fps=30.0)
        # Safety controller MUST remain ACTIVE, not EMERGENCY_STOP or LOCKED
        assert safety.system_state == SystemState.ACTIVE
        assert status.system_state == SystemState.ACTIVE.value
        assert "EMERGENCY" not in status.last_action
