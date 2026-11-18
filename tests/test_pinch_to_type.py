"""Unit tests for N.E.X.U.S. Pinch-to-Type Gesture Engine & One-Hand Air Keyboard."""

import time
import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from app.holographic_keyboard import HolographicKeyboardWidget, FingerPressState
from app.windows_keyboard_service import WindowsKeyboardInputService, MockKeyboardBackend


class MockPinchHand:
    """Mock hand landmarks providing 2D coordinates and scale-invariant pinch metric."""
    def __init__(self, index_x=0.5, index_y=0.5, norm_pinch=1.0, handedness="Right"):
        self.x = index_x
        self.y = index_y
        self.norm_pinch_distance = norm_pinch
        self.pinch_distance = norm_pinch * 0.12  # dummy raw distance
        self.handedness = handedness
        self.handedness_confidence = 0.95
        self.confidence = 0.95

        # Construct realistic normalized landmarks
        # Index tip stays anchored to the hovered point
        palm_size = 0.12
        wrist = (index_x, index_y + palm_size)
        middle_mcp = (index_x, index_y + 0.04)
        index_tip = (index_x, index_y)
        # Thumb tip closes distance towards index tip
        thumb_tip = (index_x - (norm_pinch * palm_size), index_y)

        self.landmarks_norm = [(0.5, 0.5)] * 21
        self.landmarks_norm[0] = wrist
        self.landmarks_norm[4] = thumb_tip
        self.landmarks_norm[8] = index_tip
        self.landmarks_norm[9] = middle_mcp

    def get_finger_tip(self, finger_name="index"):
        if finger_name == "thumb":
            return self.landmarks_norm[4][0], self.landmarks_norm[4][1], 0.0
        elif finger_name == "index":
            return self.landmarks_norm[8][0], self.landmarks_norm[8][1], 0.0
        return self.x, self.y, 0.0

    def get_tracking_point(self, landmark_name="index_tip"):
        if landmark_name == "wrist":
            return self.landmarks_norm[0]
        elif landmark_name == "index_tip":
            return self.landmarks_norm[8]
        return self.x, self.y


