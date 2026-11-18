"""Unit tests for virtual mouse coordinate mapping, sensitivity, EMA smoothing, and deadzones."""

import pytest
from app.virtual_mouse import VirtualMouse


class TestVirtualMouse:
    def test_coordinate_mapping_center(self):
        vm = VirtualMouse(active_margin_x=0.1, active_margin_y=0.1, sensitivity=1.0)
        vm.screen_w = 1920
        vm.screen_h = 1080

        # Center (0.5, 0.5) should map to screen center
        tx, ty = vm.map_to_screen(0.5, 0.5)
        assert abs(tx - 959.5) < 2.0
        assert abs(ty - 539.5) < 2.0

    def test_coordinate_mapping_margins(self):
        vm = VirtualMouse(active_margin_x=0.15, active_margin_y=0.15, sensitivity=1.0)
        vm.screen_w = 1920
        vm.screen_h = 1080

        # Point at left active margin (0.15) should map to 0 px
        tx_left, _ = vm.map_to_screen(0.15, 0.5)
        assert tx_left == 0.0

        # Point at right active margin (0.85) should map to screen_w - 1
        tx_right, _ = vm.map_to_screen(0.85, 0.5)
        assert tx_right == 1919.0

        # Beyond margins should be clamped safely [0..screen_w-1]
        tx_out, ty_out = vm.map_to_screen(0.02, 0.98)
        assert tx_out == 0.0
        assert ty_out == 1079.0

    def test_ema_smoothing_and_deadzone(self):
        vm = VirtualMouse(smoothing=0.5, deadzone_radius=5.0)
        vm.screen_w = 1000
        vm.screen_h = 1000
        vm.curr_x = 500.0
        vm.curr_y = 500.0

        # Move slightly within deadzone radius
        # Target close to 500
        px, py = vm.move_cursor(0.501, 0.501)
        # Should filter out minor jitter and keep curr pos
        assert px == 500
        assert py == 500

        # Substantial movement outside deadzone
        px2, py2 = vm.move_cursor(0.80, 0.80)
        assert px2 > 500
        assert py2 > 500

    def test_screen_clamping_prevents_failsafe_corner(self):
        vm = VirtualMouse()
        vm.screen_w = 1920
        vm.screen_h = 1080

        # Exact corner (0, 0) is clamped to (1, 1) to avoid PyAutoGUI failsafe crash
        cx, cy = vm._clamp_screen_coords(0, 0)
        assert cx >= 1
        assert cy >= 1

        # Far edges
        cx2, cy2 = vm._clamp_screen_coords(2000, 2000)
        assert cx2 <= 1918
        assert cy2 <= 1078

    def test_action_execution_telemetry(self):
        vm = VirtualMouse()
        vm.screen_w = 1000
        vm.screen_h = 1000
        vm.curr_x = 500.0
        vm.curr_y = 500.0

        # Test left_click return shape
        ok_l, msg_l = vm.left_click()
        assert isinstance(ok_l, bool)
        assert "Left Click" in msg_l

        # Test right_click return shape
        ok_r, msg_r = vm.right_click()
        assert isinstance(ok_r, bool)
        assert "Right Click" in msg_r

        # Test drag start and release
        ok_d, msg_d = vm.start_drag()
        assert vm.is_dragging is True
        ok_rel, msg_rel = vm.release_drag()
        assert vm.is_dragging is False
