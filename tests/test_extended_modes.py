"""Tests for extended control modes, media/presentation controls, and 3D hologram lab."""

import pytest
from unittest.mock import patch, MagicMock
from app.safety_controller import SafetyController, ControlMode, SystemState
from app.system_controls import SystemControls
from app.gesture_recognizer import GestureRecognizer, GestureState, GestureType
from app.hud_widgets import HologramLabWidget
from app.camera_worker import CameraWorker
from app.virtual_mouse import VirtualMouse, MockMouseBackend


class TestExtendedSystemControls:
    @patch("app.system_controls.pyautogui.press")
    def test_media_playback_controls(self, mock_press):
        ctrl = SystemControls()
        assert ctrl.play_pause() is True
        mock_press.assert_called_with("playpause", _pause=False)

        assert ctrl.next_track() is True
        mock_press.assert_called_with("nexttrack", _pause=False)

        assert ctrl.previous_track() is True
        mock_press.assert_called_with("prevtrack", _pause=False)

    @patch("app.system_controls.pyautogui.press")
    def test_presentation_controls(self, mock_press):
        ctrl = SystemControls()
        assert ctrl.next_slide() is True
        mock_press.assert_called_with("pagedown", _pause=False)

        assert ctrl.previous_slide() is True
        mock_press.assert_called_with("pageup", _pause=False)

        assert ctrl.start_slideshow() is True
        mock_press.assert_called_with("f5", _pause=False)

        assert ctrl.exit_slideshow() is True
        mock_press.assert_called_with("esc", _pause=False)

    @patch("app.system_controls.pyautogui.hotkey")
    def test_window_shortcuts(self, mock_hotkey):
        ctrl = SystemControls()
        assert ctrl.open_settings() is True
        mock_hotkey.assert_called_with("win", "i", _pause=False)

        assert ctrl.open_file_explorer() is True
        mock_hotkey.assert_called_with("win", "e", _pause=False)


class TestExtendedControlModes:
    def test_control_mode_aliases(self):
        safety = SafetyController()
        # Aliases test
        assert ControlMode.DESKTOP_CONTROL.value == "MOUSE MODE"
        assert ControlMode.DESKTOP.value == "MOUSE MODE"
        assert ControlMode.HOLOGRAM_CONTROL.value == "3D LAB MODE"
        assert ControlMode.HOLOGRAM.value == "3D LAB MODE"
        assert ControlMode.PRESENTATION.value == "PRESENTATION MODE"
        assert ControlMode.KEYBOARD.value == "KEYBOARD MODE"
        assert ControlMode.HOLO_KEYBOARD.value == "KEYBOARD MODE"

        safety.enable_control()
        assert safety.switch_mode(ControlMode.PRESENTATION) is True
        assert safety.current_mode == ControlMode.PRESENTATION

    def test_hologram_lab_scenes_and_interaction(self, qapp):
        lab = HologramLabWidget()
        assert len(lab.SCENES) == 5
        assert lab.current_scene_name == "SPACE"

        next_s = lab.next_scene()
        assert next_s == "ENGINEERING"

        lab.set_scene("ARCHITECTURE")
        assert lab.current_scene_name == "ARCHITECTURE"

        lab.set_scene("REACTOR")
        assert lab.current_scene_name == "REACTOR"

        lab.set_scene("DATA")
        assert lab.current_scene_name == "DATA"

        # Selection toggle
        assert lab.is_selected is False
        lab.toggle_select()
        assert lab.is_selected is True

        # Rotate and zoom
        init_yaw = lab.yaw
        lab.rotate_by(10.0, 5.0)
        assert lab.yaw != init_yaw

        init_zoom = lab.zoom
        lab.zoom_by(0.2)
        assert lab.zoom > init_zoom

        lab.reset_view()
        assert lab.zoom == 1.0
        assert lab.is_selected is False

    def test_mode_isolation_prevents_desktop_mouse_dispatch(self):
        backend = MockMouseBackend()
        mouse = VirtualMouse(backend=backend)
        safety = SafetyController(hand_stable_delay=0.0)
        safety.enable_control()
        safety.on_hand_detected()

        worker = CameraWorker(mouse=mouse, safety=safety)

        # Switch to 3D LAB mode
        safety.switch_mode(ControlMode.LAB_3D)

        # Send gesture state in 3D LAB mode
        state = GestureState(
            gesture=GestureType.PINCH_LEFT_CLICK,
            cursor_coords=(0.5, 0.5),
            pinch_active=True
        )

        status = worker._dispatch_actions(state, None, fps=30.0)
        assert "3D Lab" in status.last_action
        # Verify no desktop clicks were sent to mouse backend
        click_events = [e for e in backend.events if e.event_type == "CLICK"]
        assert len(click_events) == 0
