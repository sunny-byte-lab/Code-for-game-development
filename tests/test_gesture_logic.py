"""Unit tests for hand tracking calculations, finger states, pinch detection, and debouncing."""

import time
import pytest
from app.hand_tracker import (
    HandLandmarkData, WRIST, THUMB_TIP, INDEX_TIP, INDEX_PIP, MIDDLE_TIP,
    MIDDLE_PIP, RING_TIP, RING_PIP, PINKY_TIP, PINKY_PIP, PINKY_MCP, THUMB_IP
)
from app.gesture_recognizer import GestureRecognizer, GestureType


def create_mock_hand(fingers_extended_map=None, pinch_distance=None, middle_pinch_distance=None):
    """Generates synthetic 21-landmark normalized data for deterministic unit testing."""
    if fingers_extended_map is None:
        fingers_extended_map = {"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}

    # Base wrist at center bottom
    wrist_x, wrist_y = 0.5, 0.8
    landmarks_norm = [(wrist_x, wrist_y, 0.0)] * 21
    landmarks_pixel = [(int(wrist_x * 640), int(wrist_y * 480))] * 21

    # Finger indices: (mcp, pip, dip, tip)
    finger_indices = {
        "thumb": (1, 2, 3, 4),
        "index": (5, 6, 7, 8),
        "middle": (9, 10, 11, 12),
        "ring": (13, 14, 15, 16),
        "pinky": (17, 18, 19, 20)
    }

    # Position fingers
    for f_name, (mcp, pip, dip, tip) in finger_indices.items():
        is_ext = fingers_extended_map.get(f_name, False)
        if f_name == "thumb":
            landmarks_norm[mcp] = (0.35, 0.7, 0.0)
            landmarks_norm[pip] = (0.32, 0.65, 0.0)
            landmarks_norm[dip] = (0.30, 0.60, 0.0)
            if is_ext:
                landmarks_norm[tip] = (0.12, 0.50, 0.0)  # Extended out to the left
            else:
                landmarks_norm[tip] = (0.35, 0.60, 0.0)  # Tucked in
        else:
            base_x = 0.4 + (mcp - 5) * 0.025
            landmarks_norm[mcp] = (base_x, 0.55, 0.0)
            landmarks_norm[pip] = (base_x, 0.45, 0.0)
            landmarks_norm[dip] = (base_x, 0.38, 0.0)
            if is_ext:
                landmarks_norm[tip] = (base_x, 0.25, 0.0)  # Tip far from wrist (extended)
            else:
                landmarks_norm[tip] = (base_x, 0.52, 0.0)  # Tip curled close to wrist

    # Explicit pinky MCP
    landmarks_norm[17] = (0.55, 0.55, 0.0)

    # If pinch distance explicitly specified, position thumb tip relative to index tip
    if pinch_distance is not None:
        idx_tip = landmarks_norm[8]
        landmarks_norm[4] = (idx_tip[0] + pinch_distance, idx_tip[1], 0.0)

    if middle_pinch_distance is not None:
        mid_tip = landmarks_norm[12]
        landmarks_norm[4] = (mid_tip[0] + middle_pinch_distance, mid_tip[1], 0.0)

    for i in range(21):
        landmarks_pixel[i] = (int(landmarks_norm[i][0] * 640), int(landmarks_norm[i][1] * 480))

    return HandLandmarkData(
        landmarks_norm=landmarks_norm,
        landmarks_pixel=landmarks_pixel,
        handedness="Right",
        frame_width=640,
        frame_height=480
    )


class TestGestureLogic:
    def test_finger_extension_calculation(self):
        # Index extended, others curled
        hand = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False})
        assert hand.fingers_extended["index"] is True
        assert hand.fingers_extended["middle"] is False
        assert hand.fingers_extended["ring"] is False
        assert hand.fingers_extended["pinky"] is False
        assert hand.extended_count >= 1

    def test_all_extended_palm(self):
        hand = create_mock_hand({"thumb": True, "index": True, "middle": True, "ring": True, "pinky": True})
        assert hand.extended_count == 5

    def test_fist_all_curled(self):
        hand = create_mock_hand({"thumb": False, "index": False, "middle": False, "ring": False, "pinky": False})
        assert hand.extended_count == 0

    def test_cursor_move_recognition(self):
        recognizer = GestureRecognizer()
        hand = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.20)
        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.INDEX_POINT
        assert state.cursor_coords is not None

    def test_pinch_left_click(self):
        recognizer = GestureRecognizer(pinch_threshold=0.06, click_cooldown=0.1)
        hand = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.03)
        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.PINCH_LEFT_CLICK
        assert state.pinch_active is True

    def test_pinch_hysteresis_and_drag(self):
        recognizer = GestureRecognizer(pinch_threshold=0.06, pinch_release_threshold=0.09, drag_hold_duration=0.05)
        # Enter pinch
        hand_pinched = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.04)
        state1 = recognizer.recognize(hand_pinched)
        assert state1.pinch_active is True

        # Stay at distance 0.07 (above threshold 0.06, but below release 0.09) -> Still pinched!
        hand_mid = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.07)
        state2 = recognizer.recognize(hand_mid)
        assert state2.pinch_active is True

        # Wait past drag hold duration -> transitions to drag
        time.sleep(0.06)
        state3 = recognizer.recognize(hand_mid)
        assert state3.gesture == GestureType.PINCH_DRAG
        assert state3.is_dragging is True

        # Release beyond 0.09
        hand_released = create_mock_hand({"thumb": False, "index": True, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.12)
        state4 = recognizer.recognize(hand_released)
        assert state4.pinch_active is False
        assert state4.is_dragging is False

    def test_two_finger_scroll(self):
        recognizer = GestureRecognizer()
        # Index + Middle extended, others curled
        hand1 = create_mock_hand({"thumb": False, "index": True, "middle": True, "ring": False, "pinky": False}, pinch_distance=0.20)
        state1 = recognizer.recognize(hand1)
        assert state1.gesture == GestureType.TWO_FINGER_SCROLL
        assert state1.scroll_dy == 0.0

        # Move hand downward (mid_y increases)
        hand2 = create_mock_hand({"thumb": False, "index": True, "middle": True, "ring": False, "pinky": False}, pinch_distance=0.20)
        # Shift index and middle tips slightly
        hand2.landmarks_norm[8] = (hand2.landmarks_norm[8][0], hand2.landmarks_norm[8][1] + 0.05, 0.0)
        hand2.landmarks_norm[12] = (hand2.landmarks_norm[12][0], hand2.landmarks_norm[12][1] + 0.05, 0.0)
        state2 = recognizer.recognize(hand2)
        assert state2.gesture == GestureType.TWO_FINGER_SCROLL
        assert state2.scroll_dy > 0.0

    def test_emergency_fist_hold(self):
        # Default recognizer has automatic fist emergency lock disabled (resting hand)
        recognizer = GestureRecognizer(fist_hold_duration=0.05)
        fist_hand = create_mock_hand({"thumb": False, "index": False, "middle": False, "ring": False, "pinky": False}, pinch_distance=0.01)

        # Initial detection
        state1 = recognizer.recognize(fist_hand)
        assert state1.gesture != GestureType.FIST_EMERGENCY
        assert "CLOSED FIST" in state1.description or "RESTING" in state1.description

        # Wait past hold duration -- must remain safe resting hand and NOT lock into FIST_EMERGENCY
        time.sleep(0.06)
        state2 = recognizer.recognize(fist_hand)
        assert state2.gesture != GestureType.FIST_EMERGENCY
        assert state2.gesture == GestureType.NONE
        assert "RESTING" in state2.description or "CLOSED FIST" in state2.description

        # If explicitly opted-in via configuration, it can still trigger when enabled
        recognizer_optin = GestureRecognizer(fist_hold_duration=0.05)
        recognizer_optin.enabled_gestures["fist_emergency_stop"] = True
        _ = recognizer_optin.recognize(fist_hand)
        time.sleep(0.06)
        state_optin = recognizer_optin.recognize(fist_hand)
        assert state_optin.gesture == GestureType.FIST_EMERGENCY
