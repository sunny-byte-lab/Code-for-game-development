"""N.E.X.U.S. Holographic HUD Widgets.
Cinematic, Iron Man-inspired custom-painted Qt widgets.
All rendering is executed programmatically via QPainter for GPU-free 60fps smooth animation.
"""

import math
import time
import random
from typing import Optional, List, Tuple
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QPointF, QSizeF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient,
    QLinearGradient, QConicalGradient, QPolygonF, QImage, QPainterPath
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QLabel, QTextEdit, QSizePolicy
)
from app.theme import (
    ACCENT_CYAN, ACCENT_ICY_BLUE, ACCENT_BLUE, ACCENT_GOLD, ACCENT_GREEN,
    ACCENT_RED, BG_DARK_NAVY, BG_PANEL, TEXT_PRIMARY, TEXT_MUTED
)


# ---------------------------------------------------------------------------
# NEXUS LOGO / EMBLEM
# ---------------------------------------------------------------------------
class NexusLogoWidget(QWidget):
    """Compact animated N.E.X.U.S. diamond-ring emblem with slow pulse."""

    def __init__(self, parent: Optional[QWidget] = None, size: int = 42):
        super().__init__(parent)
        self.logo_size = size
        self.setFixedSize(size, size)
        self._phase = 0.0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(50)

    def _tick(self):
        self._phase = (self._phase + 0.04) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        r = min(cx, cy) - 2.0
        pulse = 0.82 + 0.18 * math.sin(self._phase)

        # Outer glow ring
        p.setPen(QPen(QColor(0, 240, 255, int(120 * pulse)), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Middle ring
        r2 = r * 0.70
        p.setPen(QPen(QColor(56, 189, 248, int(180 * pulse)), 1.2))
        p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))

        # Diamond hex
        r3 = r * 0.52
        pts = [QPointF(cx + r3 * math.cos(math.radians(a)), cy + r3 * math.sin(math.radians(a)))
               for a in [270, 330, 30, 90, 150, 210]]
        poly = QPolygonF(pts)
        p.setPen(QPen(QColor(0, 240, 255, 200), 1.0))
        p.drawPolygon(poly)

        # Central glow
        rc = r * 0.28
        g = QRadialGradient(cx, cy, rc)
        g.setColorAt(0.0, QColor(255, 255, 255, 255))
        g.setColorAt(0.4, QColor(0, 240, 255, int(230 * pulse)))
        g.setColorAt(1.0, QColor(0, 80, 200, 0))
        p.setBrush(QBrush(g))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - rc, cy - rc, rc * 2, rc * 2))


