"""JARVIS Gesture Recognition Engine.
Detects discrete and continuous gestures with hysteresis, debouncing, and state tracking.
"""

import time
import enum
import logging
from typing import Optional, Tuple, Dict, Any
from app.hand_tracker import (
    HandLandmarkData, WRIST, THUMB_TIP, INDEX_TIP, INDEX_PIP, INDEX_MCP,
    MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP, RING_TIP, RING_MCP, PINKY_TIP
)

logger = logging.getLogger("NEXUS.GestureRecognizer")


class GestureType(enum.Enum):
    NONE = "NONE"
    INDEX_POINT = "CURSOR_MOVE"
    PINCH_LEFT_CLICK = "LEFT_CLICK"
    PINCH_DRAG = "DRAGGING"
    PINCH_RIGHT_CLICK = "RIGHT_CLICK"
    TWO_FINGER_SCROLL = "SCROLL"
    SWIPE_LEFT = "SWIPE_LEFT"
    SWIPE_RIGHT = "SWIPE_RIGHT"
    OPEN_PALM_PAUSE = "PAUSE_SAFE"
    FIST_EMERGENCY = "EMERGENCY_STOP"
    PEACE_SIGN = "SWITCH_MODE"


class GestureState:
    """Carries full gesture telemetry for current frame."""
    def __init__(self,
                 gesture: GestureType = GestureType.NONE,
                 cursor_coords: Optional[Tuple[float, float]] = None,
                 pinch_active: bool = False,
                 is_dragging: bool = False,
                 scroll_dy: float = 0.0,
                 scroll_dx: float = 0.0,
                 confidence: float = 1.0,
                 description: str = "",
                 is_two_finger_stable: bool = False,
                 two_finger_stability_status: str = "OFF",
                 finger_states: Optional[Dict[str, str]] = None,
                 hand_label: str = "NONE",
                 tracking_confidence: float = 0.0):
        self.gesture = gesture
        self.cursor_coords = cursor_coords  # (norm_x, norm_y) [0..1]
        self.pinch_active = pinch_active
        self.is_dragging = is_dragging
        self.scroll_dy = scroll_dy
        self.scroll_dx = scroll_dx
        self.confidence = confidence
        self.description = description
        self.is_two_finger_stable = is_two_finger_stable
        self.two_finger_stability_status = two_finger_stability_status  # "OFF", "EVALUATING", "STABLE"
        self.finger_states = finger_states or {}
        self.hand_label = hand_label
        self.tracking_confidence = tracking_confidence


