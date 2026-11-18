"""Comprehensive unit test suite for N.E.X.U.S. Hands-Free Dwell-to-Type Air Keyboard.

Verifies:
1. DWELL mode is default mode.
2. Holding index finger steady over a virtual key for 0.5s triggers typing without pinch.
3. Natural hand tremor/jitter tolerance (< 25px) allows dwell accumulation without resetting.
4. Stationary finger on key produces zero repeated characters (single-shot hysteresis lock).
5. Moving off key clears the lock and allows re-arming.
6. Moving to a new key types the next key after dwell period.
7. Leaving key early (< 0.5s) cancels dwell with zero keystrokes generated.
8. Hand tracking loss immediately cancels dwell timer with zero keystrokes generated.
9. Mode switching between DWELL and PINCH works seamlessly.
10. SettingsDialog persists air keyboard configuration to settings manager.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from app.hand_tracker import (
    HandLandmarkData,
    WRIST, THUMB_TIP, INDEX_TIP, INDEX_DIP, INDEX_PIP, INDEX_MCP,
    MIDDLE_TIP, MIDDLE_DIP, MIDDLE_PIP, MIDDLE_MCP, RING_TIP, PINKY_TIP
)
from app.holographic_keyboard import HolographicKeyboardWidget, KeyDef, FingerPressState
from app.settings_manager import SettingsManager
from app.settings_dialog import SettingsDialog


def make_hand(wrist_x: float, wrist_y: float, index_x: float, index_y: float, thumb_x: float, thumb_y: float, handedness: str = "Right"):
    """Creates a 21-point HandLandmarkData with explicit thumb and index coordinates."""
    w, h = 640, 480
    landmarks_norm = []
    landmarks_pixel = []

    # 21 landmarks
    for idx in range(21):
        if idx == 0:
            x, y, z = wrist_x, wrist_y, 0.0
        elif idx == 4:
            x, y, z = thumb_x, thumb_y, 0.0
        elif idx == 8:
            x, y, z = index_x, index_y, 0.0
        elif idx in (5, 6, 7):
            inter = (idx - 4) / 4.0
            x = wrist_x + (index_x - wrist_x) * inter
            y = wrist_y + (index_y - wrist_y) * inter
            z = 0.0
        elif idx in (1, 2, 3):
            inter = idx / 4.0
            x = wrist_x + (thumb_x - wrist_x) * inter
            y = wrist_y + (thumb_y - wrist_y) * inter
            z = 0.0
        else:
            x = wrist_x + 0.05
            y = wrist_y - 0.10
            z = 0.0
        landmarks_norm.append((x, y, z))
        landmarks_pixel.append((int(x * w), int(y * h)))

    return HandLandmarkData(
        landmarks_norm=landmarks_norm,
        landmarks_pixel=landmarks_pixel,
        handedness=handedness,
        frame_width=w,
        frame_height=h
    )


class TestHandsFreeDwellTyping:

    def test_default_typing_mode_is_dwell(self, qapp):
        """Verifies DWELL is the default mode with 0.5s duration and 25px tolerance."""
        kb = HolographicKeyboardWidget()
        assert kb.press_detection_mode == "DWELL"
        assert kb.hover_dwell_time == 0.50
        assert kb.dwell_jitter_tolerance == 25.0
        assert kb.keypress_cooldown == 0.20
        assert kb.dwell_progress == 0.0
        assert kb.dwell_locked_key_id is None

    def test_dwell_to_type_activation_without_pinch(self, qapp):
        """Hovering index finger steadily over a key for >= 0.5s types without pinching."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        # Position hand over 'J' or 'K' in right hand zone
        # Thumb and index are separated (distance ~ 0.25, no pinch)
        hand = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.70, thumb_y=0.60, handedness="Right")

        base_time = 1000.0

        # Frame 1: at t=0.0s (dwell starts)
        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand])
        assert len(triggered_keys) == 0
        assert kb.dwell_progress == 0.0
        assert kb.last_hovered_key_id is not None
        hovered_key_id = kb.last_hovered_key_id

        # Frame 2: at t=0.25s (halfway)
        with patch("time.time", return_value=base_time + 0.25):
            kb.process_multi_hands([hand])
        assert len(triggered_keys) == 0
        assert 0.45 <= kb.dwell_progress <= 0.55

        # Frame 3: at t=0.55s (dwell threshold exceeded)
        with patch("time.time", return_value=base_time + 0.55):
            kb.process_multi_hands([hand])

        # Exactly 1 keypress generated!
        assert len(triggered_keys) == 1
        assert triggered_keys[0] == hovered_key_id
        assert kb.dwell_locked_key_id == hovered_key_id

    def test_zero_repeated_characters_while_stationary(self, qapp):
        """Holding finger stationary on a key after typing produces zero repeats."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        hand = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        base_time = 1000.0

        # Dwell to type
        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand])
        with patch("time.time", return_value=base_time + 0.55):
            kb.process_multi_hands([hand])
        assert len(triggered_keys) == 1

        # Hold stationary for another 2 seconds
        for offset in [0.70, 0.90, 1.20, 1.50, 2.00, 2.50]:
            with patch("time.time", return_value=base_time + offset):
                kb.process_multi_hands([hand])

        # Must still be strictly 1 keypress!
        assert len(triggered_keys) == 1
        assert kb.dwell_locked_key_id is not None

    def test_key_exit_unlocks_re_arm(self, qapp):
        """Moving to a different key unlocks re-arm and allows typing the new key."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        # Key 1 at index_x=0.55, index_y=0.50
        hand1 = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        base_time = 1000.0

        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand1])
        with patch("time.time", return_value=base_time + 0.55):
            kb.process_multi_hands([hand1])
        assert len(triggered_keys) == 1
        key1 = triggered_keys[0]

        # Move to Key 2 at index_x=0.70, index_y=0.50
        hand2 = make_hand(wrist_x=0.75, wrist_y=0.7, index_x=0.70, index_y=0.50, thumb_x=0.85, thumb_y=0.60, handedness="Right")

        # Arrival at new key clears old lock and begins new dwell
        with patch("time.time", return_value=base_time + 0.80):
            kb.process_multi_hands([hand2])
        assert kb.dwell_locked_key_id is None
        assert kb.last_hovered_key_id != key1
        key2 = kb.last_hovered_key_id

        # Finish dwell on Key 2
        with patch("time.time", return_value=base_time + 1.40):
            kb.process_multi_hands([hand2])

        assert len(triggered_keys) == 2
        assert triggered_keys[1] == key2
        assert key1 != key2

    def test_early_move_away_cancels_dwell(self, qapp):
        """Moving away before 0.5s elapses cancels dwell with zero keystrokes."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        hand1 = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        base_time = 1000.0

        # Start dwell
        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand1])
        # Progress at 0.30s (~60%)
        with patch("time.time", return_value=base_time + 0.30):
            kb.process_multi_hands([hand1])
        assert kb.dwell_progress > 0.0

        # Move completely away (top corner off keyboard)
        hand_away = make_hand(wrist_x=0.1, wrist_y=0.1, index_x=0.05, index_y=0.05, thumb_x=0.15, thumb_y=0.10, handedness="Right")
        with patch("time.time", return_value=base_time + 0.35):
            kb.process_multi_hands([hand_away])

        assert len(triggered_keys) == 0
        assert kb.dwell_progress == 0.0
        assert kb.dwell_locked_key_id is None

    def test_hand_loss_cancels_dwell(self, qapp):
        """Losing hand tracking cancels dwell timer immediately with zero characters."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        hand = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        base_time = 1000.0

        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand])
        with patch("time.time", return_value=base_time + 0.40):
            kb.process_multi_hands([hand])
        assert kb.dwell_progress > 0.50

        # Hand lost: empty hand list
        with patch("time.time", return_value=base_time + 0.45):
            kb.process_multi_hands([])

        assert len(triggered_keys) == 0
        assert kb.dwell_progress == 0.0
        assert kb.dwell_locked_key_id is None

    def test_natural_tremor_jitter_tolerance(self, qapp):
        """Micro hand jitter (< 25px) does not reset the dwell timer."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        base_time = 1000.0

        # Frame 1: index at 0.550, 0.500
        hand1 = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.550, index_y=0.500, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand1])

        # Frame 2: index micro-tremor (+0.005 in normalized space ~ 3-5px on canvas)
        hand2 = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.554, index_y=0.503, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        with patch("time.time", return_value=base_time + 0.25):
            kb.process_multi_hands([hand2])

        # Timer should NOT have reset: progress should be ~ 0.50
        assert 0.45 <= kb.dwell_progress <= 0.55

        # Frame 3: another micro-tremor at t=0.55s
        hand3 = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.548, index_y=0.498, thumb_x=0.70, thumb_y=0.60, handedness="Right")
        with patch("time.time", return_value=base_time + 0.55):
            kb.process_multi_hands([hand3])

        # Key triggered despite tremor!
        assert len(triggered_keys) == 1

    def test_mode_switch_to_pinch(self, qapp):
        """Switching to PINCH mode requires thumb-index pinch and ignores plain hover."""
        kb = HolographicKeyboardWidget()
        kb.resize(1000, 600)
        kb._recalculate_key_geometry()
        kb.test_mode = True

        # Switch to PINCH mode
        kb.set_typing_mode("PINCH")
        assert kb.press_detection_mode == "PINCH"

        triggered_keys = []
        kb.key_triggered.connect(lambda k: triggered_keys.append(k))

        # Hand with separated thumb and index (no pinch)
        hand_no_pinch = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.75, thumb_y=0.60, handedness="Right")
        base_time = 1000.0

        # Hover for 1.0 second: must NOT trigger in PINCH mode
        with patch("time.time", return_value=base_time):
            kb.process_multi_hands([hand_no_pinch])
        with patch("time.time", return_value=base_time + 1.0):
            kb.process_multi_hands([hand_no_pinch])
        assert len(triggered_keys) == 0

        # Now perform a pinch: thumb at same location as index tip
        hand_pinch = make_hand(wrist_x=0.6, wrist_y=0.7, index_x=0.55, index_y=0.50, thumb_x=0.55, thumb_y=0.50, handedness="Right")
        with patch("time.time", return_value=base_time + 1.1):
            kb.process_multi_hands([hand_pinch])

        # Pinch triggers!
        assert len(triggered_keys) == 1

    def test_settings_dialog_air_keyboard_controls(self, qapp, tmp_path):
        """Verifies SettingsDialog loads, renders, and persists air keyboard settings."""
        conf_file = str(tmp_path / "config.json")
        sm = SettingsManager(conf_file)

        # Defaults
        assert sm.get("air_typing", "typing_mode") == "DWELL"
        assert sm.get("air_typing", "dwell_duration") == 0.50

        dlg = SettingsDialog(sm)
        # Modify settings via dialog controls
        dlg.combo_typing_mode.setCurrentIndex(1)  # PINCH
        dlg.slider_dwell.setValue(75)             # 0.75s
        dlg.slider_jitter.setValue(35)            # 35.0px
        dlg.slider_kb_cd.setValue(25)             # 0.25s

        dlg._save_settings()

        # Reload settings
        sm2 = SettingsManager(conf_file)
        assert sm2.get("air_typing", "typing_mode") == "PINCH"
        assert sm2.get("air_typing", "dwell_duration") == 0.75
        assert sm2.get("air_typing", "dwell_jitter_tolerance") == 35.0
        assert sm2.get("air_typing", "keypress_cooldown") == 0.25
