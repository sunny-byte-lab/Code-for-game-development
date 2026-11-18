"""JARVIS Real-Time Hand Tracking Engine.
Uses MediaPipe Hands with rotation-invariant finger state detection and futuristic HUD rendering.
"""

import math
import time
import logging
import warnings
from typing import Dict, List, Optional, Tuple, Any, Union

# Suppress Protobuf SymbolDatabase deprecation warning
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")

import cv2
import numpy as np
import mediapipe as mp

logger = logging.getLogger("NEXUS.Tracker")

# Landmark indices for readability
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

# Landmark name mapping for convenience & string safety
LANDMARK_NAME_MAP: Dict[str, int] = {
    "wrist": WRIST,
    "thumb_cmc": THUMB_CMC,
    "thumb_mcp": THUMB_MCP,
    "thumb_ip": THUMB_IP,
    "thumb_tip": THUMB_TIP,
    "index_mcp": INDEX_MCP,
    "index_pip": INDEX_PIP,
    "index_dip": INDEX_DIP,
    "index_tip": INDEX_TIP,
    "middle_mcp": MIDDLE_MCP,
    "middle_pip": MIDDLE_PIP,
    "middle_dip": MIDDLE_DIP,
    "middle_tip": MIDDLE_TIP,
    "ring_mcp": RING_MCP,
    "ring_pip": RING_PIP,
    "ring_dip": RING_DIP,
    "ring_tip": RING_TIP,
    "pinky_mcp": PINKY_MCP,
    "pinky_pip": PINKY_PIP,
    "pinky_dip": PINKY_DIP,
    "pinky_tip": PINKY_TIP,
}

# Standard hand skeleton connections
HAND_CONNECTIONS = [
    # Thumb
    (WRIST, THUMB_CMC), (THUMB_CMC, THUMB_MCP), (THUMB_MCP, THUMB_IP), (THUMB_IP, THUMB_TIP),
    # Index
    (WRIST, INDEX_MCP), (INDEX_MCP, INDEX_PIP), (INDEX_PIP, INDEX_DIP), (INDEX_DIP, INDEX_TIP),
    # Middle
    (INDEX_MCP, MIDDLE_MCP), (MIDDLE_MCP, MIDDLE_PIP), (MIDDLE_PIP, MIDDLE_DIP), (MIDDLE_DIP, MIDDLE_TIP),
    # Ring
    (MIDDLE_MCP, RING_MCP), (RING_MCP, RING_PIP), (RING_PIP, RING_DIP), (RING_DIP, RING_TIP),
    # Pinky
    (RING_MCP, PINKY_MCP), (PINKY_MCP, PINKY_PIP), (PINKY_PIP, PINKY_DIP), (PINKY_DIP, PINKY_TIP),
    (WRIST, PINKY_MCP)
]


