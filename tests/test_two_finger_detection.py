"""Unit and integration tests for Robust Two-Finger Gesture Detection & Debug Telemetry.
Validates rotation-invariance, scale-invariance, left/right hand support,
anatomical tendon coupling tolerance, gesture separation, and temporal stability debouncing.
"""

import math
import time
import pytest

from app.hand_tracker import (
    HandLandmarkData, WRIST, THUMB_TIP, THUMB_IP, THUMB_MCP, THUMB_CMC,
    INDEX_TIP, INDEX_DIP, INDEX_PIP, INDEX_MCP,
    MIDDLE_TIP, MIDDLE_DIP, MIDDLE_PIP, MIDDLE_MCP,
    RING_TIP, RING_DIP, RING_PIP, RING_MCP,
    PINKY_TIP, PINKY_DIP, PINKY_PIP, PINKY_MCP
)
from app.gesture_recognizer import GestureRecognizer, GestureType, GestureState


def create_oriented_hand(
    index_ext: bool = True,
    middle_ext: bool = True,
    ring_ext: bool = False,
    pinky_ext: bool = False,
    thumb_ext: bool = False,
    rotation_deg: float = 0.0,
    hand_scale: float = 0.15,
    handedness: str = "Right",
    confidence: float = 0.95
) -> HandLandmarkData:
    """
    Creates a synthetic 21-landmark hand with exact joint geometry rotated at rotation_deg.
    Rotation is in degrees (0 = upright, 90 = pointing right, 180 = pointing down, 270 = pointing left).
    """
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    def rot(dx: float, dy: float) -> tuple:
        rx = dx * cos_r - dy * sin_r
        ry = dx * sin_r + dy * cos_r
        return rx, ry

    # Center palm at (0.5, 0.5)
    cx, cy = 0.5, 0.5
    wrist_dx, wrist_dy = rot(0.0, hand_scale)
    wrist = (cx + wrist_dx, cy + wrist_dy, 0.0)

    landmarks = [(wrist[0], wrist[1], 0.0)] * 21

    # Finger definitions: base lateral offsets across knuckle arc
    # Lateral order: thumb, index, middle, ring, pinky
    lat_sign = 1.0 if handedness == "Right" else -1.0
    finger_bases = {
        "thumb": (-0.35 * lat_sign, 0.40),
        "index": (-0.20 * lat_sign, 0.0),
        "middle": (0.0, -0.05),
        "ring": (0.18 * lat_sign, 0.0),
        "pinky": (0.35 * lat_sign, 0.15)
    }

    # Joint index maps
    joint_indices = {
        "thumb": (THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP),
        "index": (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
        "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
        "ring": (RING_MCP, RING_PIP, RING_DIP, RING_TIP),
        "pinky": (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP)
    }

    ext_map = {
        "thumb": thumb_ext,
        "index": index_ext,
        "middle": middle_ext,
        "ring": ring_ext,
        "pinky": pinky_ext
    }

    for fname, (mcp_i, pip_i, dip_i, tip_i) in joint_indices.items():
        bx, by = finger_bases[fname]
        mcp_dx, mcp_dy = rot(bx * hand_scale, by * hand_scale)
        p_mcp = (cx + mcp_dx, cy + mcp_dy, 0.0)
        landmarks[mcp_i] = p_mcp

        is_ext = ext_map[fname]
        if fname == "thumb":
            # Thumb extends laterally; folds inward toward index MCP
            tip_dist = 0.85 * hand_scale if is_ext else 0.35 * hand_scale
            ip_dx, ip_dy = rot((bx - 0.20 * lat_sign) * hand_scale, (by - 0.25) * hand_scale)
            landmarks[pip_i] = (cx + ip_dx, cy + ip_dy, 0.0)
            dip_dx, dip_dy = rot((bx - 0.35 * lat_sign) * hand_scale, (by - 0.45) * hand_scale)
            landmarks[dip_i] = (cx + dip_dx, cy + dip_dy, 0.0)

            tip_lat = (bx - (0.65 if is_ext else 0.10) * lat_sign) * hand_scale
            tip_fwd = (by - (0.60 if is_ext else 0.20)) * hand_scale
            t_dx, t_dy = rot(tip_lat, tip_fwd)
            landmarks[tip_i] = (cx + t_dx, cy + t_dy, 0.0)
        else:
            # Main fingers extend forward along rotation vector; curl back towards MCP when folded
            fwd_len = 1.0 * hand_scale if is_ext else 0.25 * hand_scale
            # PIP is roughly 0.35 * scale along finger vector
            pip_dx, pip_dy = rot(bx * hand_scale, (by - 0.35) * hand_scale)
            landmarks[pip_i] = (cx + pip_dx, cy + pip_dy, 0.0)
            # DIP is roughly 0.65 * scale
            dip_dx, dip_dy = rot(bx * hand_scale, (by - 0.65) * hand_scale)
            landmarks[dip_i] = (cx + dip_dx, cy + dip_dy, 0.0)
            # TIP is far (by - 1.05) if extended, or curled into palm (by - 0.10) if folded
            tip_fwd = (by - 1.05) if is_ext else (by - 0.08)
            tip_dx, tip_dy = rot(bx * hand_scale, tip_fwd * hand_scale)
            landmarks[tip_i] = (cx + tip_dx, cy + tip_dy, 0.0)

    # Frame dimensions
    w, h = 640, 480
    pixels = [(int(p[0] * w), int(p[1] * h)) for p in landmarks]

    return HandLandmarkData(
        landmarks_norm=landmarks,
        landmarks_pixel=pixels,
        handedness=handedness,
        frame_width=w,
        frame_height=h,
        confidence=confidence
    )


class TestTwoFingerDetection:
    """Comprehensive test suite for Two-Finger detection accuracy and robustness."""

    def test_upright_two_finger_scroll(self):
        """Index + Middle extended, Ring + Pinky folded upright (0 deg)."""
        hand = create_oriented_hand(index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False, rotation_deg=0.0)
        assert hand.index_state == "EXTENDED"
        assert hand.middle_state == "EXTENDED"
        assert hand.ring_state == "FOLDED"
        assert hand.pinky_state == "FOLDED"

        recognizer = GestureRecognizer()
        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.TWO_FINGER_SCROLL
        assert state.two_finger_stability_status in ("EVALUATING", "STABLE")

    def test_rotated_hands_45_90_180_degrees(self):
        """Validates that two-finger recognition is strictly rotation-invariant."""
        recognizer = GestureRecognizer()
        for deg in [45.0, 90.0, 135.0, 180.0, 270.0, 315.0]:
            recognizer.reset()
            hand = create_oriented_hand(
                index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False, rotation_deg=deg
            )
            assert hand.index_state == "EXTENDED", f"Index failed at {deg}°"
            assert hand.middle_state == "EXTENDED", f"Middle failed at {deg}°"
            assert hand.ring_state == "FOLDED", f"Ring should be folded at {deg}°"
            assert hand.pinky_state == "FOLDED", f"Pinky should be folded at {deg}°"

            state = recognizer.recognize(hand)
            assert state.gesture == GestureType.TWO_FINGER_SCROLL, f"Two-finger scroll failed at {deg}°"

    def test_left_and_right_hands(self):
        """Validates that both physical Left and Right hands are supported symmetrically."""
        recognizer = GestureRecognizer()
        for handedness in ["Right", "Left"]:
            hand = create_oriented_hand(
                index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False,
                handedness=handedness
            )
            assert hand.index_state == "EXTENDED"
            assert hand.middle_state == "EXTENDED"
            assert hand.ring_state == "FOLDED"
            assert hand.pinky_state == "FOLDED"

            state = recognizer.recognize(hand)
            assert state.gesture == GestureType.TWO_FINGER_SCROLL
            assert state.hand_label == handedness

    def test_anatomical_tendon_coupling_tolerance(self):
        """
        When middle finger extends, human ring finger tendon naturally lifts slightly.
        If ring reach is < 82% of middle finger reach, it must still recognize two-finger gesture!
        """
        hand = create_oriented_hand(index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False)
        # Position ring fingertip so it is slightly lifted (70% reach of middle finger)
        m_mcp = hand.landmarks_norm[MIDDLE_MCP]
        m_tip = hand.landmarks_norm[MIDDLE_TIP]
        mid_reach = math.hypot(m_tip[0] - m_mcp[0], m_tip[1] - m_mcp[1])

        r_mcp = hand.landmarks_norm[RING_MCP]
        # Set ring tip at 70% of middle reach
        hand.landmarks_norm[RING_TIP] = (r_mcp[0], r_mcp[1] - (mid_reach * 0.70), 0.0)

        recognizer = GestureRecognizer()
        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.TWO_FINGER_SCROLL

    def test_gesture_separation_one_finger_point(self):
        """1 finger extended (Index only) must recognize INDEX_POINT and never trigger two-finger scroll."""
        recognizer = GestureRecognizer()
        hand = create_oriented_hand(index_ext=True, middle_ext=False, ring_ext=False, pinky_ext=False)
        assert hand.index_state == "EXTENDED"
        assert hand.middle_state == "FOLDED"

        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.INDEX_POINT
        assert state.two_finger_stability_status == "OFF"

    def test_gesture_separation_closed_fist(self):
        """All fingers folded must not trigger two-finger scroll."""
        recognizer = GestureRecognizer(fist_hold_duration=1.0)
        hand = create_oriented_hand(index_ext=False, middle_ext=False, ring_ext=False, pinky_ext=False, thumb_ext=False)
        assert hand.extended_count == 0

        state = recognizer.recognize(hand)
        assert state.gesture != GestureType.TWO_FINGER_SCROLL
        assert state.two_finger_stability_status == "OFF"

    def test_gesture_separation_open_palm(self):
        """All 5 fingers extended must not trigger two-finger scroll."""
        recognizer = GestureRecognizer()
        hand = create_oriented_hand(index_ext=True, middle_ext=True, ring_ext=True, pinky_ext=True, thumb_ext=True)
        assert hand.extended_count == 5

        state = recognizer.recognize(hand)
        assert state.gesture == GestureType.NONE
        assert "OPEN PALM" in state.description
        assert state.two_finger_stability_status == "OFF"

    def test_invalid_finger_combinations(self):
        """Invalid combinations (Index+Pinky, Middle+Ring) must not trigger two-finger scroll."""
        recognizer = GestureRecognizer()
        # Index + Pinky extended, Middle folded
        hand_rock = create_oriented_hand(index_ext=True, middle_ext=False, ring_ext=False, pinky_ext=True)
        state1 = recognizer.recognize(hand_rock)
        assert state1.gesture != GestureType.TWO_FINGER_SCROLL

        # Middle + Ring extended, Index folded
        hand_mid_ring = create_oriented_hand(index_ext=False, middle_ext=True, ring_ext=True, pinky_ext=False)
        state2 = recognizer.recognize(hand_mid_ring)
        assert state2.gesture != GestureType.TWO_FINGER_SCROLL

    def test_temporal_smoothing_and_stability(self):
        """
        Frame 1: Enters gesture with status EVALUATING.
        Frame 2+: Confirms gesture with status STABLE.
        1-frame dropout: Tolerates single-frame glitch without resetting active status.
        Release: Fully resets to OFF.
        """
        recognizer = GestureRecognizer()
        hand_2fg = create_oriented_hand(index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False)
        hand_fist = create_oriented_hand(index_ext=False, middle_ext=False, ring_ext=False, pinky_ext=False)

        # Frame 1: First appearance
        state1 = recognizer.recognize(hand_2fg)
        assert state1.gesture == GestureType.TWO_FINGER_SCROLL
        assert state1.two_finger_stability_status == "EVALUATING"
        assert state1.is_two_finger_stable is False

        # Frame 2: Consecutive appearance -> STABLE
        state2 = recognizer.recognize(hand_2fg)
        assert state2.gesture == GestureType.TWO_FINGER_SCROLL
        assert state2.two_finger_stability_status == "STABLE"
        assert state2.is_two_finger_stable is True

        # Frame 3: Single-frame glitch (transient dropout) -> tolerated by 1-frame grace
        hand_glitch = create_oriented_hand(index_ext=True, middle_ext=False, ring_ext=False, pinky_ext=False)
        state3 = recognizer.recognize(hand_glitch)
        assert state3.gesture == GestureType.TWO_FINGER_SCROLL
        assert state3.two_finger_stability_status == "STABLE"

        # Frame 4: Second consecutive non-match frame -> drops gesture to OFF
        state4 = recognizer.recognize(hand_fist)
        assert state4.gesture != GestureType.TWO_FINGER_SCROLL
        assert state4.two_finger_stability_status == "OFF"

    def test_low_confidence_rejection(self):
        """Tracking confidence below 0.25 must immediately reject gesture."""
        recognizer = GestureRecognizer()
        hand_low_conf = create_oriented_hand(
            index_ext=True, middle_ext=True, ring_ext=False, pinky_ext=False, confidence=0.18
        )
        state = recognizer.recognize(hand_low_conf)
        assert state.gesture == GestureType.NONE
        assert "LOW TRACKING CONFIDENCE" in state.description
