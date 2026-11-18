"""N.E.X.U.S. Vision Geometry & Kinematics Engine.
Pure mathematical operations for rotation-invariant and scale-invariant gesture tracking.
Decoupled from any GUI framework.
"""

import math
from typing import Tuple, List, Optional


def calculate_joint_angle_cos(mcp: Tuple[float, float],
                              pip: Tuple[float, float],
                              tip: Tuple[float, float]) -> float:
    """Calculates vector cosine angle between (PIP - MCP) and (TIP - PIP).
    Value near 1.0 means the finger is straight; near 0.0 or negative means curled/folded.
    """
    u = (pip[0] - mcp[0], pip[1] - mcp[1])
    v = (tip[0] - pip[0], tip[1] - pip[1])
    u_len = math.hypot(u[0], u[1])
    v_len = math.hypot(v[0], v[1])
    if u_len < 1e-5 or v_len < 1e-5:
        return 1.0
    dot = u[0] * v[0] + u[1] * v[1]
    return max(-1.0, min(1.0, dot / (u_len * v_len)))


def is_finger_extended_joints(wrist: Tuple[float, float],
                              mcp: Tuple[float, float],
                              pip: Tuple[float, float],
                              tip: Tuple[float, float]) -> Tuple[bool, float]:
    """Calculates rotation-invariant, distance-invariant finger extension.
    Evaluates:
    1. Joint vector cosine angle.
    2. MCP-to-TIP reach vs MCP-to-PIP.
    3. Wrist-to-TIP distance vs Wrist-to-PIP distance.
    Returns: (is_extended: bool, confidence_score: float)
    """
    d_mcp_pip = math.hypot(pip[0] - mcp[0], pip[1] - mcp[1])
    if d_mcp_pip < 1e-4:
        # Mock or unpopulated intermediate joints
        return True, 1.0

    cos_angle = calculate_joint_angle_cos(mcp, pip, tip)
    d_mcp_tip = math.hypot(tip[0] - mcp[0], tip[1] - mcp[1])
    d_w_tip = math.hypot(tip[0] - wrist[0], tip[1] - wrist[1])
    d_w_pip = math.hypot(pip[0] - wrist[0], pip[1] - wrist[1])

    straight = cos_angle > 0.20
    reached = (d_mcp_tip > d_mcp_pip * 1.20) if d_mcp_pip > 1e-4 else (d_w_tip > d_w_pip * 1.05)
    wrist_ext = d_w_tip > d_w_pip * 1.05

    is_ext = wrist_ext and (reached or straight)
    score = max(0.0, min(1.0, 0.5 * max(0.0, cos_angle) + 0.5 * min(1.0, d_mcp_tip / max(0.01, d_mcp_pip * 2.0))))
    return is_ext, score


def calculate_scale_invariant_pinch(thumb_tip: Tuple[float, float],
                                    index_tip: Tuple[float, float],
                                    wrist: Tuple[float, float],
                                    middle_mcp: Tuple[float, float]) -> float:
    """Calculates pinch distance normalized by the palm scale (wrist to middle knuckle).
    Immune to camera zoom and user distance.
    """
    palm_scale = max(0.04, math.hypot(wrist[0] - middle_mcp[0], wrist[1] - middle_mcp[1]))
    raw_dist = math.hypot(thumb_tip[0] - index_tip[0], thumb_tip[1] - index_tip[1])
    return raw_dist / palm_scale


def map_coords_to_roi(norm_x: float, norm_y: float,
                      roi_left: float = 0.20, roi_top: float = 0.20,
                      roi_right: float = 0.80, roi_bottom: float = 0.80) -> Tuple[float, float, bool]:
    """Maps normalized camera coordinates into interaction ROI space (0.0 to 1.0).
    Returns (mapped_x, mapped_y, is_inside_roi).
    """
    rw = max(0.01, roi_right - roi_left)
    rh = max(0.01, roi_bottom - roi_top)

    is_inside = (roi_left <= norm_x <= roi_right) and (roi_top <= norm_y <= roi_bottom)
    clamped_x = max(roi_left, min(roi_right, norm_x))
    clamped_y = max(roi_top, min(roi_bottom, norm_y))

    mapped_x = (clamped_x - roi_left) / rw
    mapped_y = (clamped_y - roi_top) / rh
    return mapped_x, mapped_y, is_inside