class TestPinchToType:
    @pytest.fixture
    def kb(self, qapp):
        widget = HolographicKeyboardWidget()
        widget.clear_text()
        widget.resize(1000, 600)
        widget._recalculate_key_geometry()
        widget.roi_left = 0.0
        widget.roi_right = 1.0
        widget.roi_top = 0.0
        widget.roi_bottom = 1.0
        widget.test_mode = True  # dry-run internal buffer
        widget.press_detection_mode = "PINCH"
        widget.one_hand_test_mode = True
        widget.active_typing_hand = "RIGHT"
        widget.keypress_cooldown = 0.0
        return widget

    def test_one_hand_test_mode_isolation(self, kb):
        """Verifies that in One-Hand Test Mode, only the right hand types, and the left hand is idled."""
        assert kb.one_hand_test_mode is True
        assert kb.active_typing_hand == "RIGHT"

        # Position over key 'a' (left side of keyboard)
        key_a = next(k for k in kb.keys if k.key_id == "a")
        pt_a = key_a.rect.center()
        norm_ax, norm_ay = kb.map_keyboard_to_camera(pt_a.x(), pt_a.y())

        # Attempt to pinch with a Left Hand
        left_hand = MockPinchHand(index_x=norm_ax, index_y=norm_ay, norm_pinch=0.20, handedness="Left")
        kb.process_multi_hands([left_hand])

        # In 1-Hand Right mode, Left Hand is strictly idled; nothing is typed!
        assert kb.fingers["L_INDEX"].state == FingerPressState.IDLE
        assert kb.text_buffer == ""

        # Toggle to 2-Hand mode
        kb.toggle_one_hand_mode()
        assert kb.one_hand_test_mode is False

        # In 2-Hand mode, Left Hand pinch now registers
        kb.process_multi_hands([left_hand])
        assert kb.text_buffer == "a"

    def test_five_stage_pinch_to_type_cycle(self, kb):
        """
        Verifies the strict 5-stage Pinch-to-Type state machine:
        1. HOVER -> Key highlights cyan, no keystroke
        2. PINCH_CANDIDATE -> Approaching pinch, no keystroke
        3. PRESSED -> Deliberate pinch touch, exactly ONE keystroke
        4. WAIT_FOR_RELEASE -> Holding pinch produces ZERO repeated keystrokes
        5. HOVER -> Re-armed on release; second pinch types second char
        """
        # Find key 'j' (home row right hand)
        key_j = next(k for k in kb.keys if k.key_id == "j")
        pt_j = key_j.rect.center()
        nx, ny = kb.map_keyboard_to_camera(pt_j.x(), pt_j.y())

        f_index = kb.fingers["R_INDEX"]

        # Stage 1: HOVER (norm_pinch = 0.85 > 0.44 candidate threshold)
        hand_hover = MockPinchHand(index_x=nx, index_y=ny, norm_pinch=0.85, handedness="Right")
        kb.process_multi_hands([hand_hover])

        assert key_j.is_hovered is True
        assert f_index.state == FingerPressState.HOVER
        assert f_index.is_pressed is False
        assert kb.text_buffer == ""

        # Stage 2: PINCH_CANDIDATE (0.32 < norm_pinch = 0.40 <= 0.44)
        hand_candidate = MockPinchHand(index_x=nx, index_y=ny, norm_pinch=0.40, handedness="Right")
        kb.process_multi_hands([hand_candidate])

        assert f_index.state == FingerPressState.PINCH_CANDIDATE
        assert f_index.is_pressed is False
        assert kb.text_buffer == ""

        # Stage 3: PRESSED (norm_pinch = 0.22 <= 0.32 confirmed threshold)
        hand_pressed = MockPinchHand(index_x=nx, index_y=ny, norm_pinch=0.22, handedness="Right")
        kb.process_multi_hands([hand_pressed])

        assert f_index.state == FingerPressState.PRESSED
        assert f_index.is_pressed is True
        assert f_index.press_locked is True
        assert kb.text_buffer == "j"

        # Stage 4: WAIT_FOR_RELEASE (Held pinch: norm_pinch = 0.22)
        # Process multiple frames while holding pinch
        kb.process_multi_hands([hand_pressed])
        kb.process_multi_hands([hand_pressed])

        assert f_index.state == FingerPressState.WAIT_FOR_RELEASE
        assert f_index.is_pressed is False
        # Strictly NO repeated characters while held!
        assert kb.text_buffer == "j"

        # Stage 5: RE-ARM on deliberate release (norm_pinch = 0.65 >= 0.50)
        hand_released = MockPinchHand(index_x=nx, index_y=ny, norm_pinch=0.65, handedness="Right")
        kb.process_multi_hands([hand_released])

        assert f_index.state == FingerPressState.HOVER
        assert f_index.press_locked is False
        assert kb.text_buffer == "j"

        # Subsequent intentional press: second pinch generates second 'j'
        kb.process_multi_hands([hand_pressed])
        assert f_index.state == FingerPressState.PRESSED
        assert kb.text_buffer == "jj"

    def test_backspace_and_space_via_pinch(self, kb):
        """Verifies Space and Backspace execution using deliberate pinch."""
        kb._insert_text("ABC")
        assert kb.text_buffer == "ABC"

        # Position over Backspace key
        key_bsp = next(k for k in kb.keys if k.key_id == "bsp")
        pt_bsp = key_bsp.rect.center()
        nx_bsp, ny_bsp = kb.map_keyboard_to_camera(pt_bsp.x(), pt_bsp.y())

        hand_bsp_press = MockPinchHand(index_x=nx_bsp, index_y=ny_bsp, norm_pinch=0.20, handedness="Right")
        kb.process_multi_hands([hand_bsp_press])
        assert kb.text_buffer == "AB"

        # Release pinch
        hand_bsp_release = MockPinchHand(index_x=nx_bsp, index_y=ny_bsp, norm_pinch=0.70, handedness="Right")
        kb.process_multi_hands([hand_bsp_release])

        # Settle over Space key (hover frame to reset lateral movement)
        time.sleep(0.22)
        key_spc = next(k for k in kb.keys if k.key_id == "space")
        pt_spc = key_spc.rect.center()
        nx_spc, ny_spc = kb.map_keyboard_to_camera(pt_spc.x(), pt_spc.y())
        hand_spc_hover = MockPinchHand(index_x=nx_spc, index_y=ny_spc, norm_pinch=0.80, handedness="Right")
        kb.process_multi_hands([hand_spc_hover])

        # Pinch over Space key
        hand_spc_press = MockPinchHand(index_x=nx_spc, index_y=ny_spc, norm_pinch=0.20, handedness="Right")
        kb.process_multi_hands([hand_spc_press])
        assert kb.text_buffer == "AB "

    def test_send_test_key_dispatch(self, kb):
        """Verifies send_test_key sends a harmless 'a' character via WindowsKeyboardInputService."""
        mock_backend = MockKeyboardBackend()
        kb.keyboard_service = WindowsKeyboardInputService(backend=mock_backend)
        kb.keyboard_service.last_external_title = "Notepad - TestDoc"
        kb.keyboard_service.is_enabled = True

        ok, msg = kb.send_test_key("a")
        assert ok is True
        assert "SUCCESS" in msg or "VK" in msg or "Sent" in msg
        # Verify keystroke was received by mock backend
        assert len(mock_backend.events) >= 2  # down + up

    def test_lateral_swipe_rejection(self, kb):
        """Verifies that rapid sideways swipe during pinch is rejected to prevent accidental typos."""
        key_h = next(k for k in kb.keys if k.key_id == "h")
        pt_h = key_h.rect.center()
        nx, ny = kb.map_keyboard_to_camera(pt_h.x(), pt_h.y())

        f_index = kb.fingers["R_INDEX"]
        # Seed previous position 100px away
        f_index.prev_canvas_pos = (pt_h.x() - 100.0, pt_h.y())

        # Close pinch during rapid motion
        hand_swipe = MockPinchHand(index_x=nx, index_y=ny, norm_pinch=0.20, handedness="Right")
        kb.process_multi_hands([hand_swipe])

        # Must reject swipe
        assert f_index.state == FingerPressState.PINCH_CANDIDATE
        assert f_index.last_rejection_reason == "REJECTED (LATERAL_SWIPE)"
        assert kb.text_buffer == ""