# ---------------------------------------------------------------------------
# NEXUS CORE -- LARGE CINEMATIC HOLOGRAPHIC REACTOR
# ---------------------------------------------------------------------------
class NexusCoreWidget(QWidget):
    """
    Cinematic N.E.X.U.S. holographic energy core.
    Features:
    - 6 independently rotating multi-layered rings
    - Perspective holographic pedestal / platform grid underneath
    - Central pulsating energy sphere with inner geometric N.E.X.U.S. glyph
    - Real-time gesture reactivity:
        * Illuminates outer halo on hand detection
        * Directional tracking reticle points toward cursor position
        * Shockwave energy pulses on pinch / click
        * Distinct visual pulse on right-click
        * Vertical scroll chevrons showing scroll direction and intensity
        * Application launch holographic notification
    - Radar sweep line & conical light-cone
    - Orbiting constellation of 32 particles
    - Precision compass degree annotations
    - State-driven color engine (ACTIVE, READY, STANDBY, PAUSED, EMERGENCY_STOP)
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 320):
        super().__init__(parent)
        self.hud_size = size
        self.setMinimumSize(size, size)

        # Ring rotation angles (6 independent speeds, alternating CW/CCW)
        self._r = [0.0] * 6
        self._sweep = 0.0
        self._pulse = 0.0
        self._pulse_dir = 1.0
        self._hex_angle = 0.0
        self._cone_angle = 0.0
        self._annotation_phase = 0.0

        # Multi-layer shockwaves
        self._shockwaves: List[dict] = []

        # Orbiting particle constellation (small glowing nodes on 4 radii)
        self._particles: List[dict] = []
        self._init_particles()

        # Real-time gesture telemetry states
        self.system_state = "STANDBY"
        self.animations_enabled = True

        self.hand_detected: bool = False
        self.hand_norm_x: float = 0.5
        self.hand_norm_y: float = 0.5
        self.hand_angle: float = 0.0
        self.handedness: str = ""

        self.current_gesture: str = "NONE"
        self.last_action_text: str = ""
        self.scroll_intensity: float = 0.0  # -1.0 to 1.0 (negative = down, positive = up)
        self.scroll_decay: float = 0.0

        # App launch animation alert
        self.launch_alert_app: str = ""
        self.launch_alert_alpha: float = 0.0

        # Continuous timer (approx 30-35 fps)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _init_particles(self):
        self._particles = []
        radii = [0.38, 0.54, 0.70, 0.86]
        counts = [5, 7, 9, 11]
        for ri, (rad_frac, n) in enumerate(zip(radii, counts)):
            for i in range(n):
                self._particles.append({
                    "r_frac": rad_frac,
                    "angle": (i / n) * 360.0 + ri * 18.0,
                    "speed": (0.20 + ri * 0.09) * (1 if ri % 2 == 0 else -1),
                    "size": 2.2 + ri * 0.6,
                    "alpha_phase": random.uniform(0, 2 * math.pi),
                })

    def set_system_state(self, state: str) -> None:
        self.system_state = state
        self.update()

    def set_hand_presence(self, detected: bool, norm_x: float = 0.5, norm_y: float = 0.5, handedness: str = "") -> None:
        self.hand_detected = detected
        self.hand_norm_x = norm_x
        self.hand_norm_y = norm_y
        self.handedness = handedness
        if detected:
            # Angle in degrees from center (0.5, 0.5) to hand
            dx = norm_x - 0.5
            dy = norm_y - 0.5
            self.hand_angle = math.degrees(math.atan2(dy, dx))
        self.update()

    def set_gesture_telemetry(self, gesture: str, action: str = "", scroll_dy: float = 0.0) -> None:
        self.current_gesture = gesture
        if action:
            self.last_action_text = action
        if abs(scroll_dy) > 0.005:
            self.scroll_intensity = max(-1.0, min(1.0, scroll_dy * 25.0))
            self.scroll_decay = 1.0
        self.update()

    def trigger_pulse(self, shock_color: Optional[QColor] = None) -> None:
        """Triggers an expanding holographic energy shockwave."""
        col = shock_color or QColor(0, 240, 255)
        self._shockwaves.append({
            "radius": 15.0,
            "alpha": 1.0,
            "speed": 6.5,
            "color": col
        })

    def set_app_launch(self, app_name: str, success: bool = True) -> None:
        """Triggers an app launch confirmation holographic alert."""
        self.launch_alert_app = app_name
        self.launch_alert_alpha = 1.0
        col = QColor(0, 240, 255) if success else QColor(239, 68, 68)
        self.trigger_pulse(col)

    def set_animations_enabled(self, en: bool) -> None:
        self.animations_enabled = en
        if en and not self._timer.isActive():
            self._timer.start(33)
        elif not en:
            self._timer.stop()

    def _tick(self) -> None:
        if not self.animations_enabled or not self.isVisible():
            return

        state = self.system_state
        if state in ("ACTIVE", "READY"):
            m = 1.7
        elif state == "PAUSED":
            m = 0.35
        elif state == "EMERGENCY_STOP":
            m = 0.12
        else:
            m = 0.65

        # If hand detected, add energetic spin boost
        if self.hand_detected and state in ("ACTIVE", "READY"):
            m *= 1.25

        speeds = [0.65, -1.05, 1.55, -0.92, 2.1, -0.45]
        for i in range(6):
            self._r[i] = (self._r[i] + speeds[i] * m) % 360.0

        self._sweep = (self._sweep + 2.8 * m) % 360.0
        self._hex_angle = (self._hex_angle + 0.45 * m) % 360.0
        self._cone_angle = (self._cone_angle + 2.0 * m) % 360.0
        self._annotation_phase = (self._annotation_phase + 0.016 * m) % (2 * math.pi)

        # Core breathing
        self._pulse += 0.045 * self._pulse_dir * m
        if self._pulse >= 1.0:
            self._pulse = 1.0
            self._pulse_dir = -1.0
        elif self._pulse <= 0.0:
            self._pulse = 0.0
            self._pulse_dir = 1.0

        # Update shockwaves
        kept_shocks = []
        for s in self._shockwaves:
            s["radius"] += s["speed"]
            s["alpha"] = max(0.0, s["alpha"] - 0.045)
            if s["alpha"] > 0.01:
                kept_shocks.append(s)
        self._shockwaves = kept_shocks

        # Orbiting particles
        for pt in self._particles:
            pt["angle"] = (pt["angle"] + pt["speed"] * m) % 360.0
            pt["alpha_phase"] = (pt["alpha_phase"] + 0.055) % (2 * math.pi)

        # Scroll indicator decay
        if self.scroll_decay > 0:
            self.scroll_decay = max(0.0, self.scroll_decay - 0.06)

        # Launch alert decay
        if self.launch_alert_alpha > 0:
            self.launch_alert_alpha = max(0.0, self.launch_alert_alpha - 0.035)

        self.update()

    def _colors(self):
        s = self.system_state
        if s == "EMERGENCY_STOP":
            return QColor(239, 68, 68), QColor(220, 38, 38, 80), QColor(255, 120, 120, 40), "LOCKED"
        if s == "PAUSED":
            return QColor(99, 155, 210), QColor(60, 100, 160, 50), QColor(80, 140, 200, 25), "PAUSED"
        if s in ("STANDBY", "DISABLED"):
            return QColor(245, 158, 11), QColor(200, 110, 0, 60), QColor(230, 150, 30, 25), "STANDBY"
        # ACTIVE / READY
        return QColor(0, 240, 255), QColor(0, 200, 255, 75), QColor(0, 150, 220, 32), "ONLINE"

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = float(self.width()), float(self.height())
        cx = w / 2.0
        # Position core slightly above center to allow room for the holographic pedestal platform below
        cy = h * 0.46
        R = min(cx, cy) - 12.0
        if R < 35:
            return

        primary, glow_col, bg_glow, state_tag = self._colors()
        pr, pg, pb = primary.red(), primary.green(), primary.blue()

        # --- 0. Perspective Holographic Platform beneath the reactor ---
        self._draw_platform(p, cx, cy, R, primary)

        # --- 1. Deep background radial glow ---
        bg = QRadialGradient(cx, cy, R * 1.15)
        pulse_alpha = int(30 + 20 * self._pulse)
        bg.setColorAt(0.0, QColor(pr, pg, pb, pulse_alpha))
        bg.setColorAt(0.48, glow_col)
        bg.setColorAt(0.85, bg_glow)
        bg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawEllipse(QRectF(cx - R * 1.15, cy - R * 1.15, R * 2.3, R * 2.3))

        # --- 2. Conical "radar light cone" ---
        p.save()
        p.translate(cx, cy)
        p.rotate(self._cone_angle)
        cone_r = R * 0.94
        path = QPainterPath()
        path.moveTo(0, 0)
        path.arcTo(QRectF(-cone_r, -cone_r, cone_r * 2, cone_r * 2), 0, 32)
        path.lineTo(0, 0)
        cone_grad = QRadialGradient(0, 0, cone_r)
        cone_grad.setColorAt(0.0, QColor(pr, pg, pb, 40))
        cone_grad.setColorAt(0.65, QColor(pr, pg, pb, 14))
        cone_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(cone_grad))
        p.setPen(Qt.NoPen)
        p.drawPath(path)
        p.restore()

        # --- 3. Outermost precision tick ring (36 ticks with degree annotations) ---
        self._draw_tick_ring(p, cx, cy, R * 0.98, 36, 7, 3, primary, 160, 1.2)

        # --- 4. Hand Detection Halo (Outer Ring illumination) ---
        if self.hand_detected:
            halo_r = R * 0.95
            halo_pen = QPen(QColor(0, 255, 200, int(160 + 80 * math.sin(self._pulse * math.pi))), 2.2)
            p.setPen(halo_pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, halo_r * 2, halo_r * 2))

            # Directional tracking reticle pointing toward cursor position
            self._draw_tracking_indicator(p, cx, cy, halo_r, self.hand_angle, primary)

        # --- 5. Ring A -- Segmented arcs CW with glowing orbital nodes ---
        r_a = R * 0.88
        self._draw_arc_ring(p, cx, cy, r_a, self._r[0], 6, primary, 210, 2.0, 48)

        # --- 6. Ring B -- Dashed counter-CW frequency ring ---
        r_b = R * 0.76
        self._draw_dashed_ring(p, cx, cy, r_b, self._r[1], primary, 130, 1.2)

        # --- 7. Ring C -- Thin segmented CW faster ---
        r_c = R * 0.65
        self._draw_arc_ring(p, cx, cy, r_c, self._r[2], 8, primary, 150, 1.2, 32)

        # --- 8. Hexagonal geometry layer (slow rotation with energy spokes) ---
        self._draw_hex_layer(p, cx, cy, R * 0.53, self._hex_angle, primary)

        # --- 9. Ring D -- Innermost dotted CCW ring ---
        r_d = R * 0.42
        self._draw_dashed_ring(p, cx, cy, r_d, self._r[3], primary, 95, 1.0)

        # --- 10. Radar sweep line & arc glow ---
        p.save()
        p.translate(cx, cy)
        p.rotate(self._sweep)
        sweep_pen = QPen(QColor(pr, pg, pb, 220), 1.6)
        p.setPen(sweep_pen)
        p.drawLine(QPointF(0, 0), QPointF(R * 0.88, 0))
        arc_r = R * 0.88
        trail_pen = QPen(QColor(pr, pg, pb, 70), 1.0)
        p.setPen(trail_pen)
        p.drawArc(QRectF(-arc_r, -arc_r, arc_r * 2, arc_r * 2), 0, int(35 * 16))
        p.restore()

        # --- 11. Orbiting particle constellation ---
        for pt in self._particles:
            rad = pt["r_frac"] * R
            ang = math.radians(pt["angle"])
            px = cx + rad * math.cos(ang)
            py = cy + rad * math.sin(ang)
            alpha = int(140 + 100 * math.sin(pt["alpha_phase"]))
            sz = pt["size"]
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(pr, pg, pb, alpha)))
            p.drawEllipse(QRectF(px - sz / 2, py - sz / 2, sz, sz))

        # --- 12. Multi-layer expanding shockwaves ---
        for s in self._shockwaves:
            col = s["color"]
            shock_pen = QPen(QColor(col.red(), col.green(), col.blue(), int(230 * s["alpha"])), 2.0)
            p.setPen(shock_pen)
            p.setBrush(Qt.NoBrush)
            sr = s["radius"]
            p.drawEllipse(QRectF(cx - sr, cy - sr, sr * 2, sr * 2))

        # --- 13. Central Glowing Energy Core & N.E.X.U.S. Diamond Emblem ---
        r_core = R * 0.28
        core_grad = QRadialGradient(cx, cy, r_core)
        core_alpha = int(220 + 35 * self._pulse)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        core_grad.setColorAt(0.25, QColor(min(255, pr + 70), min(255, pg + 70), min(255, pb + 70), core_alpha))
        core_grad.setColorAt(0.60, QColor(pr, pg, pb, int(185 + 40 * self._pulse)))
        core_grad.setColorAt(0.90, QColor(pr // 2, pg // 2, pb // 2, 75))
        core_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(core_grad))
        p.setPen(QPen(QColor(255, 255, 255, 190), 1.0))
        p.drawEllipse(QRectF(cx - r_core, cy - r_core, r_core * 2, r_core * 2))

        # Inner N.E.X.U.S. geometric diamond core emblem
        emblem_r = r_core * 0.55
        p.save()
        p.translate(cx, cy)
        p.rotate(-self._hex_angle * 1.5)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.2))
        p.setBrush(Qt.NoBrush)
        diamond_pts = [
            QPointF(0, -emblem_r),
            QPointF(emblem_r * 0.86, 0),
            QPointF(0, emblem_r),
            QPointF(-emblem_r * 0.86, 0)
        ]
        p.drawPolygon(QPolygonF(diamond_pts))
        p.restore()

        # Central state tag text
        font = QFont("Consolas", max(7, int(R * 0.07)), QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(pr, pg, pb, 245))
        p.drawText(QRectF(cx - 60, cy - 10, 120, 20), Qt.AlignCenter, state_tag)

        # --- 14. Precision annotation ring (degree labels) ---
        ann_items = ["000°", "090°", "180°", "270°"]
        p.setFont(QFont("Consolas", max(5, int(R * 0.046))))
        p.setPen(QColor(pr, pg, pb, 115))
        for i, txt in enumerate(ann_items):
            ang = math.radians(i * 90 + self._annotation_phase * 25)
            tx = cx + (R * 1.02) * math.cos(ang) - 18
            ty = cy + (R * 1.02) * math.sin(ang) + 4
            p.drawText(QRectF(tx, ty, 36, 12), Qt.AlignCenter, txt)

        # --- 15. Scroll intensity chevron indicator (dynamic) ---
        if self.scroll_decay > 0.05:
            self._draw_scroll_indicator(p, cx, cy, R, primary)

        # --- 16. App Launch Notification Overlay ---
        if self.launch_alert_alpha > 0.05:
            self._draw_app_launch_badge(p, cx, cy, R, primary)

    # ---- Helper drawing routines ----
    def _draw_platform(self, p: QPainter, cx: float, cy: float, R: float, col: QColor) -> None:
        """Renders an angled perspective holographic emitter pedestal beneath the core."""
        plat_y = cy + R * 0.88
        plat_w = R * 1.6
        plat_h = R * 0.40

        # Outer emitter ellipse
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 60), 1.2))
        p.drawEllipse(QRectF(cx - plat_w / 2, plat_y - plat_h / 2, plat_w, plat_h))

        # Inner emitter ellipse
        iw, ih = plat_w * 0.75, plat_h * 0.75
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 45), 1.0))
        p.drawEllipse(QRectF(cx - iw / 2, plat_y - ih / 2, iw, ih))

        # Perspective radial grid lines
        grid_pen = QPen(QColor(col.red(), col.green(), col.blue(), 28), 0.8)
        p.setPen(grid_pen)
        for deg in range(0, 360, 30):
            rad = math.radians(deg)
            x1 = cx + (iw / 2) * math.cos(rad)
            y1 = plat_y + (ih / 2) * math.sin(rad)
            x2 = cx + (plat_w / 2) * math.cos(rad)
            y2 = plat_y + (plat_h / 2) * math.sin(rad)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Vertical upward emitter beam rays
        beam_pen = QPen(QColor(col.red(), col.green(), col.blue(), 20), 0.8)
        p.setPen(beam_pen)
        for offset_x in [-plat_w * 0.35, -plat_w * 0.15, plat_w * 0.15, plat_w * 0.35]:
            p.drawLine(QPointF(cx + offset_x, plat_y), QPointF(cx + offset_x * 0.6, cy + R * 0.3))

    def _draw_tracking_indicator(self, p: QPainter, cx: float, cy: float, r: float, angle_deg: float, col: QColor) -> None:
        """Draws an animated directional tracking reticle on the outer halo pointing toward cursor position."""
        p.save()
        p.translate(cx, cy)
        p.rotate(angle_deg)
        # Targeting pip
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.setBrush(QBrush(QColor(0, 240, 255, 180)))
        p.drawEllipse(QRectF(r - 4, -4, 8, 8))
        # Arrow bracket
        p.drawLine(QPointF(r + 8, -6), QPointF(r + 14, 0))
        p.drawLine(QPointF(r + 14, 0), QPointF(r + 8, 6))
        p.restore()

    def _draw_scroll_indicator(self, p: QPainter, cx: float, cy: float, R: float, col: QColor) -> None:
        """Draws glowing vertical chevron chevrons indicating scroll direction and speed."""
        alpha = int(220 * self.scroll_decay)
        is_up = self.scroll_intensity > 0
        p.save()
        p.setPen(QPen(QColor(0, 240, 255, alpha), 2.0))
        p.setFont(QFont("Consolas", 9, QFont.Bold))
        text = "SCROLL UP" if is_up else "SCROLL DOWN"
        badge_y = cy - R * 0.55 if is_up else cy + R * 0.55
        p.drawText(QRectF(cx - 60, badge_y - 12, 120, 24), Qt.AlignCenter, text)

        # Chevrons
        dir_mult = -1 if is_up else 1
        for i in range(3):
            cy_c = badge_y + dir_mult * (18 + i * 8)
            p.drawLine(QPointF(cx - 12, cy_c), QPointF(cx, cy_c + dir_mult * 5))
            p.drawLine(QPointF(cx, cy_c + dir_mult * 5), QPointF(cx + 12, cy_c))
        p.restore()

    def _draw_app_launch_badge(self, p: QPainter, cx: float, cy: float, R: float, col: QColor) -> None:
        """Holographic pop-up banner when an app is launched."""
        alpha = int(240 * self.launch_alert_alpha)
        bw, bh = 220, 36
        bx = cx - bw / 2
        by = cy - R * 0.65
        p.save()
        p.setBrush(QBrush(QColor(4, 16, 40, int(210 * self.launch_alert_alpha))))
        p.setPen(QPen(QColor(0, 240, 255, alpha), 1.5))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.setPen(QColor(0, 255, 180, alpha))
        p.drawText(QRectF(bx, by, bw, bh), Qt.AlignCenter, f"LAUNCHING: {self.launch_alert_app.upper()}")
        p.restore()

    def _draw_tick_ring(self, p, cx, cy, r, n_ticks, tick_long, tick_short, col, alpha, pen_w):
        p.save()
        p.translate(cx, cy)
        pen = QPen(QColor(col.red(), col.green(), col.blue(), alpha), pen_w)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(-r, -r, r * 2, r * 2))
        for i in range(n_ticks):
            ang = math.radians(i * (360 / n_ticks))
            tl = tick_long if i % (n_ticks // 4) == 0 else tick_short
            x1, y1 = (r - tl) * math.cos(ang), (r - tl) * math.sin(ang)
            x2, y2 = (r + 2) * math.cos(ang), (r + 2) * math.sin(ang)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.restore()

    def _draw_arc_ring(self, p, cx, cy, r, angle_offset, n_arcs, col, alpha, pen_w, arc_span):
        p.save()
        p.translate(cx, cy)
        p.rotate(angle_offset)
        pen = QPen(QColor(col.red(), col.green(), col.blue(), alpha), pen_w)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        gap = 360 // n_arcs
        for i in range(n_arcs):
            start = i * gap + 5
            p.drawArc(QRectF(-r, -r, r * 2, r * 2), int(start * 16), int(arc_span * 16))
            dot_ang = math.radians(start)
            dx, dy = r * math.cos(dot_ang), r * math.sin(dot_ang)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), min(255, alpha + 60))))
            p.drawEllipse(QRectF(dx - 2.5, dy - 2.5, 5, 5))
            p.setPen(pen)
        p.restore()

    def _draw_dashed_ring(self, p, cx, cy, r, angle_offset, col, alpha, pen_w):
        p.save()
        p.translate(cx, cy)
        p.rotate(angle_offset)
        dash_pen = QPen(QColor(col.red(), col.green(), col.blue(), alpha), pen_w, Qt.DashLine)
        dash_pen.setDashPattern([4, 6])
        p.setPen(dash_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(-r, -r, r * 2, r * 2))
        p.restore()

    def _draw_hex_layer(self, p, cx, cy, r, angle, col):
        p.save()
        p.translate(cx, cy)
        p.rotate(angle)
        hex_pen = QPen(QColor(col.red(), col.green(), col.blue(), 90), 1.0)
        p.setPen(hex_pen)
        p.setBrush(Qt.NoBrush)
        pts = [QPointF(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)))
               for a in range(0, 360, 60)]
        p.drawPolygon(QPolygonF(pts))
        spoke_pen = QPen(QColor(col.red(), col.green(), col.blue(), 45), 0.8)
        p.setPen(spoke_pen)
        for pt in pts:
            p.drawLine(QPointF(0, 0), pt)
        p.restore()


# Backwards compat alias
ArcReactorHUD = NexusCoreWidget


# ---------------------------------------------------------------------------
# WEBCAM HUD -- CINEMATIC OPTICAL TRACKING VIEWER
# ---------------------------------------------------------------------------
class WebcamHUDWidget(QWidget):
    """Cinematic live optical-tracking viewport with minimal corner brackets
    and subtle holographic grid. No thick borders."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.current_image: Optional[QImage] = None
        self.status_text = "STANDBY"
        self.gesture_text = "NONE"
        self.fps_value = 0.0

        # Scan line animation
        self._scan_y = 0.0
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._adv_scan)
        self._scan_timer.start(40)

        # Grid fade pulse
        self._grid_alpha = 0.0
        self._grid_dir = 1.0

    def _adv_scan(self):
        if not self.isVisible():
            return
        self._scan_y = (self._scan_y + 2.5) % max(1, self.height())
        self._grid_alpha += 0.015 * self._grid_dir
        if self._grid_alpha >= 1.0:
            self._grid_alpha = 1.0
            self._grid_dir = -1.0
        elif self._grid_alpha <= 0.0:
            self._grid_alpha = 0.0
            self._grid_dir = 1.0
        self.update()

    def update_frame(self, image: QImage, status: str, gesture: str, fps: float) -> None:
        self.current_image = image
        self.status_text = status
        self.gesture_text = gesture
        self.fps_value = fps
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(3, 7, 18))

        # Camera image
        if self.current_image and not self.current_image.isNull():
            img = self.current_image
            iw, ih = img.width(), img.height()
            aspect = iw / ih if ih > 0 else 1.33
            rh = h
            rw = int(rh * aspect)
            if rw > w:
                rw = w
                rh = int(rw / aspect)
            ox = (w - rw) // 2
            oy = (h - rh) // 2
            p.drawImage(QRect(ox, oy, rw, rh), img)
        else:
            p.setPen(QColor(0, 240, 255, 100))
            p.setFont(QFont("Consolas", 10, QFont.Bold))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                       "N.E.X.U.S. OPTICAL PIPELINE\nAWAITING SENSOR LINK...")

        # Subtle holographic grid
        grid_alpha = int(18 * self._grid_alpha)
        if grid_alpha > 2:
            grid_pen = QPen(QColor(0, 200, 255, grid_alpha), 0.5)
            p.setPen(grid_pen)
            step = max(30, w // 14)
            for gx in range(0, w, step):
                p.drawLine(gx, 0, gx, h)
            step_y = max(25, h // 10)
            for gy in range(0, h, step_y):
                p.drawLine(0, gy, w, gy)

        # Moving scan line
        scan_pen = QPen(QColor(0, 240, 255, 30), 1.0)
        p.setPen(scan_pen)
        sy = int(self._scan_y)
        p.drawLine(0, sy, w, sy)

        # Corner brackets (no rectangle border)
        b = QPen(QColor(0, 240, 255, 210), 2.0)
        p.setPen(b)
        blen = max(18, min(30, w // 18))
        marg = 8
        # TL
        p.drawLine(marg, marg, marg + blen, marg)
        p.drawLine(marg, marg, marg, marg + blen)
        # TR
        p.drawLine(w - marg, marg, w - marg - blen, marg)
        p.drawLine(w - marg, marg, w - marg, marg + blen)
        # BL
        p.drawLine(marg, h - marg, marg + blen, h - marg)
        p.drawLine(marg, h - marg, marg, h - marg - blen)
        # BR
        p.drawLine(w - marg, h - marg, w - marg - blen, h - marg)
        p.drawLine(w - marg, h - marg, w - marg, h - marg - blen)

        # Mid-edge tick marks
        mid_pen = QPen(QColor(0, 240, 255, 100), 1.0)
        p.setPen(mid_pen)
        tmarg = 4
        for tick_x in [w // 4, w // 2, 3 * w // 4]:
            p.drawLine(tick_x, tmarg, tick_x, tmarg + 8)
            p.drawLine(tick_x, h - tmarg, tick_x, h - tmarg - 8)
        for tick_y in [h // 4, h // 2, 3 * h // 4]:
            p.drawLine(tmarg, tick_y, tmarg + 8, tick_y)
            p.drawLine(w - tmarg, tick_y, w - tmarg - 8, tick_y)

        # FPS / status pill
        pill_w, pill_h = 190, 28
        p.setBrush(QBrush(QColor(4, 10, 26, 195)))
        p.setPen(QPen(QColor(0, 240, 255, 100), 0.8))
        p.drawRoundedRect(marg + 2, marg + 2, pill_w, pill_h, 4, 4)
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.setPen(QColor(0, 255, 180))
        p.drawText(marg + 10, marg + 18, f"FPS: {self.fps_value:.1f}")
        p.setPen(QColor(160, 210, 255))
        p.setFont(QFont("Consolas", 7))
        p.drawText(marg + 70, marg + 18, self.status_text[:18])

        # Gesture badge -- bottom center
        gest_str = f"GESTURE: {self.gesture_text}"
        badge_w = min(w - 40, 260)
        badge_h = 28
        bx = (w - badge_w) // 2
        by = h - badge_h - marg - 2
        p.setBrush(QBrush(QColor(5, 14, 36, 210)))
        p.setPen(QPen(QColor(0, 240, 255, 170), 1.2))
        p.drawRoundedRect(bx, by, badge_w, badge_h, 5, 5)
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(QColor(0, 240, 255))
        p.drawText(QRectF(bx, by, badge_w, badge_h), Qt.AlignCenter, gest_str)


# ---------------------------------------------------------------------------
# GLOW CARD -- minimal floating panel with corner brackets, no heavy border
# ---------------------------------------------------------------------------
class GlowCard(QFrame):
    """Transparent-look container with fine corner brackets and a slim title bar."""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.title = title.upper()
        self.setObjectName("GlowCard")
        self.setFrameShape(QFrame.NoFrame)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        blen = 14

        # Very faint fill
        p.fillRect(0, 0, w, h, QColor(8, 16, 36, 60))

        # Corner accents
        pen = QPen(QColor(0, 240, 255, 160), 1.5)
        p.setPen(pen)
        # TL
        p.drawLine(0, 0, blen, 0)
        p.drawLine(0, 0, 0, blen)
        # TR
        p.drawLine(w - 1, 0, w - 1 - blen, 0)
        p.drawLine(w - 1, 0, w - 1, blen)
        # BL
        p.drawLine(0, h - 1, blen, h - 1)
        p.drawLine(0, h - 1, 0, h - 1 - blen)
        # BR
        p.drawLine(w - 1, h - 1, w - 1 - blen, h - 1)
        p.drawLine(w - 1, h - 1, w - 1, h - 1 - blen)

        # Top separator for title area
        if self.title:
            sep_pen = QPen(QColor(0, 240, 255, 60), 0.8)
            p.setPen(sep_pen)
            p.drawLine(blen + 2, 22, w - blen - 2, 22)
            p.setFont(QFont("Consolas", 7, QFont.Bold))
            p.setPen(QColor(0, 200, 255, 180))
            p.drawText(blen + 6, 15, self.title)


# ---------------------------------------------------------------------------
# AUDIO LEVEL METER
# ---------------------------------------------------------------------------
class AudioLevelMeter(QWidget):
    """Segmented LED bar for system volume."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setMinimumWidth(100)
        self.level = 50

    def set_level(self, pct: int) -> None:
        self.level = max(0, min(100, pct))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = 22
        active = int(round(self.level / 100 * n))
        bw = max(3, (w - n * 2) / n)
        for i in range(n):
            bx = i * (bw + 2)
            if i < active:
                color = QColor(255, 50, 80) if i > 17 else (QColor(245, 158, 11) if i > 13 else QColor(0, 240, 255))
            else:
                color = QColor(12, 26, 50)
            p.fillRect(QRectF(bx, 2, bw, h - 4), color)


# ---------------------------------------------------------------------------
# TERMINAL LOG VIEW
# ---------------------------------------------------------------------------
class TerminalLogView(QTextEdit):
    """Monospace event stream with severity colour-coding."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("TerminalLog")
        self.document().setMaximumBlockCount(300)

    def append_log(self, level: str, message: str) -> None:
        lvl = level.upper()
        if "EMERGENCY" in lvl or "CRITICAL" in lvl:
            tc, mc = "#ef4444", "#fca5a5"
        elif "ERROR" in lvl:
            tc, mc = "#ef4444", "#f87171"
        elif "WARNING" in lvl or "WARN" in lvl:
            tc, mc = "#f59e0b", "#fde68a"
        elif "SUCCESS" in lvl or "ONLINE" in message:
            tc, mc = "#10b981", "#a7f3d0"
        elif any(k in message for k in ("GESTURE", "CLICK", "DRAG", "MOVE")):
            tc, mc = "#00f0ff", "#e0faff"
        else:
            tc, mc = "#38bdf8", "#cbd5e1"

        html = (f"<span style='color:{tc};font-weight:bold'>[{lvl}]</span> "
                f"<span style='color:{mc};font-family:Consolas'>{message}</span>")
        try:
            self.append(html)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 3D HOLOGRAPHIC LABORATORY -- MULTI-SCENE INTERACTIVE ENGINE
# ---------------------------------------------------------------------------
class HologramLabWidget(QWidget):
    """
    Cinematic 3D Holographic Laboratory.
    Renders 5 interactive holographic scenes with procedural 3D vector projection:
    1. SPACE: Planetary sphere, orbital rings, satellites, and atmospheric glow.
    2. ENGINEERING: Wireframe turbine / rotor assembly with stator casing and angled blades.
    3. ARCHITECTURE: Layered neural network / node graph with flowing synaptic data packets.
    4. REACTOR: 3D Arc-Reactor magnetic confinement rings and pulsating plasma prism.
    5. DATA: 3D cylindrical telemetry bar chart with dynamic vertical metric pillars.

    Full hand interaction support:
    - Pointing: Highlights active object
    - Pinch: Selects / locks object for manipulation
    - Hand displacement: Rotates object (pitch and yaw)
    - Two-finger scroll: Zooms object in / out
    - Scene switching via tab clicks or gesture trigger
    - Reset view functionality
    """

    SCENES = ["SPACE", "ENGINEERING", "ARCHITECTURE", "REACTOR", "DATA"]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.active_scene_idx: int = 0
        self.pitch: float = 18.0       # degrees
        self.yaw: float = 28.0         # degrees
        self.zoom: float = 1.0
        self.auto_rotate: bool = True

        self.is_selected: bool = False
        self.is_highlighted: bool = False

        self.show_grid: bool = True
        self.show_orbits: bool = True
        self.show_atmosphere: bool = True

        self._dragging: bool = False
        self._last_mouse_pos: QPointF = QPointF(0, 0)
        self._phase: float = 0.0

        # Space scene satellites
        self._satellites = [
            {"angle": 0.0, "speed": 1.2, "r_mult": 1.45, "inc": 24.0, "color": QColor(0, 240, 255)},
            {"angle": 120.0, "speed": -0.85, "r_mult": 1.65, "inc": -48.0, "color": QColor(56, 189, 248)},
            {"angle": 240.0, "speed": 1.6, "r_mult": 1.30, "inc": 75.0, "color": QColor(245, 158, 11)},
        ]

        # Scan line
        self._scan_y: float = 0.0

        # Animation timer (30 fps)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    @property
    def current_scene_name(self) -> str:
        return self.SCENES[self.active_scene_idx]

    def set_scene(self, scene_name_or_idx) -> None:
        if isinstance(scene_name_or_idx, int):
            self.active_scene_idx = scene_name_or_idx % len(self.SCENES)
        elif isinstance(scene_name_or_idx, str):
            name = scene_name_or_idx.upper()
            for idx, s in enumerate(self.SCENES):
                if s == name or s.startswith(name):
                    self.active_scene_idx = idx
                    break
        self.update()

    def next_scene(self) -> str:
        self.active_scene_idx = (self.active_scene_idx + 1) % len(self.SCENES)
        self.update()
        return self.current_scene_name

    def prev_scene(self) -> str:
        self.active_scene_idx = (self.active_scene_idx - 1) % len(self.SCENES)
        self.update()
        return self.current_scene_name

    def toggle_select(self) -> bool:
        self.is_selected = not self.is_selected
        self.update()
        return self.is_selected

    def select_object(self, selected: bool = True) -> None:
        self.is_selected = selected
        self.update()

    def highlight_object(self, highlighted: bool = True) -> None:
        self.is_highlighted = highlighted
        self.update()

    def reset_view(self) -> None:
        self.pitch = 18.0
        self.yaw = 28.0
        self.zoom = 1.0
        self.is_selected = False
        self.is_highlighted = False
        self.update()

    def rotate_by(self, dx: float, dy: float) -> None:
        self.yaw = (self.yaw + dx * 0.5) % 360.0
        self.pitch = max(-80.0, min(80.0, self.pitch - dy * 0.5))
        self.update()

    def zoom_by(self, delta: float) -> None:
        self.zoom = max(0.5, min(2.5, self.zoom + delta))
        self.update()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.05) % (2.0 * math.pi)
        if self.auto_rotate and not self._dragging:
            self.yaw = (self.yaw + 0.4) % 360.0

        for sat in self._satellites:
            sat["angle"] = (sat["angle"] + sat["speed"]) % 360.0

        self._scan_y = (self._scan_y + 2.0) % max(1, self.height())
        self.update()

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        # Check tab row click
        if pos.y() <= 30:
            tab_w = self.width() / len(self.SCENES)
            idx = int(pos.x() // tab_w)
            if 0 <= idx < len(self.SCENES):
                self.set_scene(idx)
                event.accept()
                return

        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_mouse_pos = pos
            self.is_selected = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.position() - self._last_mouse_pos
            self._last_mouse_pos = event.position()
            self.rotate_by(delta.x(), delta.y())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def wheelEvent(self, event) -> None:
        d = event.angleDelta().y() / 1200.0
        self.zoom_by(d)
        event.accept()

    @staticmethod
    def _rotate_3d(x: float, y: float, z: float, pitch_deg: float, yaw_deg: float) -> Tuple[float, float, float]:
        pr = math.radians(pitch_deg)
        yr = math.radians(yaw_deg)
        # Yaw (around Y axis)
        x1 = x * math.cos(yr) + z * math.sin(yr)
        y1 = y
        z1 = -x * math.sin(yr) + z * math.cos(yr)
        # Pitch (around X axis)
        x2 = x1
        y2 = y1 * math.cos(pr) - z1 * math.sin(pr)
        z2 = y1 * math.sin(pr) + z1 * math.cos(pr)
        return x2, y2, z2

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, (h / 2.0) + 8.0
        base_r = min(w, h - 35) * 0.28 * self.zoom

        # 1. Background dark translucent fill & boundary
        p.fillRect(0, 0, w, h, QColor(4, 9, 22, 235))

        # Selection halo / border
        if self.is_selected:
            p.setPen(QPen(QColor(0, 240, 255, 180), 1.5))
        elif self.is_highlighted:
            p.setPen(QPen(QColor(56, 189, 248, 120), 1.0))
        else:
            p.setPen(QPen(QColor(0, 240, 255, 60), 0.8))
        p.drawRect(QRectF(1, 1, w - 2, h - 2))

        # Corner brackets
        blen = 10
        p.setPen(QPen(QColor(0, 240, 255, 200 if self.is_selected else 140), 1.5))
        p.drawLine(1, 1, 1 + blen, 1); p.drawLine(1, 1, 1, 1 + blen)
        p.drawLine(w - 2, 1, w - 2 - blen, 1); p.drawLine(w - 2, 1, w - 2, 1 + blen)
        p.drawLine(1, h - 2, 1 + blen, h - 2); p.drawLine(1, h - 2, 1, h - 2 - blen)
        p.drawLine(w - 2, h - 2, w - 2 - blen, h - 2); p.drawLine(w - 2, h - 2, w - 2, h - 2 - blen)

        # 2. Top scene navigation tab bar
        self._draw_tabs(p, w)

        # 3. Render active 3D scene
        scene = self.current_scene_name
        if scene == "SPACE":
            self._draw_space_scene(p, cx, cy, base_r)
        elif scene == "ENGINEERING":
            self._draw_engineering_scene(p, cx, cy, base_r)
        elif scene == "ARCHITECTURE":
            self._draw_architecture_scene(p, cx, cy, base_r)
        elif scene == "REACTOR":
            self._draw_reactor_scene(p, cx, cy, base_r)
        elif scene == "DATA":
            self._draw_data_scene(p, cx, cy, base_r)

        # 4. Subtle vertical scanning line
        p.setPen(QPen(QColor(0, 240, 255, 30), 1.0))
        p.drawLine(QPointF(0, self._scan_y), QPointF(w, self._scan_y))

        # 5. Technical annotations and HUD overlay
        self._draw_hud_overlay(p, w, h, base_r)

    def _draw_tabs(self, p: QPainter, w: float) -> None:
        """Paints clickable holographic category tabs at top."""
        num_tabs = len(self.SCENES)
        tab_w = w / num_tabs
        tab_h = 24.0

        p.setFont(QFont("Consolas", 7, QFont.Bold))
        for i, sc in enumerate(self.SCENES):
            tx = i * tab_w
            is_active = (i == self.active_scene_idx)

            if is_active:
                p.fillRect(QRectF(tx + 1, 1, tab_w - 2, tab_h), QColor(0, 160, 240, 60))
                p.setPen(QPen(QColor(0, 240, 255, 220), 1.2))
                p.drawLine(QPointF(tx + 2, tab_h), QPointF(tx + tab_w - 2, tab_h))
                p.setPen(QColor(255, 255, 255))
            else:
                p.fillRect(QRectF(tx + 1, 1, tab_w - 2, tab_h), QColor(8, 16, 36, 120))
                p.setPen(QPen(QColor(0, 200, 255, 30), 0.8))
                p.drawRect(QRectF(tx + 1, 1, tab_w - 2, tab_h))
                p.setPen(QColor(120, 160, 200, 160))

            p.drawText(QRectF(tx, 2, tab_w, tab_h), Qt.AlignCenter, sc[:5])

    def _draw_space_scene(self, p: QPainter, cx: float, cy: float, base_r: float) -> None:
        """Scene 1: 3D Planetary Sphere with orbits and satellites."""
        if self.show_atmosphere:
            atmos = QRadialGradient(cx, cy, base_r * 1.35)
            atmos.setColorAt(0.0, QColor(0, 200, 255, 45))
            atmos.setColorAt(0.65, QColor(0, 160, 240, 25))
            atmos.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(atmos))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx - base_r * 1.35, cy - base_r * 1.35, base_r * 2.7, base_r * 2.7))

        if self.show_grid:
            for lat_deg in range(-60, 75, 25):
                lat_rad = math.radians(lat_deg)
                ring_r = base_r * math.cos(lat_rad)
                ring_y = -base_r * math.sin(lat_rad)

                pts_2d = []
                for lon_deg in range(0, 365, 12):
                    lon_rad = math.radians(lon_deg)
                    lx = ring_r * math.cos(lon_rad)
                    ly = ring_y
                    lz = ring_r * math.sin(lon_rad)
                    rx, ry, rz = self._rotate_3d(lx, ly, lz, self.pitch, self.yaw)
                    pts_2d.append((cx + rx, cy + ry, rz))

                for i in range(len(pts_2d) - 1):
                    x1, y1, z1 = pts_2d[i]
                    x2, y2, z2 = pts_2d[i + 1]
                    avg_z = (z1 + z2) / 2.0
                    alpha = 160 if avg_z >= 0 else 40
                    p.setPen(QPen(QColor(0, 240, 255, alpha), 1.0 if avg_z >= 0 else 0.6))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            for lon_deg in range(0, 180, 30):
                pts_2d = []
                for lat_deg in range(-90, 95, 12):
                    lat_rad = math.radians(lat_deg)
                    lx = base_r * math.cos(lat_rad) * math.cos(math.radians(lon_deg))
                    ly = -base_r * math.sin(lat_rad)
                    lz = base_r * math.cos(lat_rad) * math.sin(math.radians(lon_deg))
                    rx, ry, rz = self._rotate_3d(lx, ly, lz, self.pitch, self.yaw)
                    pts_2d.append((cx + rx, cy + ry, rz))

                for i in range(len(pts_2d) - 1):
                    x1, y1, z1 = pts_2d[i]
                    x2, y2, z2 = pts_2d[i + 1]
                    avg_z = (z1 + z2) / 2.0
                    alpha = 140 if avg_z >= 0 else 35
                    p.setPen(QPen(QColor(0, 240, 255, alpha), 1.0 if avg_z >= 0 else 0.6))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Outer rim outline
        p.setPen(QPen(QColor(0, 240, 255, 220), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - base_r, cy - base_r, base_r * 2, base_r * 2))

        if self.show_orbits:
            for sat in self._satellites:
                orb_r = base_r * sat["r_mult"]
                inc = sat["inc"]
                col = sat["color"]

                pts_orb = []
                for deg in range(0, 365, 12):
                    rad = math.radians(deg)
                    ox = orb_r * math.cos(rad)
                    oy = -orb_r * math.sin(rad) * math.sin(math.radians(inc))
                    oz = orb_r * math.sin(rad) * math.cos(math.radians(inc))
                    rx, ry, rz = self._rotate_3d(ox, oy, oz, self.pitch, self.yaw)
                    pts_orb.append((cx + rx, cy + ry, rz))

                for i in range(len(pts_orb) - 1):
                    x1, y1, z1 = pts_orb[i]
                    x2, y2, z2 = pts_orb[i + 1]
                    avg_z = (z1 + z2) / 2.0
                    alpha = 130 if avg_z >= 0 else 35
                    p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), alpha), 1.0, Qt.DashLine))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

                s_rad = math.radians(sat["angle"])
                sx = orb_r * math.cos(s_rad)
                sy = -orb_r * math.sin(s_rad) * math.sin(math.radians(inc))
                sz = orb_r * math.sin(s_rad) * math.cos(math.radians(inc))
                s_rx, s_ry, s_rz = self._rotate_3d(sx, sy, sz, self.pitch, self.yaw)
                scx, scy = cx + s_rx, cy + s_ry

                p.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
                p.setBrush(QBrush(col))
                p.drawEllipse(QRectF(scx - 3, scy - 3, 6, 6))

    def _draw_engineering_scene(self, p: QPainter, cx: float, cy: float, base_r: float) -> None:
        """Scene 2: 3D Wireframe Mechanical Turbine / Rotor Assembly."""
        casing_r = base_r * 1.15
        hub_r = base_r * 0.32
        length = base_r * 0.70

        # Stator casing rings at -z and +z
        for z_off in (-length * 0.5, length * 0.5):
            pts = []
            for deg in range(0, 365, 15):
                rad = math.radians(deg)
                lx = casing_r * math.cos(rad)
                ly = casing_r * math.sin(rad)
                rx, ry, rz = self._rotate_3d(lx, ly, z_off, self.pitch, self.yaw)
                pts.append((cx + rx, cy + ry, rz))
            for i in range(len(pts) - 1):
                x1, y1, z1 = pts[i]
                x2, y2, z2 = pts[i + 1]
                avg_z = (z1 + z2) / 2.0
                alpha = 180 if avg_z >= 0 else 50
                p.setPen(QPen(QColor(0, 240, 255, alpha), 1.2 if avg_z >= 0 else 0.8))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Longitudinal stator struts
        for deg in (0, 60, 120, 180, 240, 300):
            rad = math.radians(deg)
            lx = casing_r * math.cos(rad)
            ly = casing_r * math.sin(rad)
            rx1, ry1, rz1 = self._rotate_3d(lx, ly, -length * 0.5, self.pitch, self.yaw)
            rx2, ry2, rz2 = self._rotate_3d(lx, ly, length * 0.5, self.pitch, self.yaw)
            p.setPen(QPen(QColor(56, 189, 248, 120), 1.0))
            p.drawLine(QPointF(cx + rx1, cy + ry1), QPointF(cx + rx2, cy + ry2))

        # Central axle shaft
        p.setPen(QPen(QColor(245, 158, 11, 200), 1.5))
        s1x, s1y, _ = self._rotate_3d(0, 0, -length * 0.7, self.pitch, self.yaw)
        s2x, s2y, _ = self._rotate_3d(0, 0, length * 0.7, self.pitch, self.yaw)
        p.drawLine(QPointF(cx + s1x, cy + s1y), QPointF(cx + s2x, cy + s2y))

        # 8 Angled turbine blades radiating from central hub
        blade_phase = self._phase * 1.5
        num_blades = 8
        for b in range(num_blades):
            b_angle = math.radians((b * (360.0 / num_blades)) + math.degrees(blade_phase))
            twist = math.radians(22.0)

            # Blade root on hub
            hx1 = hub_r * math.cos(b_angle)
            hy1 = hub_r * math.sin(b_angle)
            # Blade tip on casing
            tx1 = (casing_r * 0.95) * math.cos(b_angle + twist)
            ty1 = (casing_r * 0.95) * math.sin(b_angle + twist)

            rx_h, ry_h, rz_h = self._rotate_3d(hx1, hy1, 0, self.pitch, self.yaw)
            rx_t, ry_t, rz_t = self._rotate_3d(tx1, ty1, length * 0.2, self.pitch, self.yaw)

            avg_z = (rz_h + rz_t) / 2.0
            p.setPen(QPen(QColor(0, 240, 255, 220 if avg_z >= 0 else 60), 1.6 if avg_z >= 0 else 0.8))
            p.drawLine(QPointF(cx + rx_h, cy + ry_h), QPointF(cx + rx_t, cy + ry_t))

            # Blade thickness strut
            rx_t2, ry_t2, _ = self._rotate_3d(tx1, ty1, -length * 0.1, self.pitch, self.yaw)
            p.setPen(QPen(QColor(56, 189, 248, 130 if avg_z >= 0 else 30), 0.8))
            p.drawLine(QPointF(cx + rx_t, cy + ry_t), QPointF(cx + rx_t2, cy + ry_t2))

    def _draw_architecture_scene(self, p: QPainter, cx: float, cy: float, base_r: float) -> None:
        """Scene 3: 3D Layered Neural Network / Node Graph with Synaptic Flow."""
        # 4 distinct depth layers
        layers = [
            {"z": -base_r * 0.70, "nodes": [(-0.4, -0.4), (-0.4, 0.4), (0.4, 0.0)], "color": QColor(56, 189, 248)},
            {"z": -base_r * 0.22, "nodes": [(-0.6, -0.6), (-0.6, 0.0), (-0.6, 0.6), (0.2, -0.3), (0.2, 0.3)], "color": QColor(0, 240, 255)},
            {"z": base_r * 0.22,  "nodes": [(-0.3, -0.5), (-0.3, 0.5), (0.5, -0.3), (0.5, 0.3)], "color": QColor(0, 240, 255)},
            {"z": base_r * 0.70,  "nodes": [(0.0, -0.35), (0.0, 0.35)], "color": QColor(245, 158, 11)},
        ]

        # Calculate 3D projected points for each node
        layer_projected = []
        for l_idx, layer in enumerate(layers):
            pts = []
            for nx, ny in layer["nodes"]:
                lx = nx * base_r * 1.1
                ly = ny * base_r * 1.1
                lz = layer["z"]
                rx, ry, rz = self._rotate_3d(lx, ly, lz, self.pitch, self.yaw)
                pts.append((cx + rx, cy + ry, rz))
            layer_projected.append(pts)

        # Draw synaptic connection lines between adjacent layers
        for l_idx in range(len(layer_projected) - 1):
            src_pts = layer_projected[l_idx]
            dst_pts = layer_projected[l_idx + 1]
            for s_pt in src_pts:
                for d_pt in dst_pts:
                    avg_z = (s_pt[2] + d_pt[2]) / 2.0
                    alpha = 75 if avg_z >= 0 else 20
                    p.setPen(QPen(QColor(0, 200, 255, alpha), 0.7))
                    p.drawLine(QPointF(s_pt[0], s_pt[1]), QPointF(d_pt[0], d_pt[1]))

                    # Pulsing data packet along synapse
                    t = (self._phase * 0.8 + (s_pt[0] + d_pt[1]) * 0.01) % 1.0
                    px = s_pt[0] + (d_pt[0] - s_pt[0]) * t
                    py = s_pt[1] + (d_pt[1] - s_pt[1]) * t
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor(255, 255, 255, int(180 if avg_z >= 0 else 60))))
                    p.drawEllipse(QRectF(px - 1.5, py - 1.5, 3.0, 3.0))

        # Draw glowing node spheres
        for l_idx, pts in enumerate(layer_projected):
            col = layers[l_idx]["color"]
            for pt in pts:
                sz = 7.0 if pt[2] >= 0 else 4.5
                p.setPen(QPen(QColor(255, 255, 255, 220), 1.0))
                p.setBrush(QBrush(col))
                p.drawEllipse(QRectF(pt[0] - sz / 2.0, pt[1] - sz / 2.0, sz, sz))

    def _draw_reactor_scene(self, p: QPainter, cx: float, cy: float, base_r: float) -> None:
        """Scene 4: 3D Arc-Reactor Multi-Tier Core & Luminous Plasma Prism."""
        # Multi-tiered rotating concentric rings
        ring_radii = [base_r * 0.45, base_r * 0.75, base_r * 1.05]
        speeds = [1.2, -0.9, 0.6]

        for idx, (r, sp) in enumerate(zip(ring_radii, speeds)):
            rot_yaw = self.yaw + math.degrees(self._phase * sp)
            rot_pitch = self.pitch + (idx * 15.0)

            pts = []
            for deg in range(0, 365, 12):
                rad = math.radians(deg)
                lx = r * math.cos(rad)
                ly = r * math.sin(rad)
                rx, ry, rz = self._rotate_3d(lx, ly, 0, rot_pitch, rot_yaw)
                pts.append((cx + rx, cy + ry, rz))

            for i in range(len(pts) - 1):
                x1, y1, z1 = pts[i]
                x2, y2, z2 = pts[i + 1]
                avg_z = (z1 + z2) / 2.0
                alpha = 200 if avg_z >= 0 else 60
                col = QColor(0, 240, 255, alpha) if idx != 1 else QColor(56, 189, 248, alpha)
                p.setPen(QPen(col, 1.3 if avg_z >= 0 else 0.8))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # 6 Magnetic coil blocks on outer ring
            if idx == 2:
                for b_deg in range(0, 360, 60):
                    b_rad = math.radians(b_deg)
                    lx = r * math.cos(b_rad)
                    ly = r * math.sin(b_rad)
                    rx, ry, rz = self._rotate_3d(lx, ly, 0, rot_pitch, rot_yaw)
                    p.setPen(QPen(QColor(245, 158, 11, 220), 1.2))
                    p.setBrush(QBrush(QColor(10, 25, 55)))
                    p.drawRect(QRectF(cx + rx - 5, cy + ry - 4, 10, 8))

        # Central Arc Reactor Energy Prism (3D Octahedron)
        pr_r = base_r * 0.28
        verts = [
            (0, -pr_r * 1.3, 0),   # Top
            (0, pr_r * 1.3, 0),    # Bottom
            (-pr_r, 0, -pr_r),
            (pr_r, 0, -pr_r),
            (pr_r, 0, pr_r),
            (-pr_r, 0, pr_r)
        ]
        proj_verts = []
        for vx, vy, vz in verts:
            rx, ry, rz = self._rotate_3d(vx, vy, vz, self.pitch, self.yaw + math.degrees(self._phase * 2.0))
            proj_verts.append((cx + rx, cy + ry, rz))

        # Connect top and bottom to base polygon
        edges = [
            (0, 2), (0, 3), (0, 4), (0, 5),
            (1, 2), (1, 3), (1, 4), (1, 5),
            (2, 3), (3, 4), (4, 5), (5, 2)
        ]
        for v1, v2 in edges:
            p1 = proj_verts[v1]
            p2 = proj_verts[v2]
            p.setPen(QPen(QColor(0, 240, 255, 220), 1.4))
            p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Inner plasma glow
        core_glow = QRadialGradient(cx, cy, pr_r * 1.2)
        core_glow.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_glow.setColorAt(0.4, QColor(0, 240, 255, 160))
        core_glow.setColorAt(1.0, QColor(0, 100, 220, 0))
        p.setBrush(QBrush(core_glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - pr_r, cy - pr_r, pr_r * 2, pr_r * 2))

    def _draw_data_scene(self, p: QPainter, cx: float, cy: float, base_r: float) -> None:
        """Scene 5: 3D Holographic Cylindrical Telemetry Bar Chart."""
        grid_r = base_r * 1.15
        num_bars = 8

        # Perspective ground grid ellipse
        pts_grid = []
        for deg in range(0, 365, 15):
            rad = math.radians(deg)
            lx = grid_r * math.cos(rad)
            lz = grid_r * math.sin(rad)
            rx, ry, rz = self._rotate_3d(lx, base_r * 0.45, lz, self.pitch, self.yaw)
            pts_grid.append((cx + rx, cy + ry, rz))
        for i in range(len(pts_grid) - 1):
            x1, y1, z1 = pts_grid[i]
            x2, y2, z2 = pts_grid[i + 1]
            p.setPen(QPen(QColor(0, 240, 255, 70), 1.0))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Vertical 3D Bar Pillars
        trend_pts = []
        for i in range(num_bars):
            ang = math.radians(i * (360.0 / num_bars))
            lx = (grid_r * 0.75) * math.cos(ang)
            lz = (grid_r * 0.75) * math.sin(ang)

            # Bar height oscillates smoothly
            h_val = base_r * (0.35 + 0.35 * math.sin(self._phase + i * 0.78))
            base_y = base_r * 0.45
            top_y = base_y - h_val

            rx_b, ry_b, rz_b = self._rotate_3d(lx, base_y, lz, self.pitch, self.yaw)
            rx_t, ry_t, rz_t = self._rotate_3d(lx, top_y, lz, self.pitch, self.yaw)

            # Pillar vertical stem
            avg_z = (rz_b + rz_t) / 2.0
            p.setPen(QPen(QColor(0, 240, 255, 220 if avg_z >= 0 else 80), 3.0))
            p.drawLine(QPointF(cx + rx_b, cy + ry_b), QPointF(cx + rx_t, cy + ry_t))

            # Pillar top cap
            p.setPen(QPen(QColor(255, 255, 255, 240), 1.0))
            p.setBrush(QBrush(QColor(245, 158, 11) if i % 2 == 0 else QColor(0, 240, 255)))
            p.drawEllipse(QRectF(cx + rx_t - 4, cy + ry_t - 4, 8, 8))

            trend_pts.append((cx + rx_t, cy + ry_t, rz_t))

        # Draw connecting trend ribbon around bar tops
        for i in range(len(trend_pts)):
            p1 = trend_pts[i]
            p2 = trend_pts[(i + 1) % len(trend_pts)]
            p.setPen(QPen(QColor(56, 189, 248, 120), 1.0, Qt.DashLine))
            p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

    def _draw_hud_overlay(self, p: QPainter, w: float, h: float, base_r: float) -> None:
        """Draws floating scientific telemetry and interactive status badge."""
        # Status Badge
        badge_y = 32
        if self.is_selected:
            p.fillRect(QRectF(8, badge_y, 145, 14), QColor(0, 240, 255, 45))
            p.setPen(QPen(QColor(0, 240, 255, 220), 1.0))
            p.drawRect(QRectF(8, badge_y, 145, 14))
            p.setFont(QFont("Consolas", 6, QFont.Bold))
            p.setPen(QColor(0, 240, 255))
            p.drawText(12, badge_y + 10, "● OBJECT: SELECTED (LOCKED)")
        elif self.is_highlighted:
            p.fillRect(QRectF(8, badge_y, 140, 14), QColor(56, 189, 248, 30))
            p.setPen(QPen(QColor(56, 189, 248, 160), 0.8))
            p.drawRect(QRectF(8, badge_y, 140, 14))
            p.setFont(QFont("Consolas", 6, QFont.Bold))
            p.setPen(QColor(56, 189, 248))
            p.drawText(12, badge_y + 10, "○ OBJECT: HIGHLIGHTED")

        # Bottom telemetry
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(0, 240, 255, 210))
        p.drawText(8, h - 20, f"3D LAB // {self.current_scene_name}")

        p.setFont(QFont("Consolas", 6))
        p.setPen(QColor(160, 210, 255, 180))
        p.drawText(8, h - 8, f"ROT: P={self.pitch:.0f}° Y={self.yaw:.0f}° | ZOOM={self.zoom:.1f}X")
        p.drawText(w - 180, h - 8, "PINCH: SELECT | MOVE: ROTATE | SCROLL: ZOOM")


