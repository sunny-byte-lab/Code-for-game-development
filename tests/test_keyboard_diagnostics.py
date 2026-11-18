"""Comprehensive tests for N.E.X.U.S. Keyboard Diagnostics Panel, Dwell-to-Type Engine,
and Global Overlay non-focus-stealing integration.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtWidgets import QApplication

from app.holographic_keyboard import HolographicKeyboardWidget, FingerPressState
from app.keyboard_diagnostics_dialog import KeyboardDiagnosticsDialog
from app.global_keyboard_overlay import GlobalKeyboardOverlay
from app.hand_tracker import HandLandmarkData


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestKeyboardDiagnosticsAndDwell:
    def test_keyboard_diagnostics_dialog_initialization(self, qapp):
        kb = HolographicKeyboardWidget()
        diag = KeyboardDiagnosticsDialog(kb)
        assert diag.windowTitle() == "N.E.X.U.S. // AIR KEYBOARD DIAGNOSTICS & SYSTEM AUDIT"
        assert len(diag.test_buttons) == 8
        diag.close()

    def test_run_all_8_tests_automated(self, qapp):
        kb = HolographicKeyboardWidget()
        diag = KeyboardDiagnosticsDialog(kb)
        
        # Run all 8 tests sequentially
        test_funcs = [
            diag.run_test_1_visibility,
            diag.run_test_2_landmarks,
            diag.run_test_3_key_under_fingertip,
            diag.run_test_4_single_event,
            diag.run_test_5_notepad,
            diag.run_test_6_control_keys,
            diag.run_test_7_chrome,
            diag.run_test_8_hand_loss
        ]
        
        for i, fn in enumerate(test_funcs, 1):
            res = fn()
            assert res is True, f"Diagnostic Test {i} ({fn.__name__}) failed!"
            
        diag.close()

    def test_dwell_to_type_accumulation_and_trigger(self, qapp):
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.clear_text()
        kb.press_detection_mode = "HYBRID"
        kb.hover_dwell_time = 0.20  # Fast dwell for testing
        kb.keypress_cooldown = 0.10
        
        # Position index finger over key 'a'
        key_a = next(k for k in kb.keys if k.key_id == "a")
        center_a = key_a.rect.center()
        
        # Use inverse mapping to find normalized camera coordinates for key 'a'
        cam_x, cam_y = kb.map_keyboard_to_camera(center_a.x(), center_a.y())
        
        hand = MagicMock(spec=HandLandmarkData)
        hand.handedness = "Right"
        hand.confidence = 0.95
        hand.norm_pinch_distance = 0.85  # No pinch (wide open)
        hand.pinch_distance = 0.85
        # Landmarks: thumb (idx 4) at cam_x - 0.2, index (idx 8) at cam_x
        landmarks = [(cam_x, cam_y, 0.0)] * 21
        landmarks[4] = (cam_x - 0.2, cam_y, 0.0)
        landmarks[8] = (cam_x, cam_y, 0.0)
        hand.landmarks_norm = landmarks
        hand.get_finger_tip = MagicMock(return_value=(cam_x, cam_y, 0.0))
        hand.get_tracking_point = MagicMock(return_value=(cam_x, cam_y, 0.0))
        hand.get_thumb_index_pinch = MagicMock(return_value=0.85)
        hand.get_raw_finger_metric = MagicMock(return_value=0.02)  # No forward depth
        
        # Frame 1: Initial hover
        t0 = 1000.0
        kb.process_multi_hands([hand], timestamp=t0)
        assert kb.last_hovered_key_id == "a"
        assert kb.dwell_progress < 1.0
        assert kb.text_buffer == ""
        
        # Frame 2: Halfway dwell (0.10s)
        t1 = t0 + 0.10
        kb.process_multi_hands([hand], timestamp=t1)
        assert 0.35 <= kb.dwell_progress <= 0.65
        assert kb.text_buffer == ""
        
        # Frame 3: Completed dwell (0.22s) -> triggers keypress!
        t2 = t0 + 0.22
        kb.process_multi_hands([hand], timestamp=t2)
        assert kb.dwell_progress >= 1.0
        assert kb.dwell_locked_key_id == "a"
        assert kb.text_buffer == "a"
        
        # Frame 4: Steady hover after dwell triggers -> zero repeat!
        t3 = t0 + 0.35
        kb.process_multi_hands([hand], timestamp=t3)
        assert kb.text_buffer == "a"  # Unchanged! Zero repeats while holding hover

    def test_global_keyboard_overlay_attributes_and_flags(self, qapp):
        kb = HolographicKeyboardWidget()
        overlay = GlobalKeyboardOverlay(kb)
        
        # Verify non-focus-stealing flags
        flags = overlay.windowFlags()
        assert bool(flags & Qt.WindowType.FramelessWindowHint) is True
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True
        assert bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus) is True
        
        # Verify toggle behavior
        assert overlay.is_visible is False
        assert overlay.toggle_overlay() is True
        assert overlay.is_visible is True
        assert overlay.toggle_overlay() is False
        assert overlay.is_visible is False
        overlay.close()
