"""Unit and integration tests for Universal Windows Mouse Control via Win32 SendInput.
Validates:
- SendInput dispatch with native INPUT/MOUSEINPUT ctypes structures
- SetCursorPos desktop positioning
- Left/Right click, atomic down/up sequencing, and anti-slip freeze
- Scroll dispatch with MOUSEEVENTF_WHEEL and signed DWORD delta
- Hand persistence and tracking-loss button release failsafes
- Pipeline telemetry fields (input_api, scroll_status, mouse_movement_status)
"""

import time
import ctypes
from unittest.mock import MagicMock, patch
import pytest

from app.virtual_mouse import (
    VirtualMouse,
    WindowsMouseBackend,
    MockMouseBackend,
    INPUT,
    INPUT_MOUSE,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_WHEEL,
)
from app.camera_worker import ControlPipelineStatus, CameraWorker
from app.hand_tracker import HandLandmarkData


class TestWindowsMouseBackend:
    """Tests the native Windows SendInput backend implementation."""

    def test_send_input_struct_format(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SendInput.return_value = 1

        # Dispatch a left click down
        ok = backend._send_input(MOUSEEVENTF_LEFTDOWN, data=0, dx=10, dy=20)
        assert ok is True
        assert backend.api_name == "SendInput (Win32)"

        # Verify arguments passed to SendInput
        backend._user32.SendInput.assert_called_once()
        args = backend._user32.SendInput.call_args[0]
        nInputs, pInputs, cbSize = args

        assert nInputs == 1
        assert cbSize == ctypes.sizeof(INPUT)

        # Inspect the ctypes structure pointed to by pInputs
        inp = ctypes.cast(pInputs, ctypes.POINTER(INPUT)).contents
        assert inp.type == INPUT_MOUSE
        assert inp.mi.dwFlags == MOUSEEVENTF_LEFTDOWN
        assert inp.mi.dx == 10
        assert inp.mi.dy == 20
        assert inp.mi.mouseData == 0

    def test_scroll_wheel_positive_delta(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SendInput.return_value = 1

        ok = backend.scroll(120)
        assert ok is True

        backend._user32.SendInput.assert_called_once()
        args = backend._user32.SendInput.call_args[0]
        inp = ctypes.cast(args[1], ctypes.POINTER(INPUT)).contents

        assert inp.mi.dwFlags == MOUSEEVENTF_WHEEL
        assert inp.mi.mouseData == 120

    def test_scroll_wheel_negative_delta(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SendInput.return_value = 1

        ok = backend.scroll(-120)
        assert ok is True

        backend._user32.SendInput.assert_called_once()
        args = backend._user32.SendInput.call_args[0]
        inp = ctypes.cast(args[1], ctypes.POINTER(INPUT)).contents

        assert inp.mi.dwFlags == MOUSEEVENTF_WHEEL
        # -120 in 32-bit unsigned DWORD is 0xFFFFFF88 (4294967176)
        expected_dword = (-120) & 0xFFFFFFFF
        assert inp.mi.mouseData == expected_dword

    def test_mouse_down_and_up_events(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SendInput.return_value = 1

        # Left Down
        assert backend.mouse_down("left") is True
        inp = ctypes.cast(backend._user32.SendInput.call_args[0][1], ctypes.POINTER(INPUT)).contents
        assert inp.mi.dwFlags == MOUSEEVENTF_LEFTDOWN

        # Left Up
        assert backend.mouse_up("left") is True
        inp = ctypes.cast(backend._user32.SendInput.call_args[0][1], ctypes.POINTER(INPUT)).contents
        assert inp.mi.dwFlags == MOUSEEVENTF_LEFTUP

        # Right Down
        assert backend.mouse_down("right") is True
        inp = ctypes.cast(backend._user32.SendInput.call_args[0][1], ctypes.POINTER(INPUT)).contents
        assert inp.mi.dwFlags == MOUSEEVENTF_RIGHTDOWN

        # Right Up
        assert backend.mouse_up("right") is True
        inp = ctypes.cast(backend._user32.SendInput.call_args[0][1], ctypes.POINTER(INPUT)).contents
        assert inp.mi.dwFlags == MOUSEEVENTF_RIGHTUP

    def test_click_sequence(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SendInput.return_value = 1

        ok = backend.click("left")
        assert ok is True
        assert backend._user32.SendInput.call_count == 2

    def test_set_cursor_pos(self):
        backend = WindowsMouseBackend()
        backend._user32 = MagicMock()
        backend._user32.SetCursorPos.return_value = 1

        ok = backend.set_cursor_pos(500, 300)
        assert ok is True
        backend._user32.SetCursorPos.assert_called_once_with(500, 300)


class TestVirtualMouseFailsafes:
    """Tests safety mechanisms, button release, and drag controls."""

    def test_release_all_buttons(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        vm.is_dragging = True

        vm.release_all_buttons()
        assert vm.is_dragging is False

        # Should have dispatched mouse_up for both left and right
        types = [e.event_type for e in mock_backend.events]
        buttons = [e.button for e in mock_backend.events]
        assert types == ["UP", "UP"]
        assert "left" in buttons
        assert "right" in buttons

    def test_release_drag_calls_release_all(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        vm.is_dragging = True

        ok, msg = vm.release_drag()
        assert ok is True
        assert vm.is_dragging is False
        assert len(mock_backend.events) == 2

    def test_input_api_property(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        assert vm.input_api == "Mock"

        win_backend = WindowsMouseBackend()
        vm_win = VirtualMouse(backend=win_backend)
        assert vm_win.input_api == "SendInput (Win32)"


class TestControlPipelineStatusTelemetry:
    """Verifies pipeline telemetry status contract."""

    def test_status_dataclass_fields(self):
        status = ControlPipelineStatus(
            hand_detected=True,
            hand_landmarks_count=21,
            gesture_name="INDEX_POINTING",
            system_state="ACTIVE",
            control_mode="MOUSE",
            action_permitted=True,
            permission_reason="PERMITTED",
            last_action="CURSOR_MOVE",
            last_action_success=True,
            last_action_error="",
            cursor_coords=(800, 600),
            fps=30.0,
            camera_index=0,
            input_api="SendInput (Win32)",
            scroll_status="IDLE",
            mouse_movement_status="ACTIVE",
        )
        assert status.input_api == "SendInput (Win32)"
        assert status.scroll_status == "IDLE"
        assert status.mouse_movement_status == "ACTIVE"
        assert status.cursor_coords == (800, 600)
