"""Unit tests for N.E.X.U.S. Hand-Gesture Scroll Controller and Windows event dispatcher."""

import time
import pytest
from unittest.mock import MagicMock

from app.scroll_controller import ScrollController, ScrollDirection, ScrollStatus, ScrollTelemetry
from app.virtual_mouse import MockMouseBackend, VirtualMouse, MouseState
from app.hand_tracker import (
    HandLandmarkData, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP,
    WRIST, THUMB_TIP, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP
)
from app.gesture_recognizer import GestureRecognizer, GestureType
from app.safety_controller import SafetyController, ControlMode


def create_mock_hand(index_y: float = 0.50,
                     middle_y: float = 0.50,
                     ring_y: float = 0.65,
                     pinky_y: float = 0.70,
                     wrist_y: float = 0.80) -> HandLandmarkData:
    """Creates a mock HandLandmarkData with specified vertical landmark positions."""
    w, h = 640, 480
    lm = [(0.5, wrist_y, 0.0) for _ in range(21)]
    # Wrist
    lm[WRIST] = (0.5, wrist_y, 0.0)
    # Palm MCPs (for hand scale reference)
    lm[INDEX_MCP] = (0.48, 0.65, 0.0)
    lm[MIDDLE_MCP] = (0.52, 0.63, 0.0)
    lm[RING_MCP] = (0.56, 0.65, 0.0)
    lm[PINKY_MCP] = (0.60, 0.68, 0.0)
    # Thumb
    lm[THUMB_TIP] = (0.42, 0.60, 0.0)
    # Fingertips
    lm[INDEX_TIP] = (0.48, index_y, 0.0)
    lm[MIDDLE_TIP] = (0.52, middle_y, 0.0)
    lm[RING_TIP] = (0.56, ring_y, 0.0)
    lm[PINKY_TIP] = (0.60, pinky_y, 0.0)

    pix = [(int(p[0] * w), int(p[1] * h)) for p in lm]

    return HandLandmarkData(
        landmarks_norm=lm,
        landmarks_pixel=pix,
        handedness="Right",
        frame_width=w,
        frame_height=h
    )


