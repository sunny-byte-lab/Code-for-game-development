"""Unit tests for nexus_vision pure geometry, filters, and gesture classification."""

import pytest
from nexus_vision import (
    calculate_joint_angle_cos,
    is_finger_extended_joints,
    calculate_scale_invariant_pinch,
    map_coords_to_roi,
    OneEuroFilter,
    PointFilter2D,
    MathGestureClassifier,
    GestureType
)


def test_joint_angle_cos_calculations():
    # Collinear straight finger
    cos_straight = calculate_joint_angle_cos((0.5, 0.7), (0.5, 0.5), (0.5, 0.3))
    assert pytest.approx(cos_straight, 0.01) == 1.0

    # Right angle bend (folded)
    cos_bent = calculate_joint_angle_cos((0.5, 0.7), (0.5, 0.5), (0.7, 0.5))
    assert pytest.approx(cos_bent, 0.01) == 0.0


def test_finger_extension_geometry():
    wrist = (0.5, 0.8)
    mcp = (0.5, 0.6)
    pip = (0.5, 0.45)
    tip_straight = (0.5, 0.3)
    tip_curled = (0.5, 0.55)

    ext_straight, s1 = is_finger_extended_joints(wrist, mcp, pip, tip_straight)
    assert ext_straight is True
    assert s1 > 0.60

    ext_curled, s2 = is_finger_extended_joints(wrist, mcp, pip, tip_curled)
    assert ext_curled is False


def test_scale_invariant_pinch_distance():
    wrist = (0.5, 0.8)
    middle_mcp = (0.5, 0.6)  # palm scale = 0.20
    index_tip = (0.5, 0.3)
    thumb_tip_touching = (0.51, 0.3)  # distance = 0.01 -> norm = 0.01 / 0.20 = 0.05
    thumb_tip_open = (0.35, 0.3)      # distance = 0.15 -> norm = 0.15 / 0.20 = 0.75

    norm_pinch = calculate_scale_invariant_pinch(thumb_tip_touching, index_tip, wrist, middle_mcp)
    assert norm_pinch < 0.10

    norm_open = calculate_scale_invariant_pinch(thumb_tip_open, index_tip, wrist, middle_mcp)
    assert norm_open > 0.60


def test_one_euro_filter():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.02)
    # Steady signal smoothing
    v1 = f.filter(10.0, timestamp=100.0)
    assert v1 == 10.0

    v2 = f.filter(10.5, timestamp=100.033)
    assert 10.0 < v2 < 10.5


def test_math_gesture_classifier():
    clf = MathGestureClassifier(pinch_threshold=0.28)

    # Mock 21-landmark array
    lms = [(0.5, 0.5, 0.0)] * 21
    res = clf.classify_landmarks(lms)
    assert "gesture" in res
    assert isinstance(res["gesture"], GestureType)
