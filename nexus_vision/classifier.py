"""N.E.X.U.S. Pure Gesture Classification Engine.
Classifies hand poses using geometric landmark metrics independently of platform or UI.
"""

from enum import Enum
from typing import List, Tuple, Dict, Any, Optional
from nexus_vision.geometry import (
    calculate_joint_angle_cos,
    is_finger_extended_joints,
    calculate_scale_invariant_pinch
)


class GestureType(Enum):
    NONE = "NONE"
    POINT = "POINT"
    PINCH = "PINCH"
    TWO_FINGER = "TWO_FINGER"
    OPEN_PALM = "OPEN_PALM"
    FIST = "FIST"


class MathGestureClassifier:
    """Classifies gestures purely from normalized 21-landmark arrays."""

    def __init__(self,
                 pinch_threshold: float = 0.28,
                 pinch_release_threshold: float = 0.40):
        self.pinch_threshold = pinch_threshold
        self.pinch_release_threshold = pinch_release_threshold

    def classify_landmarks(self, landmarks_norm: List[Tuple[float, float, float]]) -> Dict[str, Any]:
        """Analyzes a 21-element landmark list and returns classification dictionary."""
        if len(landmarks_norm) < 21:
            return {
                "gesture": GestureType.NONE,
                "pinch_distance": 1.0,
                "extended_fingers": {},
                "confidence": 0.0
            }

        wrist = (landmarks_norm[0][0], landmarks_norm[0][1])
        middle_mcp = (landmarks_norm[9][0], landmarks_norm[9][1])

        # Thumb (4), Index (8), Middle (12), Ring (16), Pinky (20)
        idx_ext, idx_score = is_finger_extended_joints(
            wrist, (landmarks_norm[5][0], landmarks_norm[5][1]),
            (landmarks_norm[6][0], landmarks_norm[6][1]),
            (landmarks_norm[8][0], landmarks_norm[8][1])
        )
        mid_ext, mid_score = is_finger_extended_joints(
            wrist, (landmarks_norm[9][0], landmarks_norm[9][1]),
            (landmarks_norm[10][0], landmarks_norm[10][1]),
            (landmarks_norm[12][0], landmarks_norm[12][1])
        )
        ring_ext, ring_score = is_finger_extended_joints(
            wrist, (landmarks_norm[13][0], landmarks_norm[13][1]),
            (landmarks_norm[14][0], landmarks_norm[14][1]),
            (landmarks_norm[16][0], landmarks_norm[16][1])
        )
        pinky_ext, pinky_score = is_finger_extended_joints(
            wrist, (landmarks_norm[17][0], landmarks_norm[17][1]),
            (landmarks_norm[18][0], landmarks_norm[18][1]),
            (landmarks_norm[20][0], landmarks_norm[20][1])
        )

        pinch_dist = calculate_scale_invariant_pinch(
            (landmarks_norm[4][0], landmarks_norm[4][1]),
            (landmarks_norm[8][0], landmarks_norm[8][1]),
            wrist, middle_mcp
        )

        ext_map = {
            "index": idx_ext,
            "middle": mid_ext,
            "ring": ring_ext,
            "pinky": pinky_ext
        }

        # Classification decision tree
        ext_count = sum(1 for e in ext_map.values() if e)

        if pinch_dist <= self.pinch_threshold:
            gesture = GestureType.PINCH
        elif ext_count >= 3:
            gesture = GestureType.OPEN_PALM
        elif ext_count == 0:
            gesture = GestureType.FIST
        elif idx_ext and mid_ext and not ring_ext and not pinky_ext:
            gesture = GestureType.TWO_FINGER
        elif idx_ext and not mid_ext and not ring_ext and not pinky_ext:
            gesture = GestureType.POINT
        else:
            gesture = GestureType.NONE

        return {
            "gesture": gesture,
            "pinch_distance": pinch_dist,
            "extended_fingers": ext_map,
            "scores": {
                "index": idx_score,
                "middle": mid_score,
                "ring": ring_score,
                "pinky": pinky_score
            }
        }