class TestScrollController:
    def test_anchor_establishment_on_gesture_engagement(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, deadzone=0.035, engagement_required_frames=1)

        assert not ctrl.is_active
        assert ctrl.anchor_y is None

        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        telem = ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)

        assert ctrl.is_active
        assert ctrl.anchor_y is not None
        assert abs(ctrl.anchor_y - 0.50) < 0.01

    def test_deadzone_prevents_accidental_scrolling(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, deadzone=0.035, engagement_required_frames=1)

        # Establish anchor at y = 0.50
        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)

        # Micro-drift inside deadzone (0.50 -> 0.515, delta = 0.015 <= 0.035)
        hand_drift = create_mock_hand(index_y=0.515, middle_y=0.515)
        telem = ctrl.process_hand(hand_drift, is_scroll_gesture=True, now=1.1)

        assert telem.last_event_status == "DEADZONE"
        assert telem.direction == "NONE"
        assert len(backend.events) == 0  # Zero wheel events dispatched

    def test_upward_scroll_dispatches_positive_wheel_delta(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, deadzone=0.035, sensitivity=1.5, engagement_required_frames=1)

        # Anchor at y = 0.50
        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)

        # Move hand UP (y decreases from 0.50 to 0.40, delta = -0.10)
        hand_up = create_mock_hand(index_y=0.40, middle_y=0.40)
        telem = ctrl.process_hand(hand_up, is_scroll_gesture=True, now=1.5)

        assert telem.direction == "UP"
        assert telem.wheel_delta == 120
        # Check backend received positive delta (120)
        scroll_events = [e for e in backend.events if e.event_type == "SCROLL"]
        assert len(scroll_events) >= 1
        assert scroll_events[-1].delta == 120

    def test_downward_scroll_dispatches_negative_wheel_delta(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, deadzone=0.035, sensitivity=1.5, engagement_required_frames=1)

        # Anchor at y = 0.50
        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)

        # Move hand DOWN (y increases from 0.50 to 0.60, delta = +0.10)
        hand_down = create_mock_hand(index_y=0.60, middle_y=0.60)
        telem = ctrl.process_hand(hand_down, is_scroll_gesture=True, now=1.5)

        assert telem.direction == "DOWN"
        assert telem.wheel_delta == -120
        # Check backend received negative delta (-120)
        scroll_events = [e for e in backend.events if e.event_type == "SCROLL"]
        assert len(scroll_events) >= 1
        assert scroll_events[-1].delta == -120

    def test_proportional_speed_scaling(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, deadzone=0.035, min_speed=2.0, max_speed=20.0, engagement_required_frames=1)

        # Anchor at y = 0.50
        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)

        # Small displacement
        hand_small = create_mock_hand(index_y=0.45, middle_y=0.45)
        telem_small = ctrl.process_hand(hand_small, is_scroll_gesture=True, now=1.1)

        # Large displacement
        hand_large = create_mock_hand(index_y=0.30, middle_y=0.30)
        telem_large = ctrl.process_hand(hand_large, is_scroll_gesture=True, now=1.2)

        assert telem_large.speed > telem_small.speed

    def test_gesture_release_stops_scrolling_immediately(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, engagement_required_frames=1)

        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)
        assert ctrl.is_active

        # Gesture released
        telem = ctrl.process_hand(hand, is_scroll_gesture=False, now=1.1)
        assert not ctrl.is_active
        assert ctrl.anchor_y is None
        assert telem.scroll_mode is False
        assert telem.direction == "NONE"

    def test_tracking_loss_stops_scrolling_immediately(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend, engagement_required_frames=1)

        hand = create_mock_hand(index_y=0.50, middle_y=0.50)
        ctrl.process_hand(hand, is_scroll_gesture=True, now=1.0)
        assert ctrl.is_active

        # Hand lost (hand = None)
        telem = ctrl.process_hand(None, is_scroll_gesture=True, now=1.1)
        assert not ctrl.is_active
        assert ctrl.anchor_y is None
        assert telem.scroll_mode is False

    def test_cursor_isolation_during_active_scrolling(self):
        backend = MockMouseBackend()
        mouse = VirtualMouse(backend=backend)

        # Frame 1: Tracking regained
        mouse.process_frame(norm_coords=(0.5, 0.5), timestamp=1.0)
        # Frame 2: Tracking move
        state, coords, _ = mouse.process_frame(norm_coords=(0.52, 0.52), timestamp=1.05)
        assert state == MouseState.TRACKING
        initial_moves = len([e for e in backend.events if e.event_type == "MOVE"])
        assert initial_moves >= 1

        # Frame 3: Scroll active: cursor movement must be strictly frozen
        state, coords, msg = mouse.process_frame(
            norm_coords=(0.6, 0.4),
            timestamp=1.1,
            is_scroll_active=True
        )
        assert state == MouseState.SCROLLING
        assert "SCROLLING" in msg

        # Ensure NO new cursor moves were dispatched while scrolling
        after_scroll_moves = len([e for e in backend.events if e.event_type == "MOVE"])
        assert after_scroll_moves == initial_moves

    def test_air_typing_isolation(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend)
        safety = SafetyController()

        # Engage Air Typing Mode
        safety.switch_mode(ControlMode.KEYBOARD)
        assert safety.current_mode == ControlMode.KEYBOARD

        # Scroll controller must stop and remain inactive
        ctrl.stop_scrolling()
        assert not ctrl.is_active

    def test_synthetic_scroll_triggers_real_events(self):
        backend = MockMouseBackend()
        ctrl = ScrollController(backend=backend)

        # Synthetic UP
        ok_up = ctrl.synthetic_scroll(ScrollDirection.UP, notches=2)
        assert ok_up is True
        assert ctrl.last_wheel_delta == 240

        # Synthetic DOWN
        ok_down = ctrl.synthetic_scroll(ScrollDirection.DOWN, notches=1)
        assert ok_down is True
        assert ctrl.last_wheel_delta == -120

        scroll_events = [e for e in backend.events if e.event_type == "SCROLL"]
        assert len(scroll_events) == 2
        assert scroll_events[0].delta == 240
        assert scroll_events[1].delta == -120
