"""Unit tests for Dual-Hand Air Keyboard and Automatic Mode Switching.

Verifies:
1. Two hands detected for confirmation duration (0.40s) automatically engages KEYBOARD_MODE.
2. Both index fingers independently hover and dwell-type without requiring any pinch gesture.
3. Single hand loss (left or right) enters SWITCHING_TO_MOUSE grace period (0.80s).
4. Persisting hand loss past grace period automatically transitions to MOUSE_MODE and releases held keys.
5. Transient hand loss (<0.80s) recovers smoothly back to KEYBOARD_MODE without dropping mode.
6. Re-introducing two hands for confirmation period re-engages KEYBOARD_MODE cleanly.
7. Duplicate character suppression prevents multiple keystrokes when both hands target the same key.
8. Curled/folded index finger is rejected by rotation-invariant angle checks, preventing unwanted typing.
"""

import time
import math
import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.camera_worker import CameraWorker, DualHandModeState
from app.hand_tracker import HandLandmarkData
from app.holographic_keyboard import HolographicKeyboardWidget, FingerPressState
from app.safety_controller import SafetyController, ControlMode, SystemState
from app.virtual_mouse import VirtualMouse


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    yield app


def make_hand(wrist_x=0.5, wrist_y=0.8, index_tip_x=0.5, index_tip_y=0.3,
              handedness="Right", is_curled=False, conf=0.95):
    """Constructs a realistic 21-landmark HandLandmarkData for testing."""
    lms = []
    pip_y = index_tip_y + 0.15 if not is_curled else index_tip_y - 0.05
    mcp_y = pip_y + 0.12 if not is_curled else pip_y + 0.10

    for i in range(21):
        if i == 0:
            lms.append((wrist_x, wrist_y, 0.0))
        elif i == 5:
            lms.append((index_tip_x, mcp_y, 0.0))
        elif i == 6:
            lms.append((index_tip_x, pip_y, -0.01))
        elif i == 8:
            lms.append((index_tip_x, index_tip_y, -0.05 if not is_curled else 0.05))
        elif i == 4:
            # Thumb tip separated from index
            lms.append((wrist_x - 0.10 if handedness == "Right" else wrist_x + 0.10, wrist_y - 0.20, 0.0))
        else:
            lms.append((wrist_x + 0.01 * (i % 5), wrist_y - 0.03 * i, 0.0))

    return HandLandmarkData(
        landmarks_norm=lms,
        landmarks_pixel=[(int(p[0] * 1280), int(p[1] * 720)) for p in lms],
        handedness=handedness,
        frame_width=1280,
        frame_height=720,
        confidence=conf,
        handedness_confidence=0.95
    )