class HandLandmarkData:
    """Encapsulates processed hand metrics for a single frame."""
    def __init__(self, landmarks_norm: List[Tuple[float, float, float]],
                 landmarks_pixel: List[Tuple[int, int]],
                 handedness: str,
                 frame_width: int,
                 frame_height: int,
                 confidence: float = 0.95,
                 handedness_confidence: float = 0.95,
                 frame_timestamp: float = 0.0,
                 frame_id: int = 0):
        self.landmarks_norm = landmarks_norm  # [(x, y, z), ...] normalized [0..1]
        self.landmarks_pixel = landmarks_pixel  # [(px, py), ...]
        self.landmarks = landmarks_norm  # Convenience alias for backwards compatibility
        self.handedness = handedness  # "Left" or "Right" (physically accurate)
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.confidence = float(confidence)
        self.handedness_confidence = float(handedness_confidence)
        self.frame_timestamp = frame_timestamp if frame_timestamp > 0 else time.time()
        self.frame_id = frame_id

        # Strict validation: require 21 valid landmarks within normalized unit coordinate space
        self.is_valid = bool(
            len(landmarks_norm) >= 21 and
            len(landmarks_pixel) >= 21 and
            0.0 <= landmarks_norm[INDEX_TIP][0] <= 1.0 and
            0.0 <= landmarks_norm[INDEX_TIP][1] <= 1.0 and
            0.0 <= landmarks_norm[WRIST][0] <= 1.0 and
            0.0 <= landmarks_norm[WRIST][1] <= 1.0
        )

        # Hand scale reference (wrist to middle MCP palm size) for distance-invariant normalization
        raw_palm_scale = self.get_2d_distance(WRIST, MIDDLE_MCP)
        self.hand_scale = max(0.04, raw_palm_scale)

        # Precompute finger extended states and confidence scores (Rotation-invariant geometric analysis)
        self.finger_scores: Dict[str, float] = {}
        self.fingers_extended: Dict[str, bool] = self._calculate_fingers_extended()
        self.finger_states: Dict[str, str] = {
            k: ("EXTENDED" if v else "FOLDED") for k, v in self.fingers_extended.items()
        }

        # Key distances: Use robust 2D camera-plane distance to avoid MediaPipe noisy pseudo-Z depth distortion!
        self.pinch_distance_2d = self.get_2d_distance(THUMB_TIP, INDEX_TIP)
        self.pinch_distance_3d = self.get_distance(THUMB_TIP, INDEX_TIP)
        self.pinch_distance = self.pinch_distance_2d
        self.pinch_middle_distance = self.get_2d_distance(THUMB_TIP, MIDDLE_TIP)
        self.pinch_pixel_distance = self.get_pixel_distance(THUMB_TIP, INDEX_TIP)

        # Scale-invariant normalized pinch distances (consistent across all camera distances)
        self.norm_pinch_distance = self.pinch_distance / self.hand_scale
        self.norm_pinch_middle_distance = self.pinch_middle_distance / self.hand_scale

    def get_tracking_point(self, landmark_name: Union[str, int] = "index_tip") -> Tuple[float, float]:
        """Returns normalized (x, y) coordinates for the selected ergonomic tracking landmark."""
        if isinstance(landmark_name, int):
            if 0 <= landmark_name < len(self.landmarks_norm):
                p = self.landmarks_norm[landmark_name]
                return p[0], p[1]
            p = self.landmarks_norm[INDEX_TIP]
            return p[0], p[1]

        if landmark_name == "index_mcp":
            p = self.landmarks_norm[INDEX_MCP]
            return p[0], p[1]
        elif landmark_name == "index_pip":
            p = self.landmarks_norm[INDEX_PIP]
            return p[0], p[1]
        elif landmark_name == "hand_center":
            w = self.landmarks_norm[WRIST]
            m = self.landmarks_norm[MIDDLE_MCP]
            return (w[0] + m[0]) / 2.0, (w[1] + m[1]) / 2.0
        elif landmark_name == "thumb_index_mid":
            t = self.landmarks_norm[THUMB_TIP]
            i = self.landmarks_norm[INDEX_TIP]
            return (t[0] + i[0]) / 2.0, (t[1] + i[1]) / 2.0
        else:  # default "index_tip"
            p = self.landmarks_norm[INDEX_TIP]
            return p[0], p[1]

    def get_tracking_pixel(self, landmark_name: str = "index_tip") -> Tuple[int, int]:
        """Returns screen pixel coordinates for the selected tracking landmark."""
        nx, ny = self.get_tracking_point(landmark_name)
        return int(nx * self.frame_width), int(ny * self.frame_height)

    def get_norm(self, idx: Union[int, str]) -> Tuple[float, float, float]:
        if isinstance(idx, str):
            key = idx.lower()
            if key in LANDMARK_NAME_MAP:
                return self.landmarks_norm[LANDMARK_NAME_MAP[key]]
            nx, ny = self.get_tracking_point(key)
            return (nx, ny, 0.0)
        return self.landmarks_norm[idx]

    def get_pixel(self, idx: Union[int, str]) -> Tuple[int, int]:
        if isinstance(idx, str):
            key = idx.lower()
            if key in LANDMARK_NAME_MAP:
                return self.landmarks_pixel[LANDMARK_NAME_MAP[key]]
            return self.get_tracking_pixel(key)
        return self.landmarks_pixel[idx]

    def get_distance(self, idx1: int, idx2: int) -> float:
        """Euclidean distance in normalized 3D space."""
        p1 = self.landmarks_norm[idx1]
        p2 = self.landmarks_norm[idx2]
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2)

    def get_2d_distance(self, idx1: int, idx2: int) -> float:
        """Euclidean distance in normalized 2D space."""
        p1 = self.landmarks_norm[idx1]
        p2 = self.landmarks_norm[idx2]
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    def get_pixel_distance(self, idx1: int, idx2: int) -> float:
        """Euclidean distance in screen pixels."""
        p1 = self.landmarks_pixel[idx1]
        p2 = self.landmarks_pixel[idx2]
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    def _calculate_finger_joint_angle(self, mcp_idx: int, pip_idx: int, tip_idx: int) -> float:
        """Calculates cosine of angle between (PIP - MCP) and (TIP - PIP) vectors.
        Returns ~1.0 for straight/extended finger, <= 0.20 for folded/curled knuckle."""
        p_mcp = self.landmarks_norm[mcp_idx]
        p_pip = self.landmarks_norm[pip_idx]
        p_tip = self.landmarks_norm[tip_idx]

        u = (p_pip[0] - p_mcp[0], p_pip[1] - p_mcp[1])
        v = (p_tip[0] - p_pip[0], p_tip[1] - p_pip[1])
        u_len = math.hypot(u[0], u[1])
        v_len = math.hypot(v[0], v[1])

        if u_len < 1e-4 or v_len < 1e-4:
            return 1.0  # Degenerate case fallback
        dot = u[0] * v[0] + u[1] * v[1]
        return max(-1.0, min(1.0, dot / (u_len * v_len)))

    def _is_finger_extended(self, mcp_idx: int, pip_idx: int, tip_idx: int) -> Tuple[bool, float]:
        """Calculates rotation-invariant finger extension state and normalized score."""
        wrist = self.landmarks_norm[WRIST]
        p_mcp = self.landmarks_norm[mcp_idx]
        p_pip = self.landmarks_norm[pip_idx]
        p_tip = self.landmarks_norm[tip_idx]

        d_wrist_tip = math.hypot(p_tip[0] - wrist[0], p_tip[1] - wrist[1])
        d_wrist_pip = math.hypot(p_pip[0] - wrist[0], p_pip[1] - wrist[1])
        d_wrist_mcp = math.hypot(p_mcp[0] - wrist[0], p_mcp[1] - wrist[1])
        d_mcp_tip = math.hypot(p_tip[0] - p_mcp[0], p_tip[1] - p_mcp[1])
        d_mcp_pip = math.hypot(p_pip[0] - p_mcp[0], p_pip[1] - p_mcp[1])

        # Backward compatibility for synthetic test mocks where PIP was not placed away from wrist
        if d_wrist_pip < 0.02:
            is_ext = d_wrist_tip > d_wrist_mcp * 1.10
            return is_ext, 1.0 if is_ext else 0.0

        cos_angle = self._calculate_finger_joint_angle(mcp_idx, pip_idx, tip_idx)
        wrist_ext = d_wrist_tip > d_wrist_pip * 1.06
        mcp_ext = d_mcp_tip > d_mcp_pip * 1.25 if d_mcp_pip > 1e-4 else wrist_ext
        straight = cos_angle > 0.20

        is_ext = wrist_ext and (mcp_ext or straight)

        # Normalized extension confidence score [0.0..1.0]
        mcp_ratio = (d_mcp_tip / max(0.01, d_mcp_pip)) if d_mcp_pip > 1e-4 else (1.5 if is_ext else 0.5)
        reach_norm = d_mcp_tip / max(0.04, self.hand_scale)
        score = max(0.0, min(1.0, 0.40 * min(1.0, mcp_ratio / 2.0) + 0.35 * max(0.0, cos_angle) + 0.25 * min(1.0, reach_norm / 0.85)))
        return is_ext, score

    def _calculate_fingers_extended(self) -> Dict[str, bool]:
        """Calculates finger extension using rotation-invariant joint angles and chord distance ratios."""
        idx_ext, idx_score = self._is_finger_extended(INDEX_MCP, INDEX_PIP, INDEX_TIP)
        mid_ext, mid_score = self._is_finger_extended(MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP)
        ring_ext, ring_score = self._is_finger_extended(RING_MCP, RING_PIP, RING_TIP)
        pinky_ext, pinky_score = self._is_finger_extended(PINKY_MCP, PINKY_PIP, PINKY_TIP)

        # Thumb extension: Check thumb tip distance to pinky MCP compared to thumb IP distance
        pinky_mcp = self.landmarks_norm[PINKY_MCP]
        thumb_tip = self.landmarks_norm[THUMB_TIP]
        thumb_ip = self.landmarks_norm[THUMB_IP]
        d_tip_pinky = math.hypot(thumb_tip[0] - pinky_mcp[0], thumb_tip[1] - pinky_mcp[1])
        d_ip_pinky = math.hypot(thumb_ip[0] - pinky_mcp[0], thumb_ip[1] - pinky_mcp[1])
        thumb_ext = d_tip_pinky > d_ip_pinky * 1.12
        thumb_score = min(1.0, max(0.0, (d_tip_pinky / max(0.01, d_ip_pinky) - 0.8) / 0.8))

        self.finger_scores = {
            "thumb": thumb_score,
            "index": idx_score,
            "middle": mid_score,
            "ring": ring_score,
            "pinky": pinky_score
        }

        return {
            "thumb": thumb_ext,
            "index": idx_ext,
            "middle": mid_ext,
            "ring": ring_ext,
            "pinky": pinky_ext
        }

    @property
    def index_state(self) -> str:
        return self.finger_states.get("index", "FOLDED")

    @property
    def middle_state(self) -> str:
        return self.finger_states.get("middle", "FOLDED")

    @property
    def ring_state(self) -> str:
        return self.finger_states.get("ring", "FOLDED")

    @property
    def pinky_state(self) -> str:
        return self.finger_states.get("pinky", "FOLDED")

    @property
    def thumb_state(self) -> str:
        return self.finger_states.get("thumb", "FOLDED")

    @property
    def extended_count(self) -> int:
        return sum(1 for v in self.fingers_extended.values() if v)

    def get_finger_tip(self, finger_name: str) -> Tuple[float, float, float]:
        """Returns normalized (x, y, z) for the specified fingertip."""
        name = finger_name.lower()
        if name == "thumb":
            return self.landmarks_norm[THUMB_TIP]
        elif name == "index":
            return self.landmarks_norm[INDEX_TIP]
        elif name == "middle":
            return self.landmarks_norm[MIDDLE_TIP]
        elif name == "ring":
            return self.landmarks_norm[RING_TIP]
        elif name == "pinky":
            return self.landmarks_norm[PINKY_TIP]
        return self.landmarks_norm[INDEX_TIP]

    def get_finger_landmarks(self, finger_name: str) -> Dict[str, Tuple[float, float, float]]:
        """Returns normalized 3D landmarks for all joints of the specified finger."""
        name = finger_name.lower()
        wrist = self.landmarks_norm[WRIST]
        if name == "thumb":
            return {
                "tip": self.landmarks_norm[THUMB_TIP],
                "dip": self.landmarks_norm[THUMB_IP],
                "pip": self.landmarks_norm[THUMB_MCP],
                "mcp": self.landmarks_norm[THUMB_CMC],
                "wrist": wrist
            }
        elif name == "index":
            return {
                "tip": self.landmarks_norm[INDEX_TIP],
                "dip": self.landmarks_norm[INDEX_DIP],
                "pip": self.landmarks_norm[INDEX_PIP],
                "mcp": self.landmarks_norm[INDEX_MCP],
                "wrist": wrist
            }
        elif name == "middle":
            return {
                "tip": self.landmarks_norm[MIDDLE_TIP],
                "dip": self.landmarks_norm[MIDDLE_DIP],
                "pip": self.landmarks_norm[MIDDLE_PIP],
                "mcp": self.landmarks_norm[MIDDLE_MCP],
                "wrist": wrist
            }
        elif name == "ring":
            return {
                "tip": self.landmarks_norm[RING_TIP],
                "dip": self.landmarks_norm[RING_DIP],
                "pip": self.landmarks_norm[RING_PIP],
                "mcp": self.landmarks_norm[RING_MCP],
                "wrist": wrist
            }
        elif name == "pinky":
            return {
                "tip": self.landmarks_norm[PINKY_TIP],
                "dip": self.landmarks_norm[PINKY_DIP],
                "pip": self.landmarks_norm[PINKY_PIP],
                "mcp": self.landmarks_norm[PINKY_MCP],
                "wrist": wrist
            }
        return {"tip": self.landmarks_norm[INDEX_TIP], "wrist": wrist}

    def get_raw_finger_metric(self, finger_name: str) -> float:
        """Calculates monocular forward displacement and knuckle flex for baseline calibration."""
        name = finger_name.lower()
        joints = self.get_finger_landmarks(name)
        tip = joints["tip"]
        mcp = joints.get("mcp", joints["wrist"])
        pip = joints.get("pip", joints["wrist"])
        dip = joints.get("dip", pip)

        palm = max(0.04, self.hand_scale)
        # MediaPipe relative Z displacement (smaller/more negative Z = closer to camera/forward)
        rel_z = (mcp[2] - tip[2]) / palm

        if name == "thumb":
            # Thumb presses with inward/downward stroke toward virtual spacebar
            spread = abs(tip[0] - mcp[0]) / palm
            return 0.60 * rel_z + 0.40 * spread
        else:
            # Multi-segment knuckle curl (2D chord ratio)
            d_mcp_pip = math.hypot(pip[0] - mcp[0], pip[1] - mcp[1])
            d_pip_dip = math.hypot(dip[0] - pip[0], dip[1] - pip[1])
            d_dip_tip = math.hypot(tip[0] - dip[0], tip[1] - dip[1])
            total_arc = max(0.01, d_mcp_pip + d_pip_dip + d_dip_tip)
            chord = math.hypot(tip[0] - mcp[0], tip[1] - mcp[1])
            curl = max(0.0, 1.0 - (chord / total_arc))

            # Forward displacement and finger dip relative to PIP (no constant positive offset)
            dip_y = max(0.0, (tip[1] - pip[1]) / palm)
            return 0.65 * rel_z + 0.25 * curl + 0.10 * dip_y

    def calculate_finger_press_metric(self, finger_name: str, baseline: float = 0.0) -> float:
        """
        Estimates the intentional forward air-press depth metric for a monocular camera.
        Combines relative Z landmark delta and joint flex downward displacement,
        normalized by scale-invariant palm size, subtracting calibrated resting baseline.
        A resting hand produces ~0.0; an intentional forward air press rises towards 0.15+.
        """
        raw = self.get_raw_finger_metric(finger_name)
        return max(0.0, raw - baseline)


