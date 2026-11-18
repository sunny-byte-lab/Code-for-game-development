"""Unit tests for the Iron Man-style Holographic Virtual Keyboard and Text Editor."""

import os
import time
import pytest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from app.holographic_keyboard import HolographicKeyboardWidget, KeyDef
from app.safety_controller import SafetyController, ControlMode
from app.virtual_mouse import VirtualMouse, MockMouseBackend
from app.camera_worker import CameraWorker
from app.gesture_recognizer import GestureState, GestureType


class DummyHand:
    """Mock hand landmark data for headless testing."""
    def __init__(self, x=0.5, y=0.5, pinch_dist=1.0):
        self.x = x
        self.y = y
        self.norm_pinch_distance = pinch_dist
        self.pinch_distance = pinch_dist
        self.handedness = "Right"

    def get_tracking_point(self, landmark_name="index_tip"):
        return self.x, self.y


class TestHolographicKeyboard:
    def test_keyboard_layout_completeness(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.resize(800, 600)
        # Verify 5 rows
        assert len(kb.keyboard_rows) == 5
        # Verify letters A-Z are present
        all_chars = set()
        for k in kb.keys:
            if k.char:
                all_chars.add(k.char.lower())
        for code in range(ord('a'), ord('z') + 1):
            assert chr(code) in all_chars, f"Letter {chr(code)} missing from keyboard layout"

        # Verify digits 0-9 are present
        for digit in "0123456789":
            assert digit in all_chars, f"Digit {digit} missing from keyboard layout"

        # Verify essential control keys
        key_ids = {k.key_id for k in kb.keys}
        assert "esc" in key_ids
        assert "bsp" in key_ids
        assert "tab" in key_ids
        assert "caps" in key_ids
        assert "enter" in key_ids
        assert "space" in key_ids
        assert "shift_l" in key_ids or "shift" in key_ids
        assert "up" in key_ids
        assert "down" in key_ids
        assert "left" in key_ids
        assert "right" in key_ids
        assert "clr" in key_ids
        assert "copy" in key_ids
        assert "paste" in key_ids

    def test_text_editor_operations(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        assert kb.text_buffer == ""

        # Insert characters
        kb._insert_text("JARVIS")
        assert kb.text_buffer == "JARVIS"
        assert kb.cursor_pos == 6

        # Space and Backspace
        kb._insert_text(" ")
        assert kb.text_buffer == "JARVIS "
        kb._action_backspace()
        assert kb.text_buffer == "JARVIS"

        # Newline
        kb._insert_text("\nONLINE")
        assert kb.text_buffer == "JARVIS\nONLINE"

        # Cursor movement
        kb.cursor_pos = 0
        kb._insert_text("HELLO ")
        assert kb.text_buffer == "HELLO JARVIS\nONLINE"

        # Select all and copy
        kb.select_all()
        assert kb.get_selected_text() == "HELLO JARVIS\nONLINE"
        kb.copy_to_clipboard()
        cb = QApplication.clipboard()
        assert cb.text() == "HELLO JARVIS\nONLINE"

        # Clear text
        kb.clear_text()
        assert kb.text_buffer == ""
        assert kb.cursor_pos == 0

        # Paste from clipboard
        kb.paste_from_clipboard()
        assert kb.text_buffer == "HELLO JARVIS\nONLINE"

    def test_shift_and_caps_lock(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.clear_text()

        # Find key 'a'
        key_a = next(k for k in kb.keys if k.key_id == "a")
        # Normal typing (lowercase)
        kb._execute_key(key_a)
        assert kb.text_buffer == "a"

        # Caps Lock ON
        kb.is_caps_lock = True
        kb._execute_key(key_a)
        assert kb.text_buffer == "aA"

        # Caps Lock OFF, Shift ON (One-shot)
        kb.is_caps_lock = False
        kb.is_shift = True
        kb._execute_key(key_a)
        assert kb.text_buffer == "aAA"
        # Shift should automatically reset after typing regular char
        assert kb.is_shift is False

        # Numbers to symbols with Shift
        key_1 = next(k for k in kb.keys if k.key_id == "1")
        kb._execute_key(key_1)
        assert kb.text_buffer == "aAA1"

        kb.is_shift = True
        kb._execute_key(key_1)
        assert kb.text_buffer == "aAA1!"
        assert kb.is_shift is False

    def test_pinch_to_type_hysteresis_and_single_keypress(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        kb.resize(800, 600)
        kb._recalculate_key_geometry()
        kb.roi_left = 0.0
        kb.roi_right = 1.0
        kb.roi_top = 0.0
        kb.roi_bottom = 1.0
        kb.sensitivity_x = 1.0
        kb.sensitivity_y = 1.0

        # Force key 'z' position
        key_z = next(k for k in kb.keys if k.key_id == "z")
        center = key_z.rect.center()
        kb.hovered_key = key_z

        # 1. Approach without pinch (pinch_dist = 0.8 > threshold)
        hand = DummyHand(x=center.x() / 800.0, y=center.y() / 600.0, pinch_dist=0.8)
        state = GestureState(GestureType.INDEX_POINT)
        kb.process_hand_frame(hand, state)
        assert kb.text_buffer == ""
        assert kb.is_pinch_active is False

        # 2. Pinch closes below threshold (pinch_dist = 0.25 < 0.38)
        hand_pinch = DummyHand(x=center.x() / 800.0, y=center.y() / 600.0, pinch_dist=0.25)
        kb.process_hand_frame(hand_pinch, state)
        # Should type 'z' exactly once!
        assert kb.text_buffer == "z"
        assert kb.is_pinch_active is True
        assert kb.pinch_locked is True

        # 3. Hold pinch in subsequent frames
        kb.process_hand_frame(hand_pinch, state)
        kb.process_hand_frame(hand_pinch, state)
        # Must NOT repeat character while held!
        assert kb.text_buffer == "z"

        # 4. Release fingers (pinch_dist = 0.65 > release threshold 0.52)
        hand_release = DummyHand(x=center.x() / 800.0, y=center.y() / 600.0, pinch_dist=0.65)
        kb.process_hand_frame(hand_release, state)
        assert kb.is_pinch_active is False
        assert kb.pinch_locked is False
        assert kb.text_buffer == "z"

        # 5. Pinch again after separating
        time.sleep(0.01)
        kb.last_keypress_time = 0.0  # bypass cooldown for test
        kb.process_hand_frame(hand_pinch, state)
        # Should now type second 'z'
        assert kb.text_buffer == "zz"

    def test_tracking_loss_resets_pinch_state_safely(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.is_pinch_active = True
        kb.pinch_locked = True
        kb.pointer_visible = True

        # Hand lost
        kb.process_hand_frame(None, GestureState(GestureType.NONE))
        assert kb.is_hand_present is False
        assert kb.pointer_visible is False
        assert kb.is_pinch_active is False
        assert kb.pinch_locked is False

    @patch("app.holographic_keyboard.pyautogui.write")
    def test_external_typing_mode_safety(self, mock_write, qapp):
        kb = HolographicKeyboardWidget()
        kb.clear_text()
        key_h = next(k for k in kb.keys if k.key_id == "h")

        # 1. External typing disabled by default
        assert kb.external_typing_enabled is False
        kb._execute_key(key_h)
        assert kb.text_buffer == "h"
        # Verify pyautogui was NOT called
        mock_write.assert_not_called()

        # 2. Explicitly toggle external typing
        kb.toggle_external_typing()
        assert kb.external_typing_enabled is True

        kb._execute_key(key_h)
        assert kb.text_buffer == "hh"
        mock_write.assert_called_with("h", _pause=False)

    def test_save_to_local_file(self, qapp, tmp_path):
        kb = HolographicKeyboardWidget()
        kb.text_buffer = "TEST STARK LOG 402."
        test_file = str(tmp_path / "test_notes.txt")

        success = kb.save_to_file(test_file)
        assert success is True
        assert os.path.exists(test_file)
        with open(test_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == "TEST STARK LOG 402."

    def test_keyboard_mode_isolation_from_desktop_mouse(self):
        backend = MockMouseBackend()
        mouse = VirtualMouse(backend=backend)
        safety = SafetyController(hand_stable_delay=0.0)
        safety.enable_control()
        safety.on_hand_detected()

        worker = CameraWorker(mouse=mouse, safety=safety)

        # Switch to KEYBOARD mode
        assert safety.switch_mode(ControlMode.KEYBOARD) is True
        assert safety.current_mode == ControlMode.KEYBOARD

        # Send pinch in KEYBOARD mode
        state = GestureState(
            gesture=GestureType.PINCH_LEFT_CLICK,
            cursor_coords=(0.5, 0.5),
            pinch_active=True
        )

        status = worker._dispatch_actions(state, None, fps=30.0)
        assert "Keyboard" in status.last_action

        # Confirm that no desktop click events were dispatched to OS backend
        click_events = [e for e in backend.events if e.event_type == "CLICK"]
        assert len(click_events) == 0

    def test_paint_event_rendering_all_states(self, qapp):
        """Exercises the complete QPainter rendering pipeline across all UI and calibration states."""
        from PySide6.QtGui import QPixmap, QPainter
        kb = HolographicKeyboardWidget()
        kb.resize(1024, 768)
        kb._recalculate_key_geometry()

        pixmap = QPixmap(1024, 768)

        # 1. Standard Test Mode rendering with HUD
        kb.test_mode = True
        kb.show_diagnostics_hud = True
        kb.is_calibrated = False
        kb.calibration_active = False
        p = QPainter(pixmap)
        kb.paintEvent(MagicMock())
        p.end()

        # 2. Calibrating state rendering
        kb.calibration_active = True
        p = QPainter(pixmap)
        kb.paintEvent(MagicMock())
        p.end()

        # 3. Calibrated state with Live Global Input
        kb.calibration_active = False
        kb.is_calibrated = True
        kb.set_test_mode(False)
        kb.set_global_typing(True)
        kb.show_diagnostics_hud = False
        p = QPainter(pixmap)
        kb.paintEvent(MagicMock())
        p.end()
