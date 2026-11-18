"""Tests for Air Mouse Stabilization, Adaptive Smoothing, Tracking Loss Grace Period,
and Physical Mouse Priority Passthrough.
"""

import time
import math
import pytest
from unittest.mock import MagicMock

from app.filter import OneEuroFilter, PointFilter2D
from app.virtual_mouse import VirtualMouse, MockMouseBackend, MouseState
from app.physical_mouse_detector import PhysicalMouseDetector


class TestCursorStabilizationAndSmoothing:
    """Tests for adaptive filtering, jitter reduction, and deadzone behavior."""

    def test_one_euro_filter_reduces_low_speed_jitter(self):
        """Verifies that high-frequency micro-jitter at stationary position is heavily dampened."""
        filt = OneEuroFilter(freq=30.0, min_cutoff=0.8, beta=0.04)
        base = 500.0
        outputs = []
        t = 100.0

        for i in range(20):
            # Oscillate +/- 1.5 pixels around 500
            jitter = base + (1.5 if i % 2 == 0 else -1.5)
            val = filt.filter(jitter, timestamp=t)
            outputs.append(val)
            t += 0.033

        # Final jitter amplitude should be significantly attenuated
        recent = outputs[-6:]
        max_diff = max(recent) - min(recent)
        assert max_diff < 0.8, f"Expected jitter amplitude < 0.8px, got {max_diff:.2f}px"

    def test_one_euro_filter_responds_to_fast_movement(self):
        """Verifies that fast hand movement dynamically scales cutoff for responsive tracking without lag."""
        filt = OneEuroFilter(freq=30.0, min_cutoff=0.8, beta=0.04)
        t = 10.0
        filt.filter(100.0, timestamp=t)

        # Fast jump of 400px in 33ms
        t += 0.033
        out = filt.filter(500.0, timestamp=t)
        # Should follow closely (at least 75% of the step)
        assert out > 380.0, f"Expected fast response > 380px, got {out:.1f}px"

    def test_deadzone_eliminates_micro_jitter_when_stationary(self):
        """When finger movement is within deadzone, cursor stays locked at exact coordinates."""
        mock = MockMouseBackend()
        vm = VirtualMouse(backend=mock, deadzone_radius=8.0)
        vm.update_screen_size()

        t = 50.0
        # Initialize at center
        vm.process_frame((0.50, 0.50), timestamp=t)
        init_x, init_y = vm.curr_x, vm.curr_y

        # Micro movements within deadzone
        for i in range(5):
            t += 0.033
            # Small 0.001 delta corresponds to ~1.9px on 1920 width
            vm.process_frame((0.501, 0.501), timestamp=t)
            assert vm.curr_x == init_x
            assert vm.curr_y == init_y


class TestTrackingLossGracePeriod:
    """Tests for temporary tracking loss and recovery without cursor jumps."""

    def test_temporary_loss_within_grace_period_freezes_cursor(self):
        """During temporary loss (< 0.3s), cursor is frozen at last valid pos and state is not lost."""
        mock = MockMouseBackend()
        vm = VirtualMouse(backend=mock, tracking_loss_grace_s=0.30)
        t = 10.0

        # Valid tracking
        st, coords, _ = vm.process_frame((0.5, 0.5), timestamp=t)
        assert st == MouseState.TRACKING
        last_coords = coords

        # 1 missed frame (33ms)
        t += 0.033
        st, coords, msg = vm.process_frame(None, timestamp=t)
        assert vm.in_tracking_loss_grace is True
        assert coords == last_coords
        assert msg == "TRACKING LOSS GRACE"

        # 2nd missed frame (66ms)
        t += 0.033
        st, coords, msg = vm.process_frame(None, timestamp=t)
        assert vm.in_tracking_loss_grace is True
        assert coords == last_coords

    def test_tracking_loss_past_grace_period_triggers_lost_state(self):
        """After loss exceeds grace duration, state transitions to TRACKING_LOST."""
        mock = MockMouseBackend()
        vm = VirtualMouse(backend=mock, tracking_loss_grace_s=0.25)
        t = 10.0

        vm.process_frame((0.5, 0.5), timestamp=t)

        # Skip past grace period (300ms)
        t += 0.30
        st, coords, msg = vm.process_frame(None, timestamp=t)
        assert st == MouseState.TRACKING_LOST
        assert coords is None
        assert msg == "TRACKING LOST"

    def test_smooth_resumption_after_grace_period(self):
        """When valid tracking returns after grace, tracking resumes smoothly."""
        mock = MockMouseBackend()
        vm = VirtualMouse(backend=mock, tracking_loss_grace_s=0.30)
        t = 10.0

        vm.process_frame((0.5, 0.5), timestamp=t)

        # 1 frame dropped
        t += 0.033
        vm.process_frame(None, timestamp=t)
        assert vm.in_tracking_loss_grace is True

        # Hand returns
        t += 0.033
        st, coords, _ = vm.process_frame((0.51, 0.50), timestamp=t)
        assert st == MouseState.TRACKING
        assert vm.in_tracking_loss_grace is False
        assert coords is not None


class TestPhysicalMouseDetectorAndPriority:
    """Tests for physical mouse detection and priority switching."""

    def test_physical_activity_detected_on_significant_cursor_displacement(self):
        detector = PhysicalMouseDetector(physical_priority_timeout=1.5, movement_threshold_px=15.0)
        # Mock user32
        detector._user32 = MagicMock()
        detector._user32.GetAsyncKeyState.return_value = 0

        # Simulate N.E.X.U.S. placing cursor at (300, 300)
        detector.notify_virtual_move(300, 300)

        # Simulate physical mouse moved to (350, 350)
        def mock_get_pos(byref_pt):
            byref_pt._obj.x = 350
            byref_pt._obj.y = 350
            return 1

        detector._user32.GetCursorPos.side_effect = mock_get_pos

        is_active = detector.check_physical_activity(now=10.0)
        assert is_active is True
        assert detector.is_physical_active is True

    def test_physical_activity_detected_on_button_click(self):
        detector = PhysicalMouseDetector(physical_priority_timeout=1.5)
        detector._user32 = MagicMock()
        # Left button down (0x8000 set)
        detector._user32.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 1 else 0

        is_active = detector.check_physical_activity(now=10.0)
        assert is_active is True
        assert detector.is_physical_active is True

    def test_physical_priority_expires_after_timeout(self):
        detector = PhysicalMouseDetector(physical_priority_timeout=1.5, movement_threshold_px=15.0)
        detector._user32 = MagicMock()
        detector._user32.GetAsyncKeyState.return_value = 0

        detector.notify_virtual_move(300, 300)

        # Trigger physical move
        def mock_get_pos_moved(byref_pt):
            byref_pt._obj.x = 400
            byref_pt._obj.y = 400
            return 1

        detector._user32.GetCursorPos.side_effect = mock_get_pos_moved
        assert detector.check_physical_activity(now=10.0) is True

        # Now stationary at (400, 400) for 1.6s
        def mock_get_pos_still(byref_pt):
            byref_pt._obj.x = 400
            byref_pt._obj.y = 400
            return 1

        detector._user32.GetCursorPos.side_effect = mock_get_pos_still
        # 1.0s elapsed (still in priority)
        assert detector.check_physical_activity(now=11.0) is True

        # 1.6s elapsed (priority should expire and return False)
        assert detector.check_physical_activity(now=11.6) is False