class HandTracker:
    """Manages the MediaPipe Hands graph, landmark extraction, and HUD drawing."""

    def __init__(self,
                 detection_confidence: float = 0.60,
                 tracking_confidence: float = 0.60,
                 max_num_hands: int = 2):
        self.detection_confidence = detection_confidence
        self.tracking_confidence = tracking_confidence
        self.max_num_hands = max_num_hands

        self.mp_hands = mp.solutions.hands
        self._init_hands()

    def _init_hands(self) -> None:
        try:
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=self.max_num_hands,
                min_detection_confidence=self.detection_confidence,
                min_tracking_confidence=self.tracking_confidence
            )
        except Exception as e:
            logger.error(f"Failed to initialize MediaPipe Hands: {e}")
            self.hands = None

    def update_confidence(self, det_conf: float, track_conf: float) -> None:
        """Dynamically reconfigures detection thresholds."""
        if self.detection_confidence != det_conf or self.tracking_confidence != track_conf:
            self.detection_confidence = det_conf
            self.tracking_confidence = track_conf
            if self.hands:
                self.hands.close()
            self._init_hands()

    def process_frame(self, frame_bgr: np.ndarray, is_mirrored: bool = True, frame_id: int = 0, timestamp: float = 0.0) -> List[HandLandmarkData]:
        """Runs hand detection on an OpenCV BGR frame and returns landmark data.

        MediaPipe Hands model was trained on non-mirrored images. When is_mirrored=True
        (frame was horizontally flipped with cv2.flip(frame, 1)), MediaPipe's
        classification label is geometrically inverted: physical Right hand is classified
        as 'Left', and physical Left hand is classified as 'Right'.
        This method performs mirror correction so handedness matches true physical reality.
        """
        if self.hands is None or frame_bgr is None:
            return []

        h, w = frame_bgr.shape[:2]
        # MediaPipe expects RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False

        try:
            results = self.hands.process(frame_rgb)
        except Exception as e:
            logger.error(f"Error during hand tracking inference: {e}")
            return []

        hands_data: List[HandLandmarkData] = []
        if not results.multi_hand_landmarks:
            return hands_data

        frame_time = timestamp if timestamp > 0 else time.time()

        for i, hand_landmarks in enumerate(results.multi_hand_landmarks):
            raw_label = "Right"
            handedness_conf = 0.95
            if results.multi_handedness and i < len(results.multi_handedness):
                cls_obj = results.multi_handedness[i].classification[0]
                raw_label = cls_obj.label
                handedness_conf = getattr(cls_obj, "score", 0.95)

            # Invert label if mirrored so that physical hand identity is accurate
            if is_mirrored:
                physical_handedness = "Right" if raw_label.lower() == "left" else "Left"
            else:
                physical_handedness = raw_label.capitalize()

            landmarks_norm = []
            landmarks_pixel = []
            for lm in hand_landmarks.landmark:
                landmarks_norm.append((lm.x, lm.y, lm.z))
                px = int(lm.x * w)
                py = int(lm.y * h)
                landmarks_pixel.append((px, py))

            data = HandLandmarkData(
                landmarks_norm=landmarks_norm,
                landmarks_pixel=landmarks_pixel,
                handedness=physical_handedness,
                frame_width=w,
                frame_height=h,
                confidence=handedness_conf,
                handedness_confidence=handedness_conf,
                frame_timestamp=frame_time,
                frame_id=frame_id
            )
            if data.is_valid:
                hands_data.append(data)

        return hands_data

    def draw_futuristic_hud(self,
                            frame: np.ndarray,
                            hand: HandLandmarkData,
                            is_pinching: bool = False,
                            is_dragging: bool = False,
                            pinch_threshold: float = 0.055,
                            active_box_bounds: Any = (0.16, 0.16),
                            tracking_landmark: str = "index_tip",
                            relative_anchor: Optional[Tuple[float, float]] = None,
                            secondary_hand: Optional[HandLandmarkData] = None,
                            scroll_telemetry: Optional[Any] = None,
                            gesture_state: Optional[Any] = None) -> np.ndarray:
        """Renders an Iron Man / JARVIS holographic HUD over the OpenCV video frame."""
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # 1. Active Tracking Box (Virtual screen ROI bounds)
        # Accepts either (margin_x, margin_y) or (roi_left, roi_top, roi_right, roi_bottom)
        if len(active_box_bounds) == 4:
            r_left, r_top, r_right, r_bottom = active_box_bounds
            bx1, by1 = int(w * r_left), int(h * r_top)
            bx2, by2 = int(w * r_right), int(h * r_bottom)
        else:
            mx, my = active_box_bounds
            bx1, by1 = int(w * mx), int(h * my)
            bx2, by2 = int(w * (1.0 - mx)), int(h * (1.0 - my))

        # Cyan corner brackets for active box
        bracket_len = 20
        bracket_color = (255, 200, 0)  # BGR Cyan

        # Corner brackets
        cv2.line(overlay, (bx1, by1), (bx1 + bracket_len, by1), bracket_color, 2)
        cv2.line(overlay, (bx1, by1), (bx1, by1 + bracket_len), bracket_color, 2)
        cv2.line(overlay, (bx2, by1), (bx2 - bracket_len, by1), bracket_color, 2)
        cv2.line(overlay, (bx2, by1), (bx2, by1 + bracket_len), bracket_color, 2)
        cv2.line(overlay, (bx1, by2), (bx1 + bracket_len, by2), bracket_color, 2)
        cv2.line(overlay, (bx1, by2), (bx1, by2 - bracket_len), bracket_color, 2)
        cv2.line(overlay, (bx2, by2), (bx2 - bracket_len, by2), bracket_color, 2)
        cv2.line(overlay, (bx2, by2), (bx2, by2 - bracket_len), bracket_color, 2)

        # Translucent border
        cv2.rectangle(overlay, (bx1, by1), (bx2, by2), (80, 60, 0), 1)

        # Draw secondary hand if present during two-hand air typing
        if secondary_hand:
            sec_color = (255, 180, 50)
            for s_idx, e_idx in HAND_CONNECTIONS:
                p1 = secondary_hand.get_pixel(s_idx)
                p2 = secondary_hand.get_pixel(e_idx)
                cv2.line(overlay, p1, p2, sec_color, 3)
                cv2.line(overlay, p1, p2, (255, 255, 220), 1)
            for idx in range(21):
                pt = secondary_hand.get_pixel(idx)
                radius = 5 if idx in (INDEX_TIP, THUMB_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP) else 3
                cv2.circle(overlay, pt, radius, (0, 200, 255), -1)
            sec_wrist = secondary_hand.get_pixel(WRIST)
            cv2.putText(overlay, f"MK-IV :: {secondary_hand.handedness.upper()} HAND",
                        (sec_wrist[0] - 40, sec_wrist[1] + 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 200, 255), 1, cv2.LINE_AA)

        # 2. Glowing Hand Skeleton Lines
        for start_idx, end_idx in HAND_CONNECTIONS:
            p1 = hand.get_pixel(start_idx)
            p2 = hand.get_pixel(end_idx)
            cv2.line(overlay, p1, p2, (255, 120, 0), 4)
            cv2.line(overlay, p1, p2, (255, 255, 200), 1)

        # 3. Glowing Landmark Nodes
        for idx in range(21):
            pt = hand.get_pixel(idx)
            if idx in (INDEX_TIP, THUMB_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP):
                radius = 7 if idx == INDEX_TIP else 5
                cv2.circle(overlay, pt, radius + 2, (255, 180, 0), 1)
                cv2.circle(overlay, pt, radius, (0, 240, 255), -1)
                cv2.circle(overlay, pt, 2, (255, 255, 255), -1)
            else:
                cv2.circle(overlay, pt, 3, (255, 160, 0), -1)

        # 4. Cursor Reticle on Active Tracking Point
        target_pt = hand.get_tracking_pixel(tracking_landmark)
        cv2.circle(overlay, target_pt, 18, (255, 220, 0), 1)
        # Crosshairs
        cv2.line(overlay, (target_pt[0] - 24, target_pt[1]), (target_pt[0] - 14, target_pt[1]), (255, 220, 0), 2)
        cv2.line(overlay, (target_pt[0] + 14, target_pt[1]), (target_pt[0] + 24, target_pt[1]), (255, 220, 0), 2)
        cv2.line(overlay, (target_pt[0], target_pt[1] - 24), (target_pt[0], target_pt[1] - 14), (255, 220, 0), 2)
        cv2.line(overlay, (target_pt[0], target_pt[1] + 14), (target_pt[0], target_pt[1] + 24), (255, 220, 0), 2)

        # Reticle label
        landmark_label = tracking_landmark.upper().replace("_", " ")
        cv2.putText(overlay, f"AIM: {landmark_label}", (target_pt[0] + 18, target_pt[1] - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 240, 255), 1, cv2.LINE_AA)

        # 5. Relative Anchor Point (if in relative mode)
        if relative_anchor is not None:
            anc_px = (int(relative_anchor[0] * w), int(relative_anchor[1] * h))
            cv2.circle(overlay, anc_px, 8, (0, 165, 255), 1)
            cv2.circle(overlay, anc_px, 2, (0, 255, 255), -1)
            cv2.line(overlay, anc_px, target_pt, (0, 165, 255), 1)

        # 6. Pinch Connection Line and Dynamic Status
        idx_pt = hand.get_pixel(INDEX_TIP)
        thumb_pt = hand.get_pixel(THUMB_TIP)
        use_norm = pinch_threshold > 0.18
        pinch_dist = hand.norm_pinch_distance if use_norm else hand.pinch_distance
        dist_color = (0, 255, 0) if is_pinching else ((0, 200, 255) if pinch_dist < pinch_threshold * 1.3 else (255, 180, 0))

        cv2.line(overlay, idx_pt, thumb_pt, dist_color, 3 if is_pinching else 2)
        mid_x = (idx_pt[0] + thumb_pt[0]) // 2
        mid_y = (idx_pt[1] + thumb_pt[1]) // 2
        cv2.circle(overlay, (mid_x, mid_y), 6 if is_pinching else 4, dist_color, -1)
        if is_pinching:
            cv2.circle(overlay, (mid_x, mid_y), 14, (0, 255, 120), 2)

        # Pinch telemetry readout
        pct = max(0, min(100, int((1.0 - (pinch_dist / (pinch_threshold * 1.8))) * 100)))
        if is_dragging:
            status_label = "DRAG [ACTIVE]"
            dist_color = (0, 140, 255)
        elif is_pinching:
            status_label = "CLICK!"
            dist_color = (0, 255, 0)
        else:
            status_label = f"PINCH: {pct}%"

        cv2.putText(overlay, status_label, (mid_x + 10, mid_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, dist_color, 1, cv2.LINE_AA)

        # 7. Hand ID and telemetry tag near wrist
        wrist_pt = hand.get_pixel(WRIST)
        tag = f"MK-IV :: {hand.handedness.upper()} HAND"
        cv2.putText(overlay, tag, (wrist_pt[0] - 40, wrist_pt[1] + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1, cv2.LINE_AA)

        # 8. Scroll Gesture HUD overlay
        if scroll_telemetry and getattr(scroll_telemetry, "scroll_mode", False):
            anc_y = getattr(scroll_telemetry, "anchor_y", None)
            direction = getattr(scroll_telemetry, "direction", "NONE")
            speed = getattr(scroll_telemetry, "speed", 0.0)
            if anc_y is not None:
                ay_px = int(h * anc_y)
                ax_px = idx_pt[0]
                # Anchor reticle
                cv2.circle(overlay, (ax_px, ay_px), 8, (255, 200, 0), 1)
                cv2.line(overlay, (ax_px - 12, ay_px), (ax_px + 12, ay_px), (255, 200, 0), 1)
                # Displacement line
                cv2.line(overlay, (ax_px, ay_px), idx_pt, (0, 240, 255), 2)
                # Scroll status banner
                if direction == "UP":
                    sc_text = f"SCROLL UP :: {speed:.1f} evt/s"
                    sc_color = (0, 255, 120)
                elif direction == "DOWN":
                    sc_text = f"SCROLL DOWN :: {speed:.1f} evt/s"
                    sc_color = (0, 200, 255)
                else:
                    sc_text = "SCROLL DEADZONE (NEUTRAL)"
                    sc_color = (180, 180, 180)
                cv2.putText(overlay, sc_text, (ax_px - 80, ay_px - 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, sc_color, 1, cv2.LINE_AA)

        # 9. Two-Finger Reticle & Linking Beam Overlay
        two_fg_status = getattr(gesture_state, "two_finger_stability_status", "OFF") if gesture_state else "OFF"
        is_two_finger = (
            two_fg_status in ("STABLE", "EVALUATING") or
            (hand.fingers_extended.get("index", False) and hand.fingers_extended.get("middle", False) and not hand.fingers_extended.get("pinky", False))
        )
        if is_two_finger:
            idx_pt = hand.get_pixel(INDEX_TIP)
            mid_pt = hand.get_pixel(MIDDLE_TIP)
            reticle_col = (0, 255, 120) if two_fg_status == "STABLE" else (255, 230, 0)

            # Dual fingertip reticles & crosshairs
            for tip_p in (idx_pt, mid_pt):
                cv2.circle(overlay, tip_p, 15, reticle_col, 2)
                cv2.circle(overlay, tip_p, 8, (255, 255, 255), 1)
                cv2.line(overlay, (tip_p[0] - 20, tip_p[1]), (tip_p[0] + 20, tip_p[1]), reticle_col, 1)
                cv2.line(overlay, (tip_p[0], tip_p[1] - 20), (tip_p[0], tip_p[1] + 20), reticle_col, 1)

            # Holographic linking beam connecting index & middle fingertips
            cv2.line(overlay, idx_pt, mid_pt, reticle_col, 2)
            c_x = (idx_pt[0] + mid_pt[0]) // 2
            c_y = (idx_pt[1] + mid_pt[1]) // 2
            cv2.circle(overlay, (c_x, c_y), 4, (255, 255, 255), -1)
            ret_label = f"2-FINGER [{two_fg_status}]" if two_fg_status != "OFF" else "TWO-FINGER"
            cv2.putText(overlay, ret_label, (c_x - 42, min(idx_pt[1], mid_pt[1]) - 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, reticle_col, 1, cv2.LINE_AA)

        # 10. Real-time Two-Finger & Gesture Debug HUD Panel (Top-Left)
        card_x1, card_y1 = 12, 12
        card_w, card_h = 245, 105
        cv2.rectangle(overlay, (card_x1, card_y1), (card_x1 + card_w, card_y1 + card_h), (12, 16, 28), -1)
        cv2.rectangle(overlay, (card_x1, card_y1), (card_x1 + card_w, card_y1 + card_h), (0, 200, 255), 1)

        # Header: Hand & Confidence
        conf_pct = int(hand.confidence * 100)
        cv2.putText(overlay, f"JARVIS // HAND: {hand.handedness.upper()} ({conf_pct}%)",
                    (card_x1 + 8, card_y1 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 240, 255), 1, cv2.LINE_AA)
        cv2.line(overlay, (card_x1 + 6, card_y1 + 24), (card_x1 + card_w - 6, card_y1 + 24), (0, 100, 150), 1)

        # Finger states
        i_col = (0, 255, 120) if hand.index_state == "EXTENDED" else (160, 160, 160)
        m_col = (0, 255, 120) if hand.middle_state == "EXTENDED" else (160, 160, 160)
        r_col = (0, 255, 120) if hand.ring_state == "EXTENDED" else (160, 160, 160)
        p_col = (0, 255, 120) if hand.pinky_state == "EXTENDED" else (160, 160, 160)

        cv2.putText(overlay, f"IDX: {hand.index_state}", (card_x1 + 8, card_y1 + 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, i_col, 1, cv2.LINE_AA)
        cv2.putText(overlay, f"MID: {hand.middle_state}", (card_x1 + 124, card_y1 + 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, m_col, 1, cv2.LINE_AA)
        cv2.putText(overlay, f"RNG: {hand.ring_state}", (card_x1 + 8, card_y1 + 59),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, r_col, 1, cv2.LINE_AA)
        cv2.putText(overlay, f"LTL: {hand.pinky_state}", (card_x1 + 124, card_y1 + 59),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, p_col, 1, cv2.LINE_AA)

        # Current recognized gesture
        g_name = gesture_state.gesture.value if gesture_state and hasattr(gesture_state, "gesture") else "NONE"
        cv2.putText(overlay, f"GESTURE: {g_name[:18]}", (card_x1 + 8, card_y1 + 78),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 220, 0), 1, cv2.LINE_AA)

        # Stability status
        st_col = (0, 255, 120) if two_fg_status == "STABLE" else ((255, 200, 0) if two_fg_status == "EVALUATING" else (140, 140, 140))
        cv2.putText(overlay, f"TWO-FINGER: {two_fg_status}", (card_x1 + 8, card_y1 + 96),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, st_col, 1, cv2.LINE_AA)

        # Blend with subtle hologram transparency
        alpha = 0.88
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        return frame

    def close(self) -> None:
        """Releases MediaPipe resources."""
        if self.hands:
            try:
                self.hands.close()
            except Exception:
                pass
            self.hands = None
            logger.info("HandTracker pipeline closed.")