# Alias for backward compatibility across existing references
HolographicGlobeWidget = HologramLabWidget


# ---------------------------------------------------------------------------
# AI ASSISTANT VISUALIZER
# ---------------------------------------------------------------------------
class AIAssistantWidget(QWidget):
    """Futuristic visualizer for the N.E.X.U.S. AI assistant."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.status = "ONLINE"
        self.mic_active = True
        self.command_text = "SYSTEM STANDBY"
        self.response_text = "Awaiting audio or gesture command."
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def set_command(self, cmd: str, resp: str = ""):
        self.command_text = cmd.upper()
        if resp:
            self.response_text = resp
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())

        # Background
        p.fillRect(0, 0, w, h, QColor(4, 10, 26, 180))
        p.setPen(QPen(QColor(0, 200, 255, 40), 0.8))
        p.drawRect(QRectF(1, 1, w - 2, h - 2))

        # Equalizer audio wave
        bars = 18
        bw = max(2, (w * 0.40) / bars - 2)
        eq_cx = w * 0.24
        eq_cy = h * 0.52

        for i in range(bars):
            dist_c = abs(i - bars / 2) / (bars / 2)
            sine_h = math.sin(self._phase + i * 0.45) * 0.5 + 0.5
            bar_h = max(4.0, (18.0 - dist_c * 10.0) * sine_h)
            bx = eq_cx + (i - bars / 2) * (bw + 2)

            col = QColor(0, 240, 255) if i % 2 == 0 else QColor(56, 189, 248)
            p.fillRect(QRectF(bx, eq_cy - bar_h / 2, bw, bar_h), col)

        # Central AI Core circle
        p.setPen(QPen(QColor(0, 240, 255, 200), 1.2))
        p.setBrush(QBrush(QColor(0, 240, 255, 30)))
        p.drawEllipse(QRectF(eq_cx - 16, eq_cy - 16, 32, 32))

        # Status text column
        tx = w * 0.48
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.setPen(QColor(0, 240, 255))
        p.drawText(QRectF(tx, 10, w - tx - 8, 16), Qt.AlignLeft, "N.E.X.U.S. AI CORE")

        p.setFont(QFont("Consolas", 7))
        p.setPen(QColor(16, 185, 129))
        p.drawText(QRectF(tx, 26, w - tx - 8, 14), Qt.AlignLeft, "STATUS: ACTIVE // VOICE SYNC")

        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(245, 158, 11))
        p.drawText(QRectF(tx, 44, w - tx - 8, 16), Qt.AlignLeft, f"> {self.command_text[:22]}")

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(180, 220, 255))
        p.drawText(QRectF(tx, 62, w - tx - 8, 36), Qt.AlignLeft | Qt.TextWordWrap, self.response_text[:70])


# ---------------------------------------------------------------------------
# ROBOTIC ARMOR / WIREFRAME BLUEPRINT
# ---------------------------------------------------------------------------
class ArmorTelemetryWidget(QWidget):
    """Futuristic wireframe schematic of robotic armor chassis and subsystems."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(130)
        self._scan_y = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def _tick(self):
        if not self.isVisible():
            return
        self._scan_y = (self._scan_y + 1.8) % max(1, self.height())
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cx = w * 0.32
        cy = h * 0.50

        # Background
        p.fillRect(0, 0, w, h, QColor(4, 9, 22, 200))
        p.setPen(QPen(QColor(0, 200, 255, 45), 0.8))
        p.drawRect(QRectF(1, 1, w - 2, h - 2))

        # Armor vector silhouette
        pen_wire = QPen(QColor(0, 240, 255, 170), 1.0)
        p.setPen(pen_wire)
        p.setBrush(Qt.NoBrush)

        # Helmet
        p.drawRoundedRect(QRectF(cx - 10, cy - 42, 20, 22), 4, 4)
        # Eye slots
        p.drawLine(QPointF(cx - 6, cy - 30), QPointF(cx - 2, cy - 30))
        p.drawLine(QPointF(cx + 2, cy - 30), QPointF(cx + 6, cy - 30))
        # Torso
        p.drawPolygon(QPolygonF([
            QPointF(cx - 24, cy - 18),
            QPointF(cx + 24, cy - 18),
            QPointF(cx + 16, cy + 22),
            QPointF(cx - 16, cy + 22)
        ]))
        # Chest Arc Reactor
        p.setPen(QPen(QColor(0, 255, 240, 240), 1.2))
        p.setBrush(QBrush(QColor(0, 240, 255, 80)))
        p.drawEllipse(QRectF(cx - 6, cy - 8, 12, 12))
        p.setBrush(Qt.NoBrush)
        p.setPen(pen_wire)

        # Shoulders / arms
        p.drawLine(QPointF(cx - 24, cy - 18), QPointF(cx - 36, cy + 4))
        p.drawLine(QPointF(cx + 24, cy - 18), QPointF(cx + 36, cy + 4))
        p.drawLine(QPointF(cx - 36, cy + 4), QPointF(cx - 38, cy + 26))
        p.drawLine(QPointF(cx + 36, cy + 4), QPointF(cx + 38, cy + 26))

        # Repulsor hand nodes
        p.drawEllipse(QRectF(cx - 40, cy + 24, 5, 5))
        p.drawEllipse(QRectF(cx + 35, cy + 24, 5, 5))

        # Scan line
        p.setPen(QPen(QColor(0, 240, 255, 40), 1.0))
        p.drawLine(QPointF(0, self._scan_y), QPointF(w, self._scan_y))

        # Callout annotations on the right
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(0, 240, 255))
        tx = w * 0.62
        p.drawText(QRectF(tx, 14, w - tx - 6, 14), Qt.AlignLeft, "MK-85 TELEMETRY")

        p.setFont(QFont("Consolas", 6))
        p.setPen(QColor(160, 210, 255))
        p.drawText(QRectF(tx, 32, w - tx - 6, 14), Qt.AlignLeft, "ARMOR: 100% NOMINAL")
        p.drawText(QRectF(tx, 48, w - tx - 6, 14), Qt.AlignLeft, "REPULSOR: ARMED")
        p.drawText(QRectF(tx, 64, w - tx - 6, 14), Qt.AlignLeft, "SYNC LINK: ACTIVE")
        p.drawText(QRectF(tx, 80, w - tx - 6, 14), Qt.AlignLeft, "COOLANT: 98.2%")


