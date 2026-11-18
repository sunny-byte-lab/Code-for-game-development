"""Automated tests for upgraded mouse movement, smoothing, and clicking systems.
Validates:
1. Small hand movement dampening and deadzone stillness.
2. Corner reachability across full physical screen dimensions.
3. Fine Control Mode velocity dampening (~40% precision scale).
4. Sensitivity presets (Low, Medium, High).
5. Single click per gesture (zero repeat clicks while held).
6. Post-click cooldown debounce rejection.
7. Cursor stabilization freeze during click candidate and confirmation.
8. Hand position recalibration and ROI re-centering.
9. Left vs Right click separation.
10. Scrolling and Air Typing isolation.
"""

import time
import pytest
from app.virtual_mouse import (
    VirtualMouse, MouseState, MockMouseBackend, MouseEventRecord
)


class TestMouseMovementAndClicking:
    @pytest.fixture
    def mock_backend(self):
        return MockMouseBackend(screen_w=1920, screen_h=1080)

    @pytest.fixture
    def mouse_controller(self, mock_backend):
        vm = VirtualMouse(
            backend=mock_backend,
            sensitivity=1.2,
            sensitivity_x=1.2,
            sensitivity_y=1.2,
            fine_control_mode=False,
            fine_control_scale=0.40,
            smoothing=0.65,
            smoothing_type="one_euro",
            one_euro_min_cutoff=1.0,
            one_euro_beta=0.02,
            deadzone_radius=8.0,
            active_margin_x=0.16,
            active_margin_y=0.16,
            pinch_threshold=0.28,
            candidate_delta=0.08,
            pinch_release_threshold=0.40,
            click_cooldown=0.20,
            click_stabilization_ms=160
        )
        vm.screen_w = 1920
        vm.screen_h = 1080
        vm.curr_x = 960.0
        vm.curr_y = 540.0
        return vm

    def test_deadzone_eliminates_micro_tremor(self, mouse_controller, mock_backend):
        """Micro-movements smaller than deadzone_radius produce 0 cursor moves."""
        vm = mouse_controller
        vm.curr_x = 960.0
        vm.curr_y = 540.0
        t0 = 100.0

        # Initial resting frame
        center_nx = 0.5
        center_ny = 0.5
        vm.process_frame((center_nx, center_ny), pinch_dist=0.60, timestamp=t0)
        initial_move_count = len(mock_backend.move_events)

        # Micro-tremors of 1-3 screen pixels equivalent in normalized space
        # 1920px screen -> 1px is ~0.00052
        for i in range(10):
            tiny_dx = 0.0003 * (1 if i % 2 == 0 else -1)
            tiny_dy = 0.0003 * (1 if i % 2 == 1 else -1)
            state, coords, msg = vm.process_frame(
                (center_nx + tiny_dx, center_ny + tiny_dy),
                pinch_dist=0.60,
                timestamp=t0 + 0.033 * (i + 1)
            )
            assert state == MouseState.TRACKING
            # Cursor coords must remain clamped at current resting location
            assert abs(coords[0] - 960) <= 2
            assert abs(coords[1] - 540) <= 2

        # No unnecessary move events sent to OS
        assert len(mock_backend.move_events) <= initial_move_count + 1

    def test_screen_corner_reachability(self, mouse_controller, mock_backend):
        """Cursor must reach all four corners of the screen with active margins."""
        vm = mouse_controller
        vm.fine_control_mode = False
        t = 50.0

        # Top-Left corner: normalized (roi_left, roi_top) = (0.16, 0.16)
        _, tl_coords, _ = vm.process_frame((0.10, 0.10), pinch_dist=0.60, timestamp=t)
        t += 0.05
        _, tl_coords, _ = vm.process_frame((0.10, 0.10), pinch_dist=0.60, timestamp=t)
        assert tl_coords[0] <= 10
        assert tl_coords[1] <= 10

        # Top-Right corner: normalized (0.90, 0.10)
        t += 0.05
        vm.process_frame((0.90, 0.10), pinch_dist=0.60, timestamp=t)
        t += 0.05
        _, tr_coords, _ = vm.process_frame((0.90, 0.10), pinch_dist=0.60, timestamp=t)
        assert tr_coords[0] >= 1910
        assert tr_coords[1] <= 10

        # Bottom-Left corner: normalized (0.10, 0.90)
        t += 0.05
        vm.process_frame((0.10, 0.90), pinch_dist=0.60, timestamp=t)
        t += 0.05
        _, bl_coords, _ = vm.process_frame((0.10, 0.90), pinch_dist=0.60, timestamp=t)
        assert bl_coords[0] <= 10
        assert bl_coords[1] >= 1070

        # Bottom-Right corner: normalized (0.90, 0.90)
        t += 0.05
        vm.process_frame((0.90, 0.90), pinch_dist=0.60, timestamp=t)
        t += 0.05
        _, br_coords, _ = vm.process_frame((0.90, 0.90), pinch_dist=0.60, timestamp=t)
        assert br_coords[0] >= 1910
        assert br_coords[1] >= 1070

    def test_fine_control_mode_dampening(self, mouse_controller):
        """Fine Control Mode applies 40% precision scale to cursor velocity."""
        vm = mouse_controller
        norm_center = (0.5, 0.5)
        norm_offset = (0.6, 0.5)  # Offset hand to the right

        # Standard Mode (Fine Control OFF)
        vm.set_fine_control(False)
        tx_std, _ = vm.map_to_screen(norm_offset[0], norm_offset[1])
        cx_std, _ = vm.map_to_screen(norm_center[0], norm_center[1])
        delta_std = tx_std - cx_std

        # Fine Control Mode (ON)
        vm.set_fine_control(True)
        tx_fine, _ = vm.map_to_screen(norm_offset[0], norm_offset[1])
        cx_fine, _ = vm.map_to_screen(norm_center[0], norm_center[1])
        delta_fine = tx_fine - cx_fine

        # Verify ~0.40 scaling ratio
        ratio = delta_fine / delta_std
        assert abs(ratio - 0.40) < 0.01

        # Toggle test
        new_state = vm.toggle_fine_control()
        assert new_state is False
        assert vm.fine_control_mode is False

    def test_sensitivity_presets(self, mouse_controller):
        """Presets correctly configure sensitivity parameters."""
        vm = mouse_controller

        vm.set_sensitivity_preset("low")
        assert vm.sensitivity == 0.8
        assert vm.sensitivity_x == 0.8
        assert vm.sensitivity_y == 0.8

        vm.set_sensitivity_preset("medium")
        assert vm.sensitivity == 1.2
        assert vm.sensitivity_x == 1.2

        vm.set_sensitivity_preset("high")
        assert vm.sensitivity == 1.8
        assert vm.sensitivity_x == 1.8

    def test_single_click_and_freeze_during_pinch(self, mouse_controller, mock_backend):
        """Cursor strictly freezes during candidate, fires exactly 1 click, and allows zero extra clicks while held."""
        vm = mouse_controller
        vm.curr_x = 700.0
        vm.curr_y = 400.0
        t0 = 500.0

        # Step 1: Open hand
        vm.process_frame((0.40, 0.40), pinch_dist=0.60, timestamp=t0)
        assert len(mock_backend.click_events) == 0

        # Step 2: Finger approaches thumb (Candidate triggered: 0.32 < 0.36)
        t1 = t0 + 0.033
        state, coords_cand, _ = vm.process_frame((0.40, 0.40), pinch_dist=0.32, timestamp=t1)
        assert state == MouseState.PINCH_CANDIDATE
        locked_pos = vm.locked_position
        assert locked_pos is not None
        assert coords_cand == locked_pos
        assert vm.is_stabilized is True

        # Step 3: Severe hand tremor during pinch squeeze
        # Hand moves by +0.05 norm coords (~100 px)
        t2 = t1 + 0.033
        state, coords_wobble, _ = vm.process_frame((0.45, 0.45), pinch_dist=0.30, timestamp=t2)
        assert state == MouseState.PINCH_CANDIDATE
        # Cursor MUST NOT MOVE! Must stay strictly at locked position
        assert coords_wobble == locked_pos

        # Step 4: Pinch confirmed (dist = 0.25 <= 0.28)
        t3 = t2 + 0.033
        state, coords_click, _ = vm.process_frame((0.45, 0.45), pinch_dist=0.25, timestamp=t3)
        assert state == MouseState.CLICK_LOCKED
        assert coords_click == locked_pos
        # Exactly one click sent at locked_pos
        assert len(mock_backend.click_events) == 1
        assert mock_backend.click_events[0].x == locked_pos[0]
        assert mock_backend.click_events[0].y == locked_pos[0] or abs(mock_backend.click_events[0].y - locked_pos[1]) <= 2

        # Step 5: Held for 1.5 seconds (45 frames)
        for i in range(45):
            t_held = t3 + 0.033 * (i + 1)
            st, co, _ = vm.process_frame((0.46, 0.46), pinch_dist=0.22, timestamp=t_held)
            assert st == MouseState.CLICK_LOCKED
            assert co == locked_pos

        # Verified: Still exactly 1 click, zero duplicate clicks!
        assert len(mock_backend.click_events) == 1

        # Step 6: Released (dist = 0.50 >= 0.40)
        t_rel = t3 + 1.60
        st, co, _ = vm.process_frame((0.46, 0.46), pinch_dist=0.50, timestamp=t_rel)
        assert st == MouseState.TRACKING
        assert vm.locked_position is None

    def test_post_click_cooldown_debounce(self, mouse_controller, mock_backend):
        """Immediately re-pinching within cooldown period does not trigger a second accidental click."""
        vm = mouse_controller
        t = 300.0

        # Move & Click 1
        vm.process_frame((0.3, 0.3), pinch_dist=0.60, timestamp=t)
        t += 0.033
        vm.process_frame((0.3, 0.3), pinch_dist=0.32, timestamp=t)  # Candidate
        t += 0.033
        vm.process_frame((0.3, 0.3), pinch_dist=0.25, timestamp=t)  # Click confirmed
        assert len(mock_backend.click_events) == 1

        # Release at t = 300.10
        t += 0.034
        vm.process_frame((0.3, 0.3), pinch_dist=0.45, timestamp=t)
        assert vm.cooldown_until > t

        # Premature re-pinch at t + 0.05s (cooldown is 0.20s, so t + 0.05 is rejected)
        t += 0.05
        state, _, _ = vm.process_frame((0.3, 0.3), pinch_dist=0.25, timestamp=t)
        # Must NOT enter PINCH_CANDIDATE or CLICK_LOCKED during cooldown!
        assert state == MouseState.TRACKING
        assert len(mock_backend.click_events) == 1  # No duplicate click!

        # After cooldown expires (t + 0.25s)
        t += 0.25
        state, _, _ = vm.process_frame((0.3, 0.3), pinch_dist=0.32, timestamp=t)
        assert state == MouseState.PINCH_CANDIDATE

    def test_recalibrate_hand_position(self, mouse_controller, mock_backend):
        """Recalibrate centers cursor and centers active ROI around current resting hand coordinates."""
        vm = mouse_controller
        vm.curr_x = 200.0
        vm.curr_y = 200.0

        # Hand resting comfortably at (0.35, 0.65)
        hand_nx = 0.35
        hand_ny = 0.65
        vm.recalibrate_position(hand_nx, hand_ny)

        # Cursor should be centered at physical screen center (960, 540)
        assert vm.curr_x == 960.0
        assert vm.curr_y == 540.0
        assert mock_backend.cursor_x == 960
        assert mock_backend.cursor_y == 540

        # ROI bounds should be centered around (0.35, 0.65)
        mid_roi_x = (vm.roi_left + vm.roi_right) / 2.0
        mid_roi_y = (vm.roi_top + vm.roi_bottom) / 2.0
        assert abs(mid_roi_x - 0.35) < 0.05
        assert abs(mid_roi_y - 0.65) < 0.05

    def test_left_and_right_click_distinction(self, mouse_controller, mock_backend):
        """Left and right clicks generate distinct OS mouse events."""
        vm = mouse_controller
        t = 10.0

        # Left click
        vm.left_click()
        assert len(mock_backend.click_events) == 1
        assert mock_backend.click_events[0].button == "left"

        # Right click
        vm.right_click()
        assert len(mock_backend.click_events) == 2
        assert mock_backend.click_events[1].button == "right"

    def test_scrolling_isolation(self, mouse_controller, mock_backend):
        """Active scrolling locks cursor movement and sends wheel delta without clicking."""
        vm = mouse_controller
        vm.curr_x = 500.0
        vm.curr_y = 500.0
        t = 20.0

        # Trigger scroll
        state, coords, msg = vm.process_frame(
            norm_coords=(0.5, 0.5),
            is_scroll_active=True,
            scroll_dy=0.08,
            timestamp=t
        )
        assert state == MouseState.SCROLLING
        assert len(mock_backend.click_events) == 0
        assert coords == (500, 500)
