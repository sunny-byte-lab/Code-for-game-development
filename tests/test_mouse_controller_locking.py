"""Automated tests for Single Authoritative Mouse Controller and Pinch Locking.
Validates cursor pre-lock, drift prevention, click locking, release blending,
and state machine transitions using MockMouseBackend without requiring physical hardware.
"""

import time
import pytest
from app.virtual_mouse import (
    VirtualMouse, MouseState, MockMouseBackend, MouseEventRecord
)


class TestMouseControllerLocking:
    @pytest.fixture
    def mock_backend(self):
        backend = MockMouseBackend(screen_w=1920, screen_h=1080)
        return backend

    @pytest.fixture
    def mouse_controller(self, mock_backend):
        vm = VirtualMouse(
            backend=mock_backend,
            sensitivity=1.0,
            sensitivity_x=1.0,
            sensitivity_y=1.0,
            smoothing=0.5,
            deadzone_radius=2.0,
            active_margin_x=0.0,
            active_margin_y=0.0,
            pinch_threshold=0.28,
            candidate_delta=0.08,  # candidate_threshold = 0.36
            pinch_release_threshold=0.42,
            drag_hold_duration=0.40
        )
        vm.screen_w = 1920
        vm.screen_h = 1080
        # Initialize at center
        vm.curr_x = 960.0
        vm.curr_y = 540.0
        return vm

    def test_full_pinch_lifecycle_with_drift_prevention(self, mouse_controller, mock_backend):
        """Simulates full pinch lifecycle:
        1. Move to (500, 400)
        2. Candidate pinch detected -> Cursor locks immediately
        3. Landmark drifts/wobbles during finger closure -> ZERO movement allowed
        4. Confirmation threshold met -> Exactly 1 click at locked position
        5. Held for 1.0s -> ZERO extra clicks, ZERO moves
        6. Released -> Transitions to tracking with smooth filter reinitialization
        """
        vm = mouse_controller
        t0 = 1000.0

        # Step 1: Move to target (500, 400)
        # Normalized coords for 500, 400 on 1920x1080:
        norm_x = 500.0 / 1919.0
        norm_y = 400.0 / 1079.0

        state, coords, msg = vm.process_frame(
            norm_coords=(norm_x, norm_y),
            pinch_dist=0.60,  # Open hand
            timestamp=t0
        )
        assert state == MouseState.TRACKING
        target_locked_x = coords[0]
        target_locked_y = coords[1]
        assert abs(target_locked_x - 500) <= 2
        assert abs(target_locked_y - 400) <= 2

        move_count_before = len(mock_backend.move_events)
        assert move_count_before > 0

        # Step 2: Finger starts moving toward thumb, entering CANDIDATE range (0.32 < 0.36)
        t1 = t0 + 0.033
        state, coords, msg = vm.process_frame(
            norm_coords=(norm_x, norm_y),
            pinch_dist=0.32,
            timestamp=t1
        )
        assert state == MouseState.PINCH_CANDIDATE
        assert vm.locked_position == (target_locked_x, target_locked_y)

        # Step 3: Severe hand wobble / index fingertip shift while closing fingers
        # Hand drifts by +100px in X and +80px in Y
        wobble_x = (500.0 + 100.0) / 1919.0
        wobble_y = (400.0 + 80.0) / 1079.0
        t2 = t1 + 0.033

        state, coords, msg = vm.process_frame(
            norm_coords=(wobble_x, wobble_y),
            pinch_dist=0.30,  # Still in candidate range
            timestamp=t2
        )
        assert state == MouseState.PINCH_CANDIDATE
        # Cursor must NOT move! Movement events must not have increased
        assert len(mock_backend.move_events) == move_count_before
        assert coords == (target_locked_x, target_locked_y)

        # Step 4: Pinch confirmed! Distance drops below confirmation threshold (0.22 <= 0.28)
        t3 = t2 + 0.033
        state, coords, msg = vm.process_frame(
            norm_coords=(wobble_x, wobble_y),
            pinch_dist=0.22,
            timestamp=t3
        )
        assert state == MouseState.CLICK_LOCKED
        # Exactly one click sent!
        assert len(mock_backend.click_events) == 1
        click_evt = mock_backend.click_events[0]
        assert click_evt.button == "left"
        # The click MUST land strictly at target_locked (500, 400), NOT at drifted position (600, 480)!
        assert click_evt.x == target_locked_x
        assert click_evt.y == target_locked_y

        # Step 5: Pinch held for 1 second with continuing tremor/movement
        for i in range(30):
            t_hold = t3 + 0.033 * (i + 1)
            shake_x = wobble_x + (0.01 if i % 2 == 0 else -0.01)
            shake_y = wobble_y + (0.01 if i % 2 == 0 else -0.01)
            st, co, _ = vm.process_frame(
                norm_coords=(shake_x, shake_y),
                pinch_dist=0.20,
                timestamp=t_hold
            )
            assert st == MouseState.CLICK_LOCKED
            assert co == (target_locked_x, target_locked_y)

        # Verified: Still exactly 1 click, and zero moves dispatched during hold
        assert len(mock_backend.click_events) == 1
        # No extra moves while click locked
        assert len(mock_backend.move_events) == move_count_before + 1  # only initial + click pos set

        # Step 6: Pinch released (dist = 0.50 >= 0.42)
        t_rel = t3 + 1.10
        state, coords, msg = vm.process_frame(
            norm_coords=(wobble_x, wobble_y),
            pinch_dist=0.50,
            timestamp=t_rel
        )
        assert state == MouseState.TRACKING
        assert vm.locked_position is None
        assert vm.release_blend_start == t_rel

        # Step 7: Seamless tracking resumption without abrupt jump
        t_after = t_rel + 0.05
        state, coords_after, msg = vm.process_frame(
            norm_coords=(wobble_x, wobble_y),
            pinch_dist=0.60,
            timestamp=t_after
        )
        assert state == MouseState.TRACKING

    def test_candidate_abort_when_fingers_separate_without_clicking(self, mouse_controller, mock_backend):
        """If user starts pinching but changes their mind and separates fingers,
        cursor must unlock and return to tracking without sending a click."""
        vm = mouse_controller
        t = 100.0

        # Move to (800, 600)
        vm.process_frame((800.0 / 1919.0, 600.0 / 1079.0), pinch_dist=0.55, timestamp=t)
        assert vm.state == MouseState.TRACKING

        # Candidate triggered (0.33 < 0.36)
        t += 0.033
        vm.process_frame((800.0 / 1919.0, 600.0 / 1079.0), pinch_dist=0.33, timestamp=t)
        assert vm.state == MouseState.PINCH_CANDIDATE

        # User separates fingers back to 0.48 without reaching 0.28
        t += 0.033
        state, coords, msg = vm.process_frame((810.0 / 1919.0, 605.0 / 1079.0), pinch_dist=0.48, timestamp=t)
        assert state == MouseState.TRACKING
        # ZERO clicks sent
        assert len(mock_backend.click_events) == 0

    def test_consecutive_clicks_at_different_coordinates(self, mouse_controller, mock_backend):
        """Verifies consecutive pinch clicks at two different targets."""
        vm = mouse_controller
        t = 200.0

        # Click 1 at (300, 200)
        n1_x, n1_y = 300.0 / 1919.0, 200.0 / 1079.0
        vm.process_frame((n1_x, n1_y), pinch_dist=0.60, timestamp=t)
        t += 0.033
        vm.process_frame((n1_x, n1_y), pinch_dist=0.33, timestamp=t)  # Candidate
        t += 0.033
        vm.process_frame((n1_x, n1_y), pinch_dist=0.20, timestamp=t)  # Click
        assert len(mock_backend.click_events) == 1
        assert abs(mock_backend.click_events[0].x - 300) <= 2
        assert abs(mock_backend.click_events[0].y - 200) <= 2

        # Release
        t += 0.05
        vm.process_frame((n1_x, n1_y), pinch_dist=0.50, timestamp=t)

        # Move to Click 2 at (1200, 700)
        t += 0.15
        n2_x, n2_y = 1200.0 / 1919.0, 700.0 / 1079.0
        vm.process_frame((n2_x, n2_y), pinch_dist=0.60, timestamp=t)
        t += 0.033
        vm.process_frame((n2_x, n2_y), pinch_dist=0.60, timestamp=t)  # Filter settles at target
        t += 0.033
        vm.process_frame((n2_x, n2_y), pinch_dist=0.33, timestamp=t)  # Candidate
        t += 0.033
        vm.process_frame((n2_x, n2_y), pinch_dist=0.20, timestamp=t)  # Click
        assert len(mock_backend.click_events) == 2
        assert abs(mock_backend.click_events[1].x - 1200) <= 2
        assert abs(mock_backend.click_events[1].y - 700) <= 2

    def test_tracking_loss_releases_active_drag(self, mouse_controller, mock_backend):
        """If hand leaves webcam frame during drag, drag must be released immediately."""
        vm = mouse_controller
        vm.curr_x = 500.0
        vm.curr_y = 500.0
        vm.start_drag()
        assert vm.is_dragging is True
        assert mock_backend.is_left_down is True

        # Hand lost
        state, coords, msg = vm.process_frame(norm_coords=None, emergency=False)
        assert state == MouseState.TRACKING_LOST
        assert vm.is_dragging is False
        assert mock_backend.is_left_down is False
        assert len(mock_backend.up_events) >= 1

    def test_emergency_stop_aborts_drag_and_locking(self, mouse_controller, mock_backend):
        """Emergency stop immediately terminates any locked position or active drag."""
        vm = mouse_controller
        vm.curr_x = 600.0
        vm.curr_y = 600.0
        vm.start_drag()

        state, coords, msg = vm.process_frame(
            norm_coords=(0.5, 0.5),
            emergency=True
        )
        assert state == MouseState.EMERGENCY_STOP
        assert vm.is_dragging is False
        assert mock_backend.is_left_down is False
        assert vm.locked_position is None