# ---------------------------------------------------------------------------
# GESTURE GUIDE REFERENCE CARD
# ---------------------------------------------------------------------------
class GestureGuideWidget(QWidget):
    """Futuristic HUD card illustrating supported hand gestures."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(130)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())

        # Background
        p.fillRect(0, 0, w, h, QColor(4, 9, 22, 200))
        p.setPen(QPen(QColor(0, 200, 255, 40), 0.8))
        p.drawRect(QRectF(1, 1, w - 2, h - 2))

        # Title
        p.setFont(QFont("Consolas", 7, QFont.Bold))
        p.setPen(QColor(0, 240, 255))
        p.drawText(8, 16, "GESTURE INTELLIGENCE MATRIX")

        # 2-column gesture list
        items = [
            ("INDEX POINT", "CURSOR MOVE"),
            ("THUMB PINCH", "LEFT CLICK"),
            ("HOLD PINCH", "DRAG & DROP"),
            ("THUMB+MID", "RIGHT CLICK"),
            ("2 FINGERS", "SCROLL UP/DN"),
            ("CLOSED FIST", "EMERGENCY STOP"),
        ]

        p.setFont(QFont("Consolas", 6))
        y = 32
        for i, (gest, act) in enumerate(items):
            col_x = 8 if i < 3 else w / 2.0 + 4
            row_y = y + (i % 3) * 28

            p.setPen(QColor(56, 189, 248))
            p.drawText(col_x, row_y, gest)
            p.setPen(QColor(16, 185, 129))
            p.drawText(col_x, row_y + 12, f"-> {act}")