class GestureRecognizer:
    """Processes HandLandmarkData to classify user gestures with hysteresis and cooldowns."""

    def __init__(self,
                 pinch_threshold: float = 0.42,
                 pinch_release_threshold: Optional[float] = None,
                 right_click_threshold: Optional[float] = None,
                 click_cooldown: float = 0.22,
                 drag_hold_duration: float = 0.45,
                 fist_hold_duration: float = 0.70,
                 palm_hold_duration: float = 0.50,
                 tracking_landmark: str = "index_tip",
                 pinch_normalized: bool = True,
                 right_click_gesture: str = "thumb_middle_pinch"):
        # Thresholds
        self.pinch_threshold = pinch_threshold
        self.pinch_release_threshold = pinch_release_threshold if pinch_release_threshold is not None else (pinch_threshold * 1.35)
        self.right_click_threshold = right_click_threshold if right_click_threshold is not None else (pinch_threshold * 0.95)
        self.click_cooldown = click_cooldown
        self.drag_hold_duration = drag_hold_duration
        self.fist_hold_duration = fist_hold_duration
        self.palm_hold_duration = palm_hold_duration

        # Configuration options
        self.tracking_landmark = tracking_landmark
        self.pinch_normalized = pinch_normalized
        self.right_click_gesture = right_click_gesture

        # State tracking
        self.is_pinching: bool = False
        self.pinch_start_time: float = 0.0
        self.last_click_time: float = 0.0
        self.is_dragging: bool = False

        self.is_right_pinching: bool = False
        self.last_right_click_time: float = 0.0

        # Scroll reference
        self.last_scroll_y: Optional[float] = None
        self.last_scroll_x: Optional[float] = None
        self.last_swipe_time: float = 0.0

        # Two-Finger Gesture Temporal Smoothing and Debounce State
        self.two_finger_counter: int = 0
        self.two_finger_stable_threshold: int = 2   # 2 frames to confirm STABLE status
        self.two_finger_dropout_counter: int = 0
        self.two_finger_dropout_grace: int = 1      # 1 frame dropout tolerance against single-frame tracking glitches
        self.is_two_finger_active: bool = False
        self.is_two_finger_stable: bool = False

        # Continuous gesture timers
        self.fist_start_time: Optional[float] = None
        self.palm_start_time: Optional[float] = None
        self.peace_start_time: Optional[float] = None

        # Configuration overrides
        self.enabled_gestures: Dict[str, bool] = {
            "cursor_move": True,
            "left_click": True,
            "drag_and_drop": True,
            "right_click": True,
            "scroll": True,
            "open_palm_pause": True,
            "fist_emergency_stop": False
        }

    def update_config(self,
                      pinch_th: float,
                      release_th: float,
                      click_cd: float,
                      tracking_landmark: Optional[str] = None,
                      pinch_normalized: Optional[bool] = None,
                      right_click_gesture: Optional[str] = None) -> None:
        self.pinch_threshold = pinch_th
        self.pinch_release_threshold = max(release_th, pinch_th + 0.015)
        self.click_cooldown = click_cd
        if tracking_landmark is not None:
            self.tracking_landmark = tracking_landmark
        if pinch_normalized is not None:
            self.pinch_normalized = pinch_normalized
        if right_click_gesture is not None:
            self.right_click_gesture = right_click_gesture

    def reset(self) -> None:
        """Resets all active gesture states."""
        self.is_pinching = False
        self.is_dragging = False
        self.is_right_pinching = False
        self.last_scroll_y = None
        self.last_scroll_x = None
        self.fist_start_time = None
        self.palm_start_time = None
        self.peace_start_time = None
        self.two_finger_counter = 0
        self.two_finger_dropout_counter = 0
        self.is_two_finger_active = False
        self.is_two_finger_stable = False

    def recognize(self, hand: Optional[HandLandmarkData]) -> GestureState:
        """Main recognition cycle for a single frame of hand landmarks."""
        now = time.time()
        if hand is None:
            self.reset()
            return GestureState(
                GestureType.NONE,
                description="NO HAND DETECTED",
                is_two_finger_stable=False,
                two_finger_stability_status="OFF",
                finger_states={},
                hand_label="NONE",
                tracking_confidence=0.0
            )

        # Reject if tracking confidence is too low or landmarks are invalid
        if not hand.is_valid or hand.confidence < 0.25:
            self.reset()
            return GestureState(
                GestureType.NONE,
                cursor_coords=hand.get_tracking_point(self.tracking_landmark),
                confidence=hand.confidence,
                description="LOW TRACKING CONFIDENCE",
                is_two_finger_stable=False,
                two_finger_stability_status="OFF",
                finger_states=getattr(hand, "finger_states", {}),
                hand_label=hand.handedness,
                tracking_confidence=hand.confidence
            )

        fingers = hand.fingers_extended
        idx_ext = fingers["index"]
        mid_ext = fingers["middle"]
        ring_ext = fingers["ring"]
        pinky_ext = fingers["pinky"]
        thumb_ext = fingers["thumb"]
        total_extended = hand.extended_count

        # Coordinates from the selected ergonomic tracking landmark
        cursor_coords = hand.get_tracking_point(self.tracking_landmark)

        # Distance calculation (scale-invariant normalized vs raw)
        use_norm = self.pinch_threshold > 0.18 or self.pinch_normalized
        if self.pinch_threshold <= 0.15:
            use_norm = False
        pinch_dist = hand.norm_pinch_distance if use_norm else hand.pinch_distance
        middle_pinch_dist = hand.norm_pinch_middle_distance if use_norm else hand.pinch_middle_distance

        # -------------------------------------------------------------
        # 1. CLOSED FIST / RESTING HAND (All 5 fingers closed)
        # Automatic emergency stop is removed to prevent accidental locking.
        # A closed fist is treated as a safe neutral resting posture.
        # -------------------------------------------------------------
        if total_extended == 0:
            self.two_finger_counter = 0
            self.is_two_finger_active = False

            # Optional emergency fist trigger ONLY if explicitly enabled in configuration
            if self.enabled_gestures.get("fist_emergency_stop", False):
                if self.fist_start_time is None:
                    self.fist_start_time = now
                elif now - self.fist_start_time >= self.fist_hold_duration:
                    return GestureState(
                        GestureType.FIST_EMERGENCY,
                        confidence=hand.confidence,
                        description="EMERGENCY STOP (FIST LOCKED)",
                        is_two_finger_stable=False,
                        two_finger_stability_status="OFF",
                        finger_states=hand.finger_states,
                        hand_label=hand.handedness,
                        tracking_confidence=hand.confidence
                    )
                progress = int(((now - self.fist_start_time) / self.fist_hold_duration) * 100)
                return GestureState(
                    GestureType.NONE,
                    confidence=hand.confidence,
                    description=f"EMERGENCY FIST DETECTED ({progress}%)",
                    is_two_finger_stable=False,
                    two_finger_stability_status="OFF",
                    finger_states=hand.finger_states,
                    hand_label=hand.handedness,
                    tracking_confidence=hand.confidence
                )

            self.fist_start_time = None
            return GestureState(
                GestureType.NONE,
                cursor_coords=cursor_coords,
                confidence=hand.confidence,
                description="CLOSED FIST (RESTING HAND)",
                is_two_finger_stable=False,
                two_finger_stability_status="OFF",
                finger_states=hand.finger_states,
                hand_label=hand.handedness,
                tracking_confidence=hand.confidence
            )
        else:
            self.fist_start_time = None

        # -------------------------------------------------------------
        # 2. OPEN PALM (All 5 fingers extended) -> NEUTRAL RELAXED HAND
        # Does NOT trigger pause mode - allows comfortable hand resting
        # -------------------------------------------------------------
        if total_extended == 5:
            self.two_finger_counter = 0
            self.is_two_finger_active = False
            self.palm_start_time = None
            return GestureState(
                GestureType.NONE,
                cursor_coords=cursor_coords,
                confidence=hand.confidence,
                description="OPEN PALM (NEUTRAL)",
                is_two_finger_stable=False,
                two_finger_stability_status="OFF",
                finger_states=hand.finger_states,
                hand_label=hand.handedness,
                tracking_confidence=hand.confidence
            )
        else:
            self.palm_start_time = None

        # -------------------------------------------------------------
        # 3. TWO FINGER SCROLL & SWIPE
        # (Index + Middle extended, Ring + Pinky curled/folded)
        # Prevents accidental clicks and dragging during scroll operations!
        # -------------------------------------------------------------
        # Rotation-invariant anatomical tendon coupling tolerance:
        # Ring finger is considered folded if:
        # - not ring_ext, OR
        # - reach of ring finger (RING_MCP to RING_TIP) is < 82% of middle finger reach (MIDDLE_MCP to MIDDLE_TIP)
        d_ring_reach = hand.get_2d_distance(RING_MCP, RING_TIP)
        d_mid_reach = hand.get_2d_distance(MIDDLE_MCP, MIDDLE_TIP)
        ring_folded = (not ring_ext) or (d_ring_reach < d_mid_reach * 0.82)
        pinky_folded = not pinky_ext

        # Deliberate two-finger gesture candidate:
        # - Index is extended
        # - Middle is extended
        # - Ring is folded (or anatomically subordinate to middle)
        # - Pinky is folded
        # - Total extended count <= 3
        # Strict suppression: Takes precedence over pinch click to prevent accidental clicks during scrolling!
        is_two_finger_candidate = (
            idx_ext and
            mid_ext and
            ring_folded and
            pinky_folded and
            (total_extended <= 3)
        )

        # Temporal smoothing & stability state machine
        if is_two_finger_candidate:
            self.two_finger_counter += 1
            self.two_finger_dropout_counter = 0
            self.is_two_finger_active = True
            is_stable = (self.two_finger_counter >= self.two_finger_stable_threshold)
            stability_str = "STABLE" if is_stable else "EVALUATING"
        elif self.is_two_finger_active and self.two_finger_dropout_counter < self.two_finger_dropout_grace:
            # 1-frame dropout tolerance (glitch protection against temporary landmark loss)
            self.two_finger_dropout_counter += 1
            is_stable = (self.two_finger_counter >= self.two_finger_stable_threshold)
            stability_str = "STABLE" if is_stable else "EVALUATING"
        else:
            self.two_finger_counter = 0
            self.two_finger_dropout_counter = 0
            self.is_two_finger_active = False
            is_stable = False
            stability_str = "OFF"

        if self.is_two_finger_active and self.enabled_gestures.get("scroll", True):
            # Midpoint between index tip and middle tip
            mid_x = (hand.get_norm(INDEX_TIP)[0] + hand.get_norm(MIDDLE_TIP)[0]) / 2.0
            mid_y = (hand.get_norm(INDEX_TIP)[1] + hand.get_norm(MIDDLE_TIP)[1]) / 2.0
            dy = 0.0
            dx = 0.0
            if self.last_scroll_y is not None:
                dy = mid_y - self.last_scroll_y
            if self.last_scroll_x is not None:
                dx = mid_x - self.last_scroll_x
            self.last_scroll_y = mid_y
            self.last_scroll_x = mid_x

            # Reset any active pinch states when in scrolling gesture
            self.is_pinching = False
            self.is_dragging = False
            self.is_right_pinching = False

            # Check rapid horizontal swipe
            if abs(dx) > 0.075 and (now - self.last_swipe_time > 0.40):
                self.last_swipe_time = now
                sw_type = GestureType.SWIPE_LEFT if dx < 0 else GestureType.SWIPE_RIGHT
                desc = "SWIPE LEFT" if dx < 0 else "SWIPE RIGHT"
                return GestureState(
                    sw_type,
                    cursor_coords=cursor_coords,
                    scroll_dy=dy,
                    scroll_dx=dx,
                    confidence=hand.confidence,
                    is_two_finger_stable=is_stable,
                    two_finger_stability_status=stability_str,
                    finger_states=hand.finger_states,
                    hand_label=hand.handedness,
                    tracking_confidence=hand.confidence,
                    description=desc
                )

            return GestureState(
                GestureType.TWO_FINGER_SCROLL,
                cursor_coords=cursor_coords,
                scroll_dy=dy,
                scroll_dx=dx,
                confidence=hand.confidence,
                is_two_finger_stable=is_stable,
                two_finger_stability_status=stability_str,
                finger_states=hand.finger_states,
                hand_label=hand.handedness,
                tracking_confidence=hand.confidence,
                description=f"TWO-FINGER SCROLL ({stability_str}, dy={dy:.3f}, dx={dx:.3f})"
            )
        else:
            self.last_scroll_y = None
            self.last_scroll_x = None

        # -------------------------------------------------------------
        # 4. RIGHT CLICK
        # -------------------------------------------------------------
        if self.enabled_gestures.get("right_click", True):
            right_triggered = False
            if self.right_click_gesture == "index_middle_pinch":
                im_dist = hand.get_distance(INDEX_TIP, MIDDLE_TIP)
                if use_norm:
                    im_dist = im_dist / hand.hand_scale
                eff_th = min(self.right_click_threshold, 0.22) if use_norm else 0.04
                # Requires index and middle tips to actively touch each other with fingers extended
                right_triggered = (im_dist < eff_th) and (pinch_dist > eff_th * 1.5) and idx_ext and mid_ext
            else:
                # Default: thumb to middle tip pinch (must be a deliberate middle pinch, not index pointing)
                eff_th = min(self.right_click_threshold, 0.28) if use_norm else 0.04
                right_triggered = (middle_pinch_dist < eff_th) and (middle_pinch_dist < pinch_dist * 0.75) and (pinch_dist > 0.36)

            if not self.is_right_pinching and right_triggered:
                if now - self.last_right_click_time >= self.click_cooldown * 1.5:
                    self.is_right_pinching = True
                    self.last_right_click_time = now
                    logger.info("[GESTURE] Right Click Triggered")
                    return GestureState(
                        GestureType.PINCH_RIGHT_CLICK,
                        cursor_coords=cursor_coords,
                        confidence=hand.confidence,
                        is_two_finger_stable=False,
                        two_finger_stability_status="OFF",
                        finger_states=hand.finger_states,
                        hand_label=hand.handedness,
                        tracking_confidence=hand.confidence,
                        description="RIGHT CLICK ACTIVATED"
                    )
            elif self.is_right_pinching and not right_triggered:
                self.is_right_pinching = False

        # -------------------------------------------------------------
        # 5. PINCH (Thumb to Index Tip) -> EASY LEFT CLICK / DRAG
        # -------------------------------------------------------------
        if self.enabled_gestures.get("left_click", True):
            # Hysteresis: enter pinch below threshold
            if not self.is_pinching:
                if pinch_dist < self.pinch_threshold:
                    # Check click cooldown
                    if now - self.last_click_time >= self.click_cooldown:
                        self.is_pinching = True
                        self.pinch_start_time = now
                        self.last_click_time = now
                        logger.info(f"[GESTURE] Left click triggered (dist={pinch_dist:.4f} < {self.pinch_threshold:.4f})")
                        return GestureState(
                            GestureType.PINCH_LEFT_CLICK,
                            cursor_coords=cursor_coords,
                            pinch_active=True,
                            confidence=hand.confidence,
                            is_two_finger_stable=False,
                            two_finger_stability_status="OFF",
                            finger_states=hand.finger_states,
                            hand_label=hand.handedness,
                            tracking_confidence=hand.confidence,
                            description="LEFT CLICK"
                        )
                    else:
                        # Cooldown is active: maintain cursor tracking without locking out subsequent clicks
                        return GestureState(
                            GestureType.INDEX_POINT,
                            cursor_coords=cursor_coords,
                            pinch_active=True,
                            confidence=hand.confidence,
                            is_two_finger_stable=False,
                            two_finger_stability_status="OFF",
                            finger_states=hand.finger_states,
                            hand_label=hand.handedness,
                            tracking_confidence=hand.confidence,
                            description="PINCH TAP (COOLDOWN)"
                        )
            else:
                # Still pinching - check for release or drag initiation
                if pinch_dist > self.pinch_release_threshold:
                    # Released pinch
                    self.is_pinching = False
                    self.is_dragging = False
                else:
                    # Pinch is being held!
                    if self.enabled_gestures.get("drag_and_drop", True):
                        if (now - self.pinch_start_time) >= self.drag_hold_duration:
                            self.is_dragging = True
                            return GestureState(
                                GestureType.PINCH_DRAG,
                                cursor_coords=cursor_coords,
                                pinch_active=True,
                                is_dragging=True,
                                confidence=hand.confidence,
                                is_two_finger_stable=False,
                                two_finger_stability_status="OFF",
                                finger_states=hand.finger_states,
                                hand_label=hand.handedness,
                                tracking_confidence=hand.confidence,
                                description="DRAG AND DROP (HELD)"
                            )
                    return GestureState(
                        GestureType.NONE,
                        cursor_coords=cursor_coords,
                        pinch_active=True,
                        confidence=hand.confidence,
                        is_two_finger_stable=False,
                        two_finger_stability_status="OFF",
                        finger_states=hand.finger_states,
                        hand_label=hand.handedness,
                        tracking_confidence=hand.confidence,
                        description="PINCH HELD"
                    )

        # -------------------------------------------------------------
        # 6. INDEX POINT (Cursor Movement)
        # -------------------------------------------------------------
        if idx_ext and self.enabled_gestures.get("cursor_move", True):
            return GestureState(
                GestureType.INDEX_POINT,
                cursor_coords=cursor_coords,
                confidence=hand.confidence,
                is_two_finger_stable=False,
                two_finger_stability_status="OFF",
                finger_states=hand.finger_states,
                hand_label=hand.handedness,
                tracking_confidence=hand.confidence,
                description="TRACKING CURSOR"
            )

        return GestureState(
            GestureType.NONE,
            cursor_coords=cursor_coords,
            confidence=hand.confidence,
            is_two_finger_stable=False,
            two_finger_stability_status="OFF",
            finger_states=hand.finger_states,
            hand_label=hand.handedness,
            tracking_confidence=hand.confidence,
            description="HAND ACTIVE"
        )