class TestDualHandModeSwitching:
    """Tests CameraWorker and HolographicKeyboardWidget dual-hand mode transitions."""

    def test_two_hands_confirmation_engages_keyboard_mode(self, qapp):
        """Verifies two valid hands for 0.40s automatically triggers KEYBOARD_MODE."""
        safety = SafetyController()
        worker = CameraWorker(safety=safety, auto_activate_duration=0.40, auto_exit_duration=0.80)
        worker.auto_air_typing_enabled = True

        left_h = make_hand(wrist_x=0.3, index_tip_x=0.3, handedness="Left")
        right_h = make_hand(wrist_x=0.7, index_tip_x=0.7, handedness="Right")

        # Frame 1: Initial detection of two hands (starts timer)
        t0 = 1000.0
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0)
        assert worker.dual_hand_state == DualHandModeState.MOUSE_MODE
        assert safety.current_mode == ControlMode.MOUSE

        # Frame 2: 0.20s elapsed (under 0.40s threshold)
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 0.20)
        assert worker.dual_hand_state == DualHandModeState.MOUSE_MODE

        # Frame 3: 0.41s elapsed (meets >= 0.40s threshold) -> Engaging KEYBOARD_MODE
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 0.41)
        assert worker.dual_hand_state == DualHandModeState.KEYBOARD_MODE
        assert safety.current_mode == ControlMode.KEYBOARD

    def test_independent_dual_hand_dwell_typing(self, qapp):
        """Verifies both left and right index fingers can independently hover and dwell-type without pinching."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.clear_text()
        kb.press_detection_mode = "DWELL"
        kb.hover_dwell_time = 0.50
        kb.keypress_cooldown = 0.10

        # Position Left Hand over key 'a' (left side) and Right Hand over key 'l' (right side)
        key_a = next(k for k in kb.keys if k.key_id == "a")
        key_l = next(k for k in kb.keys if k.key_id == "l")
        ax, ay = kb.map_keyboard_to_camera(key_a.rect.center().x(), key_a.rect.center().y())
        lx, ly = kb.map_keyboard_to_camera(key_l.rect.center().x(), key_l.rect.center().y())

        left_h = make_hand(wrist_x=ax, index_tip_x=ax, index_tip_y=ay, handedness="Left")
        right_h = make_hand(wrist_x=lx, index_tip_x=lx, index_tip_y=ly, handedness="Right")

        # Frame 1: Initial hover
        t0 = 2000.0
        kb.process_multi_hands([left_h, right_h], timestamp=t0)
        assert kb.fingers["L_INDEX"].last_hovered_key_id == "a"
        assert kb.fingers["R_INDEX"].last_hovered_key_id == "l"
        assert kb.text_buffer == ""

        # Frame 2: 0.25s dwell (progress ~ 50%)
        kb.process_multi_hands([left_h, right_h], timestamp=t0 + 0.25)
        assert 0.40 <= kb.fingers["L_INDEX"].dwell_progress <= 0.60
        assert 0.40 <= kb.fingers["R_INDEX"].dwell_progress <= 0.60
        assert kb.text_buffer == ""

        # Frame 3: 0.52s dwell (progress >= 100%) -> Both keys actuate independently
        kb.process_multi_hands([left_h, right_h], timestamp=t0 + 0.52)
        assert "a" in kb.text_buffer
        assert "l" in kb.text_buffer

    def test_hand_loss_enters_grace_period_and_exits_to_mouse(self, qapp):
        """Verifies dropping one hand triggers SWITCHING_TO_MOUSE and returns to MOUSE_MODE after 0.80s."""
        safety = SafetyController()
        worker = CameraWorker(safety=safety, auto_activate_duration=0.40, auto_exit_duration=0.80)
        worker.auto_air_typing_enabled = True

        left_h = make_hand(wrist_x=0.3, index_tip_x=0.3, handedness="Left")
        right_h = make_hand(wrist_x=0.7, index_tip_x=0.7, handedness="Right")

        # Start in KEYBOARD_MODE
        t0 = 3000.0
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0)
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 0.45)
        assert worker.dual_hand_state == DualHandModeState.KEYBOARD_MODE
        assert safety.current_mode == ControlMode.KEYBOARD

        # Left hand dropped (only right hand visible)
        t_drop = t0 + 1.0
        worker._update_dual_hand_mode_state([right_h], now=t_drop)
        assert worker.dual_hand_state == DualHandModeState.SWITCHING_TO_MOUSE
        assert safety.current_mode == ControlMode.KEYBOARD  # Grace period maintains keyboard
        assert 0.70 <= worker.switching_countdown <= 0.80

        # After 0.40s in grace period (still within 0.80s timeout)
        worker._update_dual_hand_mode_state([right_h], now=t_drop + 0.40)
        assert worker.dual_hand_state == DualHandModeState.SWITCHING_TO_MOUSE
        assert safety.current_mode == ControlMode.KEYBOARD

        # After 0.85s (exceeds 0.80s timeout) -> Switches to MOUSE_MODE
        worker._update_dual_hand_mode_state([right_h], now=t_drop + 0.85)
        assert worker.dual_hand_state == DualHandModeState.MOUSE_MODE
        assert safety.current_mode == ControlMode.MOUSE

    def test_transient_hand_drop_recovers_to_keyboard_mode(self, qapp):
        """Verifies momentary hand drop (<0.80s) recovers smoothly back to KEYBOARD_MODE."""
        safety = SafetyController()
        worker = CameraWorker(safety=safety, auto_activate_duration=0.40, auto_exit_duration=0.80)
        worker.auto_air_typing_enabled = True

        left_h = make_hand(wrist_x=0.3, index_tip_x=0.3, handedness="Left")
        right_h = make_hand(wrist_x=0.7, index_tip_x=0.7, handedness="Right")

        # Establish KEYBOARD_MODE
        t0 = 4000.0
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0)
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 0.45)
        assert worker.dual_hand_state == DualHandModeState.KEYBOARD_MODE

        # Transient hand drop for 0.30s (<0.80s)
        t_drop = t0 + 1.0
        worker._update_dual_hand_mode_state([right_h], now=t_drop)
        assert worker.dual_hand_state == DualHandModeState.SWITCHING_TO_MOUSE

        # Second hand returns at 0.30s
        worker._update_dual_hand_mode_state([left_h, right_h], now=t_drop + 0.30)
        assert worker.dual_hand_state == DualHandModeState.KEYBOARD_MODE
        assert safety.current_mode == ControlMode.KEYBOARD
        assert worker.last_mode_transition_reason == "TWO_HANDS_RESTORED"

    def test_reintroducing_two_hands_reengages_keyboard_mode(self, qapp):
        """Verifies that re-presenting two hands after returning to mouse control re-engages keyboard."""
        safety = SafetyController()
        worker = CameraWorker(safety=safety, auto_activate_duration=0.40, auto_exit_duration=0.80)
        worker.auto_air_typing_enabled = True

        left_h = make_hand(wrist_x=0.3, index_tip_x=0.3, handedness="Left")
        right_h = make_hand(wrist_x=0.7, index_tip_x=0.7, handedness="Right")

        # Start in MOUSE_MODE
        t0 = 5000.0
        worker._update_dual_hand_mode_state([right_h], now=t0)
        assert worker.dual_hand_state == DualHandModeState.MOUSE_MODE

        # Introduce two hands
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 1.0)
        assert worker.dual_hand_state == DualHandModeState.MOUSE_MODE

        # Hold for 0.45s (exceeds 0.40s confirmation)
        worker._update_dual_hand_mode_state([left_h, right_h], now=t0 + 1.45)
        assert worker.dual_hand_state == DualHandModeState.KEYBOARD_MODE
        assert safety.current_mode == ControlMode.KEYBOARD

    def test_duplicate_character_suppression_on_same_key(self, qapp):
        """Verifies that if both left and right hands target the same key, only one keystroke occurs."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.clear_text()
        kb.press_detection_mode = "DWELL"
        kb.hover_dwell_time = 0.50
        kb.keypress_cooldown = 0.20

        # Both hands point at key 'g' (center keyboard)
        key_g = next(k for k in kb.keys if k.key_id == "g")
        gx, gy = kb.map_keyboard_to_camera(key_g.rect.center().x(), key_g.rect.center().y())

        left_h = make_hand(wrist_x=gx - 0.05, index_tip_x=gx, index_tip_y=gy, handedness="Left")
        right_h = make_hand(wrist_x=gx + 0.05, index_tip_x=gx, index_tip_y=gy, handedness="Right")

        t0 = 6000.0
        kb.process_multi_hands([left_h, right_h], timestamp=t0)
        # Actuate after 0.52s dwell
        kb.process_multi_hands([left_h, right_h], timestamp=t0 + 0.52)

        # Buffer must have exactly one 'g', never duplicate 'gg'
        assert kb.text_buffer == "g"

    def test_curled_index_finger_suppressed(self, qapp):
        """Verifies that curled or folded index fingers do not select keys or trigger typing."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.clear_text()
        kb.press_detection_mode = "DWELL"

        key_j = next(k for k in kb.keys if k.key_id == "j")
        jx, jy = kb.map_keyboard_to_camera(key_j.rect.center().x(), key_j.rect.center().y())

        # Curled hand at key 'j'
        curled_hand = make_hand(wrist_x=jx, index_tip_x=jx, index_tip_y=jy, handedness="Right", is_curled=True)

        t0 = 7000.0
        kb.process_multi_hands([curled_hand], timestamp=t0)
        assert kb.fingers["R_INDEX"].state == FingerPressState.IDLE
        assert "INDEX FOLDED" in kb.fingers["R_INDEX"].last_rejection_reason
        assert kb.text_buffer == ""

    def test_draw_text_preview_handles_enum_and_string_dual_hand_states(self, qapp):
        """Verifies that _draw_text_preview never raises TypeError when dual_hand_mode_state is an Enum or String."""
        from PySide6.QtGui import QPixmap, QPainter
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        pix = QPixmap(1000, 600)

        for test_val in [
            DualHandModeState.KEYBOARD_MODE,
            DualHandModeState.SWITCHING_TO_MOUSE,
            DualHandModeState.MOUSE_MODE,
            "KEYBOARD_MODE",
            "SWITCHING_TO_MOUSE",
            "MOUSE_MODE",
            None
        ]:
            kb.dual_hand_mode_state = test_val
            kb.mode_switch_countdown = 0.5 if "SWITCHING" in str(test_val) else 0.0
            p = QPainter(pix)
            # Must execute without raising TypeError: argument of type 'DualHandModeState' is not iterable
            kb._draw_text_preview(p, 1000.0, 600.0)
            p.end()
