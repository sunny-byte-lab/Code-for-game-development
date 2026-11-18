"""N.E.X.U.S. Global Air Keyboard Overlay Window.
Non-Focus-Stealing Floating Holographic HUD for OS-Wide Typing into Chrome, Word, Notepad, VS Code, etc.
"""

import sys
import time
import math
import ctypes
from typing import Optional, List, Any

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, Slot
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient,
    QRadialGradient, QPainterPath, QScreen
)
from PySide6.QtWidgets import QWidget, QApplication

from app.theme import (
    ACCENT_CYAN, ACCENT_ICY_BLUE, ACCENT_BLUE, ACCENT_GOLD,
    ACCENT_GREEN, ACCENT_RED, BG_DARK_NAVY, TEXT_PRIMARY, TEXT_MUTED
)
from app.holographic_keyboard import HolographicKeyboardWidget, KeyDef, FingerAirState


class GlobalKeyboardOverlay(QWidget):
    """
    Floating, semi-transparent, always-on-top holographic keyboard overlay.
    Guaranteed NOT to steal focus from external applications (via WS_EX_NOACTIVATE).
    """

    overlay_closed = Signal()

    def __init__(self, keyboard_widget: HolographicKeyboardWidget, parent: Optional[QWidget] = None):
        super().__init__(None)  # Independent top-level window
        self.keyboard_widget = keyboard_widget

        # Configure non-focus-stealing window flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        # Default size and positioning (bottom center of primary screen)
        screen = QApplication.primaryScreen()
        geom = screen.geometry() if screen else None
        sw = geom.width() if geom else 1920
        sh = geom.height() if geom else 1080

        w = min(1100, int(sw * 0.70))
        h = min(360, int(sh * 0.38))
        x = (sw - w) // 2
        y = sh - h - 35
        self.setGeometry(x, y, w, h)

        # Dragging state for moving overlay
        self._dragging: bool = False
        self._drag_pos: QPointF = QPointF()

        # Connect repaint timer at 30 FPS to sync shockwaves and finger reticles
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_tick)
        self.anim_timer.start(33)

    @property
    def is_visible(self) -> bool:
        return self.isVisible()

    def toggle_overlay(self) -> bool:
        if self.isVisible():
            self.hide()
            self.overlay_closed.emit()
            return False
        else:
            self.show()
            return True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._enforce_no_activate()
        # Sync keyboard widget geometry to overlay dimensions
        self.keyboard_widget.resize(self.width(), self.height())
        self.keyboard_widget._recalculate_key_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.keyboard_widget.resize(self.width(), self.height())
        self.keyboard_widget._recalculate_key_geometry()

    def _enforce_no_activate(self) -> None:
        """Applies Win32 WS_EX_NOACTIVATE style so clicking/rendering never steals focus."""
        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOOLWINDOW = 0x00000080
                cur_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur_style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            except Exception:
                pass

    def _on_tick(self) -> None:
        if self.isVisible():
            self.update()

    def mousePressEvent(self, event) -> None:
        # Allow user to drag overlay from top bar
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 36:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        event.accept()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        w = float(self.width())
        h = float(self.height())

        # 1. Holographic Backdrop (Glassmorphic dark gradient)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(4, 4, w - 8, h - 8), 12, 12)

        bg_grad = QLinearGradient(0, 0, 0, h)
        bg_grad.setColorAt(0.0, QColor(2, 8, 20, 225))
        bg_grad.setColorAt(0.5, QColor(4, 14, 32, 215))
        bg_grad.setColorAt(1.0, QColor(2, 6, 16, 235))
        p.fillPath(bg_path, bg_grad)

        # Border glow
        p.setPen(QPen(QColor(0, 240, 255, 160), 1.5))
        p.drawPath(bg_path)

        # 2. Header Status Bar
        p.setPen(QPen(QColor(0, 200, 255, 40), 1))
        p.drawLine(8, 36, int(w - 8), 36)

        # Title and target window readout
        target = "Active Window"
        if hasattr(self.keyboard_widget, "keyboard_service") and self.keyboard_widget.keyboard_service:
            target = self.keyboard_widget.keyboard_service.get_active_target_window()

        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.setPen(QColor(ACCENT_CYAN))
        p.drawText(QRectF(16, 8, 320, 22), Qt.AlignLeft | Qt.AlignVCenter, "⚡ N.E.X.U.S. // GLOBAL AIR KEYBOARD")

        p.setPen(QColor(ACCENT_GREEN))
        p.drawText(QRectF(340, 8, w - 500, 22), Qt.AlignLeft | Qt.AlignVCenter, f"TARGET: {target[:40]}")

        # Shortcut hints on the right
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(w - 180, 8, 164, 22), Qt.AlignRight | Qt.AlignVCenter, "[ESC / CTRL+K: CLOSE]")

        # 3. Delegate rendering of keys, shockwaves, and finger reticles to shared keyboard widget
        self.keyboard_widget._draw_keys(p)
        self.keyboard_widget._draw_finger_reticles(p)

        # 4. Corner HUD brackets
        p.setPen(QPen(QColor(0, 240, 255, 200), 2))
        blen = 14
        # Top-left
        p.drawLine(8, 8, 8 + blen, 8)
        p.drawLine(8, 8, 8, 8 + blen)
        # Top-right
        p.drawLine(int(w - 8), 8, int(w - 8 - blen), 8)
        p.drawLine(int(w - 8), 8, int(w - 8), 8 + blen)
        # Bottom-left
        p.drawLine(8, int(h - 8), 8 + blen, int(h - 8))
        p.drawLine(8, int(h - 8), 8, int(h - 8 - blen))
        # Bottom-right
        p.drawLine(int(w - 8), int(h - 8), int(w - 8 - blen), int(h - 8))
        p.drawLine(int(w - 8), int(h - 8), int(w - 8), int(h - 8 - blen))
