"""Unit tests for scale-invariant pinch detection, ergonomic tracking landmarks,
and gesture click suppression during scrolling.
"""

import pytest
from app.hand_tracker import (
    HandLandmarkData, WRIST, THUMB_TIP, INDEX_TIP, INDEX_MCP, INDEX_PIP, MIDDLE_MCP, MIDDLE_TIP
)
from app.gesture_recognizer import GestureRecognizer, GestureType
from tests.test_gesture_logic import create_mock_hand


class TestScaleInvariantPinch:
    def test_hand_scale_calculation(self):
        """Verifies that palm scale (wrist to middle MCP) is calculated and strictly positive."""
        hand = create_mock_hand()
        assert hand.hand_scale > 0.05
        assert hand.norm_pinch_distance > 0.0

    def test_distance_invariance(self):
        """When a hand is farther away, raw Euclidean coordinates shrink proportionally,
        but normalized pinch distance should remain virtually identical."""
        # Near hand (large scale)
        hand_near = create_mock_hand(pinch_distance=0.08)
        # Far hand (same hand, but 2x smaller across all coordinates)
        far_norm = [(p[0] * 0.5, p[1] * 0.5, p[2] * 0.5) for p in hand_near.landmarks_norm]
        far_pix = [(int(p[0] * 640), int(p[1] * 480)) for p in far_norm]
        hand_far = HandLandmarkData(far_norm, far_pix, "Right", 640, 480)

        # Raw distance is halved
        assert abs(hand_far.pinch_distance - hand_near.pinch_distance * 0.5) < 0.01

        # But scale-normalized pinch distance is consistent!
        diff_ratio = abs(hand_far.norm_pinch_distance - hand_near.norm_pinch_distance) / hand_near.norm_pinch_distance
        assert diff_ratio < 0.05, f"Expected normalized distance to match within 5%, diff ratio={diff_ratio}"

    def test_ergonomic_tracking_landmarks(self):
        """Verifies that multiple ergonomic tracking landmarks can be retrieved correctly."""
        hand = create_mock_hand()

        idx_tip = hand.get_tracking_point("index_tip")
        idx_mcp = hand.get_tracking_point("index_mcp")
        idx_pip = hand.get_tracking_point("index_pip")
        center = hand.get_tracking_point("hand_center")
        mid_ti = hand.get_tracking_point("thumb_index_mid")

        assert idx_tip == (hand.landmarks_norm[INDEX_TIP][0], hand.landmarks_norm[INDEX_TIP][1])
        assert idx_mcp == (hand.landmarks_norm[INDEX_MCP][0], hand.landmarks_norm[INDEX_MCP][1])
        assert idx_pip == (hand.landmarks_norm[INDEX_PIP][0], hand.landmarks_norm[INDEX_PIP][1])

        # Center should be midpoint between wrist and middle MCP
        w = hand.landmarks_norm[WRIST]
        m = hand.landmarks_norm[MIDDLE_MCP]
        expected_center = ((w[0] + m[0]) / 2.0, (w[1] + m[1]) / 2.0)
        assert abs(center[0] - expected_center[0]) < 1e-4
        assert abs(center[1] - expected_center[1]) < 1e-4

    def test_scroll_mode_click_suppression(self):
        """When user is in two-finger scrolling mode, pinch clicks must be strictly suppressed."""
        recognizer = GestureRecognizer(pinch_threshold=0.35)
        # Create hand with both Index and Middle extended (scrolling posture)
        hand = create_mock_hand({"thumb": False, "index": True, "middle": True, "ring": False, "pinky": False}, pinch_distance=0.02)

        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.TWO_FINGER_SCROLL
        assert state.gesture != GestureType.PINCH_LEFT_CLICK
        assert state.is_dragging is False
