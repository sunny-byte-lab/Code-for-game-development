"""Unit tests for advanced virtual mouse features: independent X/Y sensitivity,
inversion, relative control mode, custom ROI bounds, and click anti-slip stabilization.
"""

import time
import pytest
from app.virtual_mouse import VirtualMouse


class TestAdvancedVirtualMouse:
    def test_independent_xy_sensitivity(self):
        vm = VirtualMouse(sensitivity_x=3.0, sensitivity_y=1.0)
        vm.screen_w = 1000
        vm.screen_h = 1000

        # Center (0.5, 0.5)
        cx, cy = vm.map_to_screen(0.5, 0.5)

        # Move +0.1 in X and +0.1 in Y
        px, py = vm.map_to_screen(0.6, 0.6)

        # Delta X should be approximately 3x Delta Y due to sensitivity_x=3.0 vs sensitivity_y=1.0
        delta_x = px - cx
        delta_y = py - cy
        assert delta_x > delta_y * 2.5

    def test_horizontal_inversion(self):
        vm_normal = VirtualMouse(invert_x=False)
        vm_normal.screen_w = 1000
        vm_normal.screen_h = 1000

        vm_inverted = VirtualMouse(invert_x=True)
        vm_inverted.screen_w = 1000
        vm_inverted.screen_h = 1000

        x_norm, _ = vm_normal.map_to_screen(0.2, 0.5)
        x_inv, _ = vm_inverted.map_to_screen(0.2, 0.5)

        # Inverted X should mirror across screen width
        assert abs((x_norm + x_inv) - (vm_normal.screen_w - 1)) < 2.0

    def test_custom_roi_bounds(self):
        vm = VirtualMouse(roi_bounds=(0.20, 0.10, 0.80, 0.70))
        vm.screen_w = 1000
        vm.screen_h = 1000

        # Top-left of custom ROI (0.20, 0.10) maps to screen (0, 0)
        x1, y1 = vm.map_to_screen(0.20, 0.10)
        assert x1 == 0.0
        assert y1 == 0.0

        # Bottom-right of custom ROI (0.80, 0.70) maps to screen (999, 999)
        x2, y2 = vm.map_to_screen(0.80, 0.70)
        assert x2 == 999.0
        assert y2 == 999.0

    def test_relative_cursor_mode(self):
        vm = VirtualMouse(cursor_mode="relative", relative_speed=5.0, relative_deadzone=0.02)
        vm.screen_w = 1000
        vm.screen_h = 1000
        vm.curr_x = 500.0
        vm.curr_y = 500.0

        # Initial point sets anchor
        t0 = 100.0
        vm.move_cursor(0.5, 0.5, timestamp=t0)
        assert vm.relative_anchor == (0.5, 0.5)

        # Move hand slightly within deadzone (< 0.02)
        px1, py1 = vm.move_cursor(0.51, 0.51, timestamp=t0 + 0.033)
        assert px1 == 500
        assert py1 == 500

        # Displace hand significantly to the right (0.6, 0.5) -> delta_x = +0.1
        t1 = t0 + 0.066
        px2, py2 = vm.move_cursor(0.60, 0.50, timestamp=t1)
        assert px2 > 500
        assert py2 == 500  # Y was centered on anchor, shouldn't move

    def test_click_anti_slip_stabilization(self):
        vm = VirtualMouse(click_stabilization=True, click_stabilization_ms=150)
        vm.screen_w = 1000
        vm.screen_h = 1000
        vm.curr_x = 450.0
        vm.curr_y = 350.0

        # Trigger stabilization (as happens when pinch click is detected)
        vm.trigger_click_stabilization(duration_ms=150)

        # Attempt to move cursor during stabilization window (simulating finger twitch during pinch)
        px, py = vm.move_cursor(0.80, 0.80)

        # Cursor should remain rock-solid frozen at 450, 350
        assert px == 450
        assert py == 350

        # Wait past stabilization window
        time.sleep(0.16)
        px_after, py_after = vm.move_cursor(0.80, 0.80)
        assert px_after > 450
